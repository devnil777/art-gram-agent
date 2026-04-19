"""
news_sender.py - Send a report-based news summary to a Telegram channel.

Usage:
    python news_sender.py --target <channel_username_or_id> [--send-all] [--report-days N]

The script loads processed events from storage, filters out already-sent events
by default (use --send-all to include them), builds a text summary of events from the last N days,
and sends that summary as Telegram messages to the specified channel.

After successful sending, it records which events were sent to prevent duplicate
publishing in subsequent runs.

The collector can exclude this target channel from analysis using
collector.exclude_channels in app.yaml.
"""

import argparse
import logging
import asyncio
import os
from typing import Optional

from telethon import TelegramClient

from config_loader import load_app_config
from processor_config_loader import load_processor_config
from utils import set_workspace_root_from_env
import storage


def setup_logger(level: str = "INFO") -> logging.Logger:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger = logging.getLogger("news_sender")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def parse_target_entity(target: str):
    value = target.strip()
    if not value:
        raise ValueError("Target channel must be provided")

    if value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            pass
    return value


PAGE_SIZE_BYTES = 4096

async def send_news_summary(
    app_config_path: str,
    processor_config_path: str,
    base_path: str,
    target: str,
    report_days: Optional[int] = None,
    skip_already_sent: bool = False,
) -> None:
    """
    Send a news summary to a Telegram channel and record sent events.
    
    Loads processed events, filters by date and sent status, builds report pages,
    sends them to Telegram, and records which events were sent.
    
    Args:
        app_config_path: Path to app configuration
        processor_config_path: Path to processor configuration
        base_path: Project base path
        target: Target channel username or ID
        report_days: Override report_days from config
        skip_already_sent: If True, filter out events already sent to this target
    """
    from report_generator import (
        load_processed_events_from_storage,
        _is_recent_message,
        _sort_events,
        _build_summary_text,
    )
    
    logger = logging.getLogger("news_sender")
    app_config = load_app_config(app_config_path)
    processor_config = load_processor_config(processor_config_path)

    # Load all processed events
    successful, _ = load_processed_events_from_storage(base_path)
    all_events = []
    for result in successful:
        if result.success and result.events:
            all_events.extend(result.events)

    # Determine report days window
    days = report_days if report_days is not None else processor_config.report.report_days
    
    # Filter by date (last N days)
    recent_events = [
        e for e in all_events if _is_recent_message(e.message_date, days=days)
    ]

    # Filter out already sent events if requested
    if skip_already_sent:
        sent_map = storage.load_sent_events(base_path, target)
        sent_ids = sent_map.get(target, set())
        recent_events = [
            e for e in recent_events
            if f"{e.channel_id}:{e.message_id}" not in sent_ids
        ]

    if not recent_events:
        logger.warning(
            "No unsent events found%s.",
            " (or all recent events already sent)" if skip_already_sent else ""
        )
        return

    # Build text pages
    sorted_events = _sort_events(recent_events)
    pages = _build_summary_text(
        processor_config.report,
        sorted_events,
        page_size_bytes=PAGE_SIZE_BYTES,
    )

    if not pages or not any(page.strip() for page in pages):
        logger.warning("Failed to generate report pages.")
        return

    # Send pages to Telegram
    session_name = app_config.telegram.session_name
    if not os.path.isabs(session_name):
        session_name = os.path.join(os.getcwd(), session_name)

    client = TelegramClient(
        session_name,
        app_config.telegram.api_id,
        app_config.telegram.api_hash,
    )

    entity = parse_target_entity(target)
    logger.info(
        "Sending news summary to %s (%d page%s)",
        target,
        len(pages),
        "s" if len(pages) != 1 else "",
    )

    async with client:
        for page in pages:
            await client.send_message(entity, page, link_preview=False, parse_mode="md")

    # Record sent events
    sent_event_ids = [
        {
            "channel_id": e.channel_id,
            "message_id": e.message_id,
        }
        for e in recent_events
    ]
    
    if sent_event_ids:
        storage.mark_events_as_sent(base_path, target, sent_event_ids)
        logger.info("Recorded %d events as sent to %s", len(sent_event_ids), target)

    logger.info("News summary sent successfully.")


def main() -> int:
    workspace_root = set_workspace_root_from_env("ART_GRAM_HOME")

    parser = argparse.ArgumentParser(
        description="Send a Telegram message with a summary of recently processed news events."
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Telegram channel username or numeric ID to send the news summary to",
    )
    parser.add_argument(
        "--report-days",
        type=int,
        default=None,
        help="Override report days window for this news summary",
    )
    parser.add_argument(
        "--send-all",
        action="store_true",
        default=False,
        help="Send all events, including already sent to this target (default: False, skip sent)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    setup_logger(args.log_level)

    try:
        asyncio.run(
            send_news_summary(
                app_config_path="config/app.yaml",
                processor_config_path="config/processor_config.yaml",
                base_path=workspace_root,
                target=args.target,
                report_days=args.report_days,
                skip_already_sent=not args.send_all,
            )
        )
        return 0
    except Exception as exc:
        logging.getLogger("news_sender").error("Failed to send news summary: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
