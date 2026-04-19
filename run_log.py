"""
run_log.py - Per-run execution journal stored in runs/run_<timestamp>.json
"""

import json
import os
import tempfile
from datetime import datetime, timezone


def runs_path(base_path: str, run_id: str) -> str:
    return os.path.join(base_path, "runs", f"run_{run_id}.json")


def write_run_log(base_path: str, run_id: str, payload: dict):
    path = runs_path(base_path, run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def build_run_log(
    run_id: str,
    started_at: str,
    finished_at: str,
    channel_results: list,
) -> dict:
    total_collected = sum(r.get("messages_collected", 0) for r in channel_results)
    errors = sum(1 for r in channel_results if r.get("status") == "error")
    return {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "channels_processed": len(channel_results),
        "channels_errored": errors,
        "total_messages_collected": total_collected,
        "channel_results": channel_results,
    }
