"""
storage.py - Raw message JSONL storage with atomic write guarantees.

Files are appended per-channel per-day: raw/channel_<id>/YYYY-MM-DD.jsonl
Atomic append uses a temp file + fsync + rename strategy to avoid
partial writes corrupting existing data.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import List, Dict


def raw_dir(base_path: str, channel_id: str) -> str:
    return os.path.join(base_path, "raw", f"channel_{channel_id}")


def raw_file_path(base_path: str, channel_id: str, date_str: str) -> str:
    return os.path.join(raw_dir(base_path, channel_id), f"{date_str}.jsonl")


def normalize_message(msg, channel_id: str, channel_username: str, run_id: str) -> dict:
    """Convert a Telethon Message object to a normalized dict."""

    fwd = msg.forward
    is_forwarded = fwd is not None

    reply_to_id = None
    if msg.reply_to and hasattr(msg.reply_to, "reply_to_msg_id"):
        reply_to_id = msg.reply_to.reply_to_msg_id

    msg_date = msg.date.isoformat() if msg.date else None
    edit_date = msg.edit_date.isoformat() if msg.edit_date else None

    # Serialize raw Telethon object safely
    try:
        raw_obj = msg.to_dict()
        # Convert any non-serializable types to strings
        raw_obj = _make_serializable(raw_obj)
    except Exception:
        raw_obj = None

    return {
        "channel_id": channel_id,
        "channel_username": channel_username,
        "message_id": msg.id,
        "message_date": msg_date,
        "text": msg.text or "",
        "raw": raw_obj,
        "is_forwarded": is_forwarded,
        "reply_to_message_id": reply_to_id,
        "edit_date": edit_date,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
    }


def _make_serializable(obj):
    """Recursively convert non-JSON-serializable types."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, bytes):
        return obj.hex()
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def append_messages(base_path: str, channel_id: str, messages: List[dict]) -> dict:
    """
    Atomically update/add normalized messages to the daily JSONL file.
    Updates existing messages by message_id, adds new ones.

    Returns dict with 'added' and 'updated' counts.

    Strategy:
    1. Read existing content and build dict by message_id.
    2. Update/add new messages, count added/updated.
    3. Write merged content to temp file with fsync.
    4. Rename temp file over target (atomic on POSIX).
    """
    if not messages:
        return {"added": 0, "updated": 0}

    # Group by date
    by_date: dict = {}
    for m in messages:
        date_str = (m["message_date"] or "unknown")[:10]
        by_date.setdefault(date_str, []).append(m)

    added_total = 0
    updated_total = 0

    for date_str, day_msgs in by_date.items():
        target = raw_file_path(base_path, channel_id, date_str)
        dir_path = os.path.dirname(target)
        os.makedirs(dir_path, exist_ok=True)

        # Read existing content and build dict
        existing_dict = {}
        if os.path.exists(target):
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        existing_dict[obj["message_id"]] = obj
                    except json.JSONDecodeError:
                        pass

        # Update/add new messages, count
        added = 0
        updated = 0
        for m in day_msgs:
            if m["message_id"] not in existing_dict:
                added += 1
            else:
                updated += 1
            existing_dict[m["message_id"]] = m

        added_total += added
        updated_total += updated

        # Prepare lines, sorted by message_id for consistency
        merged_lines = [json.dumps(obj, ensure_ascii=True) + "\n" for obj in sorted(existing_dict.values(), key=lambda x: x["message_id"])]

        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(merged_lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    return {"added": added_total, "updated": updated_total}


def load_existing_ids(base_path: str, channel_id: str) -> set:
    """Return set of all message_ids already stored for a channel (for dedup)."""
    ids = set()
    dir_path = raw_dir(base_path, channel_id)
    if not os.path.isdir(dir_path):
        return ids
    for fname in os.listdir(dir_path):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(dir_path, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ids.add(obj["message_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    return ids


# ============================================================================
# Processed Events Storage (persistent storage of extraction results)
# ============================================================================

def processed_dir(base_path: str, channel_id: str) -> str:
    """Get the directory path for processed events for a channel."""
    return os.path.join(base_path, "processed", f"channel_{channel_id}")


def processed_file_path(base_path: str, channel_id: str, date_str: str) -> str:
    """Get the JSONL file path for processed events for a channel and date."""
    return os.path.join(processed_dir(base_path, channel_id), f"{date_str}.jsonl")


def save_processing_result(
    result_dict: dict,
    base_path: str,
) -> None:
    """
    Atomically save a single processing result to the appropriate JSONL file.

    Args:
        result_dict: Dict containing the processing result with fields:
                     - channel_id
                     - message_date
                     - ... (all other ProcessingResult fields)
        base_path: Project base path

    Strategy (mirrors append_messages):
    1. Read existing content of the target file.
    2. Append new result to a temp file with fsync.
    3. Atomically rename temp file over target.
    """
    channel_id = result_dict.get("channel_id")
    message_date = result_dict.get("message_date")

    if not channel_id or not message_date:
        raise ValueError("result_dict must have channel_id and message_date")

    # Extract date from ISO timestamp
    date_str = message_date[:10]

    target = processed_file_path(base_path, channel_id, date_str)
    dir_path = os.path.dirname(target)
    os.makedirs(dir_path, exist_ok=True)

    # Read existing content
    existing_lines = []
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    new_line = json.dumps(result_dict, ensure_ascii=False, indent=None) + "\n"

    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(existing_lines)
            f.write(new_line)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_processing_results(
    base_path: str,
    channel_id: str = None,
    date_str: str = None,
) -> List[dict]:
    """
    Load processed event records from storage.

    Args:
        base_path: Project base path
        channel_id: If provided, load only results for this channel
        date_str: If provided, load only results for this date (format: YYYY-MM-DD)

    Returns:
        List of dicts (parsed JSON lines from JSONL files)
    """
    results = []
    processed_root = os.path.join(base_path, "processed")

    if not os.path.isdir(processed_root):
        return results

    # If channel_id is specified, only scan that channel
    if channel_id:
        channels_to_scan = [f"channel_{channel_id}"]
    else:
        channels_to_scan = [
            d for d in os.listdir(processed_root)
            if os.path.isdir(os.path.join(processed_root, d)) and d.startswith("channel_")
        ]

    for channel_dir_name in sorted(channels_to_scan):
        channel_path = os.path.join(processed_root, channel_dir_name)
        if not os.path.isdir(channel_path):
            continue

        # If date_str is specified, only load that file
        if date_str:
            files_to_load = [f"{date_str}.jsonl"]
        else:
            files_to_load = [
                f for f in os.listdir(channel_path)
                if f.endswith(".jsonl")
            ]

        for filename in sorted(files_to_load):
            filepath = os.path.join(channel_path, filename)
            if not os.path.exists(filepath):
                continue

            with open(filepath, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        results.append(obj)
                    except json.JSONDecodeError as e:
                        # Log but don't fail, similar to raw storage loading
                        import logging
                        log = logging.getLogger("tg_collector")
                        log.warning(
                            "Skipping malformed JSON in %s line %d: %s",
                            filepath,
                            line_num,
                            str(e),
                        )

    return results


# ============================================================================
# Sent Events Tracking (persistent storage of sent news summaries)
# ============================================================================

def sent_dir(base_path: str) -> str:
    """Get the directory path for sent events tracking."""
    return os.path.join(base_path, "sent")


def sent_file_path(base_path: str, target_identifier: str) -> str:
    """Get the JSONL file path for tracking sent events to a target."""
    # Sanitize target identifier for use as filename
    safe_target = target_identifier.replace("/", "_").replace(":", "_")
    return os.path.join(sent_dir(base_path), f"{safe_target}.jsonl")


def mark_events_as_sent(
    base_path: str,
    target_identifier: str,
    event_ids: List[Dict[str, any]],
) -> None:
    """
    Record that specific events were sent to a target channel.

    Args:
        base_path: Project base path
        target_identifier: Target channel username or ID
        event_ids: List of dicts with 'channel_id' and 'message_id' identifying events

    Each record has format:
    {
        "target": "<identifier>",
        "channel_id": "<source_channel_id>",
        "message_id": <msg_id>,
        "sent_at": "<ISO timestamp>"
    }
    """
    if not event_ids:
        return

    target_path = sent_file_path(base_path, target_identifier)
    dir_path = os.path.dirname(target_path)
    os.makedirs(dir_path, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    
    # Read existing content
    existing_lines = []
    if os.path.exists(target_path):
        with open(target_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    # Create new records
    new_lines = []
    for event in event_ids:
        record = {
            "target": target_identifier,
            "channel_id": event.get("channel_id"),
            "message_id": event.get("message_id"),
            "sent_at": now,
        }
        new_lines.append(json.dumps(record, ensure_ascii=False, indent=None) + "\n")

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(existing_lines)
            f.writelines(new_lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_sent_events(
    base_path: str,
    target_identifier: str = None,
) -> Dict[str, set]:
    """
    Load sent events tracking information.

    Args:
        base_path: Project base path
        target_identifier: If specified, load only events sent to this target

    Returns:
        Dict mapping target -> set of "channel_id:message_id" strings
    """
    sent_map = {}
    sent_root = sent_dir(base_path)

    if not os.path.isdir(sent_root):
        return sent_map

    # Determine which files to load
    if target_identifier:
        files_to_load = [sent_file_path(base_path, target_identifier)]
    else:
        files_to_load = [
            os.path.join(sent_root, f)
            for f in os.listdir(sent_root)
            if f.endswith(".jsonl")
        ]

    for filepath in files_to_load:
        if not os.path.exists(filepath):
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    target = obj.get("target")
                    channel_id = obj.get("channel_id")
                    message_id = obj.get("message_id")
                    
                    if target and channel_id and message_id:
                        if target not in sent_map:
                            sent_map[target] = set()
                        sent_map[target].add(f"{channel_id}:{message_id}")
                except json.JSONDecodeError:
                    pass

    return sent_map


def get_processed_message_ids(
    base_path: str,
    channel_id: str,
    date_str: str = None,
) -> set:
    """
    Get set of message_ids already processed for a channel (optionally filtered by date).

    Args:
        base_path: Project base path
        channel_id: Channel ID to query
        date_str: Optional date filter (format: YYYY-MM-DD)

    Returns:
        Set of processed message_ids
    """
    ids = set()
    dir_path = processed_dir(base_path, channel_id)

    if not os.path.isdir(dir_path):
        return ids

    files_to_scan = []
    if date_str:
        # Load only specific date
        files_to_scan = [f"{date_str}.jsonl"]
    else:
        # Load all files
        files_to_scan = [
            f for f in os.listdir(dir_path)
            if f.endswith(".jsonl")
        ]

    for fname in files_to_scan:
        fpath = os.path.join(dir_path, fname)
        if not os.path.exists(fpath):
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    msg_id = obj.get("message_id")
                    if msg_id is not None:
                        ids.add(msg_id)
                except (json.JSONDecodeError, KeyError):
                    pass

    return ids


def load_processed_ids_by_channel(base_path: str) -> dict:
    """
    Load all processed message_ids grouped by channel_id.

    Returns:
        Dict mapping channel_id -> set of processed message_ids
    """
    result = {}
    processed_root = os.path.join(base_path, "processed")

    if not os.path.isdir(processed_root):
        return result

    for channel_dir_name in os.listdir(processed_root):
        channel_path = os.path.join(processed_root, channel_dir_name)
        if not os.path.isdir(channel_path):
            continue

        # Extract channel_id from "channel_{id}" format
        if not channel_dir_name.startswith("channel_"):
            continue
        channel_id = channel_dir_name[len("channel_"):]

        ids = set()
        for fname in os.listdir(channel_path):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(channel_path, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        msg_id = obj.get("message_id")
                        if msg_id is not None:
                            ids.add(msg_id)
                    except (json.JSONDecodeError, KeyError):
                        pass

        if ids:
            result[channel_id] = ids

    return result
