# Raw Storage Format

## File Location

```
raw/channel_<username>/YYYY-MM-DD.jsonl
```

- One directory per channel, named by username.
- One file per calendar day (UTC date of `message_date`).
- Files are append-only; existing content is never modified.

## File Format

JSONL (JSON Lines): one JSON object per line, terminated by newline `\n`.
All files are UTF-8 encoded.
All string values use ASCII-safe encoding (`ensure_ascii=True`).

## Record Fields

| Field | Type | Nullable | Description |
|---|---|---|---|
| `channel_id` | string | no | Channel username used as system key |
| `channel_username` | string | no | Telegram @-less username (same as channel_id in current version) |
| `message_id` | integer | no | Telegram message ID, unique within channel |
| `message_date` | string (ISO 8601) | no | UTC timestamp of original message post |
| `text` | string | no | Message text content. Empty string if no text. |
| `raw` | object | yes | Full Telethon Message serialized via `.to_dict()`. Bytes fields hex-encoded. `null` on serialization failure. |
| `is_forwarded` | boolean | no | True if message is a forward from another channel/user |
| `reply_to_message_id` | integer | yes | ID of the message being replied to, if any |
| `edit_date` | string (ISO 8601) | yes | UTC timestamp of last edit, if message was edited |
| `ingested_at` | string (ISO 8601) | no | UTC timestamp when collector wrote this record |
| `run_id` | string | no | ID of the run that produced this record |

## Example Record

```json
{
  "channel_id": "example_channel",
  "channel_username": "example_channel",
  "message_id": 5821,
  "message_date": "2024-06-01T06:30:00+00:00",
  "text": "Today market opened higher across all indices.",
  "raw": {"_": "Message", "id": 5821, "peer_id": {"_": "PeerChannel", "channel_id": 1234567890}, "date": "2024-06-01T06:30:00+00:00", "message": "Today market opened higher across all indices.", "out": false, "mentioned": false, "media_unread": false, "silent": false, "post": true, "from_scheduled": false, "legacy": false, "edit_hide": false, "pinned": false, "noforwards": false, "from_id": null, "fwd_from": null, "via_bot_id": null, "reply_to": null, "media": null, "reply_markup": null, "entities": [], "views": 1423, "forwards": 12, "replies": null, "edit_date": null, "post_author": null, "grouped_id": null, "reactions": null, "restriction_reason": [], "ttl_period": null},
  "is_forwarded": false,
  "reply_to_message_id": null,
  "edit_date": null,
  "ingested_at": "2024-06-01T08:00:04.123456+00:00",
  "run_id": "20240601T080001Z"
}
```

## Deduplication

Before writing, the collector loads all existing `message_id` values for the channel.
Messages already present are skipped. This prevents duplicates even when overlap
or retry causes the same message range to be fetched again.

## Atomic Write Protocol

1. Read existing file content (if file exists).
2. Prepare new lines for messages grouped by date.
3. Write all content (existing + new) to a `.tmp` file via `tempfile.mkstemp`.
4. Call `fsync` on the temp file descriptor.
5. Call `os.replace(tmp, target)` — atomic on POSIX systems.
6. On any failure, delete the temp file; original file is untouched.
