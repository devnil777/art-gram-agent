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


def append_messages(base_path: str, channel_id: str, messages: List[dict]):
    """
    Atomically append a batch of normalized messages to the daily JSONL file.

    Strategy:
    1. Read existing content (if file exists).
    2. Write existing + new content to a temp file with fsync.
    3. Rename temp file over target (atomic on POSIX).
    """
    if not messages:
        return

    # Group by date
    by_date: dict = {}
    for m in messages:
        date_str = (m["message_date"] or "unknown")[:10]
        by_date.setdefault(date_str, []).append(m)

    for date_str, day_msgs in by_date.items():
        target = raw_file_path(base_path, channel_id, date_str)
        dir_path = os.path.dirname(target)
        os.makedirs(dir_path, exist_ok=True)

        # Read existing content
        existing_lines = []
        if os.path.exists(target):
            with open(target, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()

        new_lines = [json.dumps(m, ensure_ascii=True) + "\n" for m in day_msgs]

        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(existing_lines)
                f.writelines(new_lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise


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
