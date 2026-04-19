"""
news_sender.py - Send a report-based news summary to a Telegram channel.

Usage:
    python news_sender.py --target <channel_username_or_id> [--config config/app.yaml] \
        [--processor-config config/processor_config.yaml] [--base-path .]

The script loads processed events from storage, builds a text summary of the
most recent events, and sends that summary as a Telegram message to the
specified channel.

The collector can exclude this target channel from analysis using
collector.exclude_channels in app.yaml.
"""

import argparse
import logging
import asyncio
from typing import Optional

from telethon import TelegramClient

from config_loader import load_app_config
from processor_config_loader import load_processor_config
from report_generator import generate_report_text
from utils import set_workspace_root_from_env


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


async def send_news_summary(
    app_config_path: str,
    processor_config_path: str,
    base_path: str,
    target: str,
    max_events: int,
    report_days: Optional[int] = None,
) -> None:
    logger = logging.getLogger("news_sender")
    app_config = load_app_config(app_config_path)
    processor_config = load_processor_config(processor_config_path)

    if report_days is not None:
        processor_config.report.report_days = report_days

    summary_text = generate_report_text(
        processor_config.report,
        base_path,
        load_from_storage=True,
        max_events=max_events,
    )

    if not summary_text.strip():
        logger.warning("No events found to send.")
        return

    session_name = app_config.telegram.session_name
    if not os.path.isabs(session_name):
        session_name = os.path.join(os.getcwd(), session_name)

    client = TelegramClient(
        session_name,
        app_config.telegram.api_id,
        app_config.telegram.api_hash,
    )

    entity = parse_target_entity(target)
    logger.info("Sending news summary to %s", target)

    async with client:
        await client.send_message(entity, summary_text)

    logger.info("News summary sent successfully.")


def main() -> int:
    workspace_root = set_workspace_root_from_env("ART_GRAM_HOME")

    parser = argparse.ArgumentParser(
        description="Send a Telegram message with a summary of recently processed news events."
    )
    parser.add_argument(
        "--config",
        default="config/app.yaml",
        help="Path to app config file (default: config/app.yaml)",
    )
    parser.add_argument(
        "--processor-config",
        default="config/processor_config.yaml",
        help="Path to processor config file (default: config/processor_config.yaml)",
    )
    parser.add_argument(
        "--base-path",
        default=workspace_root,
        help="Project base path for storage and report loading (default: ART_GRAM_HOME or current directory)",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Telegram channel username or numeric ID to send the news summary to",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=20,
        help="Maximum number of events to include in the message (default: 20)",
    )
    parser.add_argument(
        "--report-days",
        type=int,
        default=None,
        help="Override report days window for this news summary",
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
                app_config_path=args.config,
                processor_config_path=args.processor_config,
                base_path=args.base_path,
                target=args.target,
                max_events=args.max_events,
                report_days=args.report_days,
            )
        )
        return 0
    except Exception as exc:
        logging.getLogger("news_sender").error("Failed to send news summary: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
