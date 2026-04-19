"""
collector.py - Main collection orchestrator.

Implements the full collection cycle described in the specification:
1. Load config.
2. Discover all available channels from the Telegram account.
3. For each channel, load state.
4. Fetch new messages from Telegram.
5. Normalize and write to raw storage atomically.
6. Update state only after confirmed write.
7. Record run log.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

from telethon import TelegramClient

from config_loader import AppConfig, load_app_config
from fetcher import fetch_messages
from logger import get_logger, set_run_context, setup_logger
from run_log import build_run_log, write_run_log
from state import (
    build_error_state,
    build_success_state,
    load_state,
    save_state,
)
from storage import append_messages, normalize_message
from utils import generate_run_id, set_workspace_root_from_env


def _is_channel_excluded(dialog, exclude_values):
    """Return True when the discovered channel matches configured exclusions."""
    if not exclude_values:
        return False

    channel_id = str(getattr(dialog, "id", "")).strip().lower()
    username = str(getattr(dialog.entity, "username", "") or "").strip().lower()
    title = str(getattr(dialog, "title", "") or "").strip().lower()

    return any(value == channel_id or value == username or value == title for value in exclude_values)


async def process_channel(
    client: TelegramClient,
    channel,  # Now a Telethon Dialog object
    config: AppConfig,
    run_id: str,
) -> dict:
    """Process a single channel. Returns a result dict for the run log."""
    log = get_logger()
    base_path = config.storage.base_path
    
    # Use numeric ID for the key to be unique and consistent
    channel_id = str(channel.id)
    channel_name = getattr(channel, "title", str(channel.id))
    channel_username = getattr(channel.entity, "username", None)
    
    channel_key = f"channel_{channel_id}"

    set_run_context(run_id, channel_key)

    existing_state = load_state(base_path, channel_key)
    log.info("Processing channel: '%s' (id=%s)", channel_name, channel_id)

    # Determine starting point
    if existing_state and existing_state.get("last_success_message_id"):
        min_id = existing_state["last_success_message_id"]
        # Apply overlap: go back overlap_messages positions to catch edits
        min_id = max(0, min_id - config.collector.overlap_messages)
        log.info("Resuming from message_id >= %d (with overlap)", min_id)
    else:
        min_id = 0
        log.info(
            "New channel, fetching up to %d initial messages",
            config.collector.initial_search_depth,
        )

    try:
        # For new channels limit how many messages to fetch upfront;
        # for known channels fetch all messages since min_id (no limit).
        fetch_limit = (
            config.collector.initial_search_depth if not existing_state else None
        )
        raw_msgs = await fetch_messages(
            client=client,
            channel_entity=channel.entity,
            channel_name=channel_name,
            min_id=min_id,
            batch_size=config.collector.batch_size,
            retry_count=config.collector.retry_count,
            retry_backoff=config.collector.retry_backoff_seconds,
            limit=fetch_limit,
        )
    except Exception as e:
        log.error("Failed to fetch messages for '%s': %s", channel_name, str(e))
        err_state = build_error_state(
            channel_key, channel_name, channel_username, str(e), existing_state
        )
        save_state(base_path, channel_key, err_state)
        return {
            "channel": channel_key,
            "status": "error",
            "error": str(e),
            "messages_collected": 0,
        }

    if not raw_msgs:
        log.info("No new messages for channel %s", channel_key)
        return {
            "channel": channel_key,
            "status": "ok",
            "messages_collected": 0,
            "messages_added": 0,
            "messages_updated": 0,
        }

    # Normalize messages (updates will be handled in storage)
    normalized = []
    for msg in raw_msgs:
        n = normalize_message(msg, channel_id, channel_username, run_id)
        normalized.append(n)

    log.info("Messages to process: %d", len(normalized))

    if not normalized:
        return {
            "channel": channel_key,
            "status": "ok",
            "messages_collected": 0,
            "messages_added": 0,
            "messages_updated": 0,
        }

    # Attempt atomic write
    try:
        result = append_messages(base_path, channel_id, normalized)  # raw_dir adds "channel_" prefix
        added = result["added"]
        updated = result["updated"]
    except Exception as e:
        log.error("Storage write failed for '%s': %s", channel_name, str(e))
        err_state = build_error_state(
            channel_key, channel_name, channel_username, str(e), existing_state
        )
        save_state(base_path, channel_key, err_state)
        return {
            "channel": channel_key,
            "status": "error",
            "error": str(e),
            "messages_collected": 0,
            "messages_added": 0,
            "messages_updated": 0,
        }

    # Only update state after confirmed write
    top_msg = normalized[-1]
    previous_last = existing_state.get("last_success_message_id", 0) if existing_state else 0
    new_last = max(previous_last, top_msg["message_id"])
    new_date = top_msg["message_date"] if new_last == top_msg["message_id"] else (existing_state.get("last_success_message_date") if existing_state else top_msg["message_date"])
    new_state = build_success_state(
        channel_id=channel_key,
        channel_title=channel_name,
        channel_username=channel_username,
        last_message_id=new_last,
        last_message_date=new_date,
        run_id=run_id,
        existing_state=existing_state,
    )
    save_state(base_path, channel_key, new_state)
    log.info(
        "Channel '%s': added %d messages, updated %d messages, last_message_id=%d",
        channel_name,
        added,
        updated,
        new_last,
    )

    return {
        "channel": channel_key,
        "status": "ok",
        "messages_collected": added + updated,
        "messages_added": added,
        "messages_updated": updated,
        "last_message_id": new_last,
    }


async def run_collector(config_path: str):
    config = load_app_config(config_path)
    log = setup_logger(config.logging.level, config.logging.file_path)

    run_id = generate_run_id()
    set_run_context(run_id)
    started_at = datetime.now(timezone.utc).isoformat()

    log.info("=== Collector run started: %s ===", run_id)

    session_name = config.telegram.session_name
    if not os.path.isabs(session_name):
        session_name = os.path.join(os.getcwd(), session_name)

    client = TelegramClient(
        session_name,
        config.telegram.api_id,
        config.telegram.api_hash,
    )

    channel_results = []

    async with client:
        # Automatically discover all channels for the current user
        dialogs = await client.get_dialogs()
        exclude_values = {
            str(item).strip().lower()
            for item in config.collector.exclude_channels
            if item is not None
        }

        channels = []
        skipped = 0
        for dialog in dialogs:
            if not dialog.is_channel:
                continue
            if _is_channel_excluded(dialog, exclude_values):
                skipped += 1
                channel_id = str(dialog.id)
                channel_username = getattr(dialog.entity, "username", None)
                channel_title = getattr(dialog, "title", None)
                log.info(
                    "Skipping excluded channel: id=%s username=%s title=%s",
                    channel_id,
                    channel_username,
                    channel_title,
                )
                continue
            channels.append(dialog)

        log.info(
            "Discovered channels to process: %d, skipped excluded: %d",
            len(channels),
            skipped,
        )

        for dialog in channels:
            result = await process_channel(client, dialog, config, run_id)
            channel_results.append(result)

    finished_at = datetime.now(timezone.utc).isoformat()
    run_payload = build_run_log(run_id, started_at, finished_at, channel_results)
    write_run_log(config.storage.base_path, run_id, run_payload)

    set_run_context(run_id)
    log.info(
        "=== Run %s finished. Channels: %d, Errors: %d, Messages: %d ===",
        run_id,
        run_payload["channels_processed"],
        run_payload["channels_errored"],
        run_payload["total_messages_collected"],
    )


def main():
    workspace_root = set_workspace_root_from_env("ART_GRAM_HOME")
    config_path = os.path.join(workspace_root, "config/app.yaml")
    asyncio.run(run_collector(config_path))


if __name__ == "__main__":
    main()
