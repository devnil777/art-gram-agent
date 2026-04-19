# Data Dictionary

## Raw Message Record (raw/channel_*/YYYY-MM-DD.jsonl)

| Field | Type | Nullable | Source | Description |
|---|---|---|---|---|
| `channel_id` | string | no | channel config | Channel username used as the system-wide key |
| `channel_username` | string | no | channel config | Same as `channel_id` in current version |
| `message_id` | integer | no | Telethon `msg.id` | Telegram-assigned message ID. Unique within channel. Monotonically increasing. |
| `message_date` | string (ISO 8601) | no | Telethon `msg.date` | UTC datetime when the message was originally posted |
| `text` | string | no | Telethon `msg.text` | Plaintext content of message. Empty string if media-only. |
| `raw` | object | yes | `msg.to_dict()` | Full Telethon message dict. Bytes values are hex-encoded. Null on serialization error. |
| `is_forwarded` | boolean | no | Telethon `msg.forward` | True if this message is a forward from another source |
| `reply_to_message_id` | integer | yes | Telethon `msg.reply_to` | ID of the message this is a reply to, if any |
| `edit_date` | string (ISO 8601) | yes | Telethon `msg.edit_date` | UTC datetime of last edit, if the message was edited |
| `ingested_at` | string (ISO 8601) | no | system clock | UTC datetime when the collector wrote this record |
| `run_id` | string | no | run context | Identifier of the run that produced this record. Format: `YYYYMMDDTHHMMSSz` |

---

## Channel State File (state/channel_<id>.json)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `channel_id` | string | no | Channel identifier (username) |
| `last_success_message_id` | integer | yes | Highest `message_id` successfully stored. Null if never succeeded. |
| `last_success_message_date` | string | yes | `message_date` of the last stored message |
| `last_success_run_id` | string | yes | `run_id` of the last successful run for this channel |
| `last_success_at` | string (ISO 8601) | yes | Wall-clock time of last successful write |
| `last_attempt_at` | string (ISO 8601) | no | Wall-clock time of most recent state save (success or error) |
| `error_count` | integer | no | Cumulative count of runs that ended in error for this channel |
| `status` | string | no | `"ok"` or `"error"` |
| `last_error` | string | yes | Error message from last failed attempt. Present only on error. |
| `_version` | integer | no | State file schema version (currently `1`) |

---

## Run Log File (runs/run_<timestamp>.json)

| Field | Type | Description |
|---|---|---|
| `run_id` | string | Unique run identifier |
| `started_at` | string (ISO 8601) | UTC start time of the run |
| `finished_at` | string (ISO 8601) | UTC end time of the run |
| `channels_processed` | integer | Total number of channels attempted |
| `channels_errored` | integer | Number of channels that resulted in error |
| `total_messages_collected` | integer | Sum of messages stored across all channels |
| `channel_results` | array | Per-channel outcome objects (see below) |

### channel_results entry

| Field | Type | Description |
|---|---|---|
| `channel` | string | Channel identifier |
| `status` | string | `"ok"` or `"error"` |
| `messages_collected` | integer | Number of messages stored in this run |
| `last_message_id` | integer | Highest stored message_id (only on success) |
| `error` | string | Error message (only on error) |

---

## Identifiers

| Identifier | Format | Example | Notes |
|---|---|---|---|
| `run_id` | `YYYYMMDDTHHMMSSz` | `20240601T080001Z` | UTC, sortable, filesystem-safe |
| `channel_id` | Telegram username | `example_channel` | No @ prefix |
| `message_id` | integer | `5821` | Telegram-assigned, channel-scoped |
