"""
config.py - Configuration loading and validation.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TelegramConfig:
    api_id: int
    api_hash: str
    session_name: str


@dataclass
class CollectorConfig:
    cron_interval: str
    batch_size: int
    overlap_messages: int
    initial_search_depth: int
    retry_count: int
    retry_backoff_seconds: int
    exclude_channels: List[str] = field(default_factory=list)


@dataclass
class StorageConfig:
    base_path: str
    raw_format: str


@dataclass
class LoggingConfig:
    level: str
    file_path: str


@dataclass
class AppConfig:
    telegram: TelegramConfig
    collector: CollectorConfig
    storage: StorageConfig
    logging: LoggingConfig


@dataclass
class ChannelEntry:
    username: str
    enabled: bool
    channel_id: Optional[int] = None
    title: Optional[str] = None
    notes: Optional[str] = None


def load_app_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    tg = raw["telegram"]
    col = raw["collector"]
    sto = raw["storage"]
    log = raw["logging"]

    return AppConfig(
        telegram=TelegramConfig(
            api_id=int(tg["api_id"]),
            api_hash=str(tg["api_hash"]),
            session_name=str(tg["session_name"]),
        ),
        collector=CollectorConfig(
            cron_interval=str(col["cron_interval"]),
            batch_size=int(col["batch_size"]),
            overlap_messages=int(col["overlap_messages"]),
            initial_search_depth=int(col["initial_search_depth"]),
            retry_count=int(col["retry_count"]),
            retry_backoff_seconds=int(col["retry_backoff_seconds"]),
            exclude_channels=[str(item).strip() for item in col.get("exclude_channels", []) if item is not None],
        ),
        storage=StorageConfig(
            base_path=str(sto["base_path"]),
            raw_format=str(sto["raw_format"]),
        ),
        logging=LoggingConfig(
            level=str(log["level"]),
            file_path=str(log["file_path"]),
        ),
    )


def load_channels(path: str) -> List[ChannelEntry]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    entries = []
    for ch in raw.get("channels", []):
        entries.append(
            ChannelEntry(
                channel_id=ch.get("channel_id"),
                username=str(ch["username"]),
                enabled=bool(ch.get("enabled", True)),
                title=ch.get("title"),
                notes=ch.get("notes"),
            )
        )
    return entries
