"""
state.py - Channel state (checkpoint) management.

State file is written only after confirmed raw data write.
This guarantees state never advances ahead of stored data.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional


STATE_VERSION = 1


def _state_path(base_path: str, channel_id: str) -> str:
    return os.path.join(base_path, "state", f"channel_{channel_id}.json")


def load_state(base_path: str, channel_id: str) -> Optional[dict]:
    path = _state_path(base_path, channel_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(base_path: str, channel_id: str, state: dict):
    """Atomically write state file using temp file + rename."""
    path = _state_path(base_path, channel_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    state["_version"] = STATE_VERSION
    state["last_attempt_at"] = datetime.now(timezone.utc).isoformat()

    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def build_success_state(
    channel_id: str,
    channel_title: str,
    channel_username: str,
    last_message_id: int,
    last_message_date: str,
    run_id: str,
    existing_state: Optional[dict],
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    error_count = existing_state.get("error_count", 0) if existing_state else 0
    return {
        "channel_id": channel_id,
        "channel_title": channel_title,
        "channel_username": channel_username,
        "last_success_message_id": last_message_id,
        "last_success_message_date": last_message_date,
        "last_success_run_id": run_id,
        "last_success_at": now,
        "error_count": error_count,
        "status": "ok",
    }


def build_error_state(
    channel_id: str,
    channel_title: str,
    channel_username: str,
    error_msg: str,
    existing_state: Optional[dict],
) -> dict:
    base = existing_state.copy() if existing_state else {}
    base["channel_id"] = channel_id
    base["channel_title"] = channel_title
    base["channel_username"] = channel_username
    base["status"] = "error"
    base["last_error"] = error_msg
    base["error_count"] = base.get("error_count", 0) + 1
    return base
