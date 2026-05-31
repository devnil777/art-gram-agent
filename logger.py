"""
logger.py - Application logging setup.

All log messages must be in English, no Unicode symbols.
Format: timestamp | level | module | run_id | channel_id | message
"""

import logging
import os
from typing import Optional


class ContextFilter(logging.Filter):
    """Injects run_id and channel_id into log records."""

    def __init__(self):
        super().__init__()
        self.run_id = "none"
        self.channel_id = "none"

    def filter(self, record):
        record.run_id = self.run_id
        record.channel_id = self.channel_id
        return True


_context_filter = ContextFilter()


def setup_logger(level: str, file_path: str) -> logging.Logger:
    import datetime
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    base, ext = os.path.splitext(file_path)
    file_path = f"{base}_{today_str}{ext}"

    log_dir = os.path.dirname(file_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    fmt = "%(asctime)s | %(levelname)-8s | %(module)-20s | run=%(run_id)s | ch=%(channel_id)s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S")

    logger = logging.getLogger("tg_collector")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addFilter(_context_filter)

    # File handler
    fh = logging.FileHandler(file_path, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("tg_collector")


def set_run_context(run_id: str, channel_id: str = "none"):
    _context_filter.run_id = run_id
    _context_filter.channel_id = channel_id
