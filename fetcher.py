"""
fetcher.py - Telegram message fetching via Telethon with retry and pagination.
"""

import asyncio
from typing import List

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import Message

from logger import get_logger


async def fetch_messages(
    client: TelegramClient,
    channel_entity,           # Telethon entity passed to iter_messages
    channel_name: str,        # human-readable name for logging only
    min_id: int,
    batch_size: int,
    retry_count: int,
    retry_backoff: int,
    limit: int = None,  # None = fetch all new messages; set for new channels
) -> List[Message]:
    """
    Fetch messages from a channel with message_id > min_id.
    Uses iter_messages for correct pagination with a guaranteed stop condition.
    'limit' caps the number of messages fetched (use for new channels).
    Returns messages in ascending order by message_id.
    """
    log = get_logger()
    all_messages = []

    for attempt in range(retry_count + 1):
        try:
            all_messages = []
            async for msg in client.iter_messages(
                channel_entity,
                limit=limit,         # None = all new; int = cap for new channels
                min_id=min_id,       # stop when id <= min_id is reached
                reverse=False,       # newest-first (default); we sort later
                wait_time=0,         # no extra sleep between pages
            ):
                if isinstance(msg, Message):
                    all_messages.append(msg)
            break  # success — exit retry loop

        except FloodWaitError as e:
            wait = e.seconds + 5
            log.warning(
                "FloodWaitError: waiting %d seconds before retry (attempt %d/%d)",
                wait,
                attempt + 1,
                retry_count,
            )
            await asyncio.sleep(wait)

        except (ChannelPrivateError, UsernameNotOccupiedError) as e:
            raise RuntimeError(f"Channel access error: {e}") from e

        except Exception as e:
            if attempt == retry_count:
                raise
            log.warning(
                "Fetch attempt %d/%d failed: %s. Retrying in %ds.",
                attempt + 1,
                retry_count,
                str(e),
                retry_backoff,
            )
            await asyncio.sleep(retry_backoff * (attempt + 1))
    else:
        raise RuntimeError(
            f"All {retry_count + 1} fetch attempts failed for {channel_name}"
        )

    # Sort ascending by message_id (newest-first from API → reverse to oldest-first)
    all_messages.sort(key=lambda m: m.id)
    log.info("Total messages fetched from '%s': %d", channel_name, len(all_messages))
    return all_messages
