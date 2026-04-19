# Configuration Reference

All configuration is loaded from YAML files at startup.
No runtime parameters are hardcoded.

## app.yaml Parameters

### telegram section

| Parameter | Type | Required | Description |
|---|---|---|---|
| `telegram.api_id` | integer | yes | Telegram application API ID from my.telegram.org |
| `telegram.api_hash` | string | yes | Telegram application API hash from my.telegram.org |
| `telegram.session_name` | string | yes | Telethon session file name (no extension). Stored in working directory. |

### collector section

| Parameter | Type | Default | Description |
|---|---|---|---|
| `collector.cron_interval` | string | `"0 */4 * * *"` | Informational only. Actual scheduling is external (cron). |
| `collector.batch_size` | integer | `100` | Number of messages to fetch per Telegram API call. Max recommended: 100. |
| `collector.overlap_messages` | integer | `5` | Number of message IDs to go back from last checkpoint. Guards against missed edits near the boundary. |
| `collector.initial_search_depth` | integer | `500` | Number of messages to collect for a channel with no prior state. |
| `collector.retry_count` | integer | `3` | Maximum number of retry attempts per fetch operation. |
| `collector.retry_backoff_seconds` | integer | `5` | Base wait time between retries. Actual wait = backoff * attempt_number. |

### storage section

| Parameter | Type | Default | Description |
|---|---|---|---|
| `storage.base_path` | string | `"."` | Root directory for all data directories (state, raw, runs, logs). |
| `storage.raw_format` | string | `"jsonl"` | Output format for raw messages. Only `jsonl` is supported currently. |

### logging section

| Parameter | Type | Default | Description |
|---|---|---|---|
| `logging.level` | string | `"INFO"` | Logging verbosity. Accepted values: DEBUG, INFO, WARNING, ERROR. |
| `logging.file_path` | string | `"logs/collector.log"` | Path to the application log file. Relative to working directory. |

---

## channels.yaml Structure

```yaml
channels:
  - channel_id: null          # optional numeric ID; used if username is unavailable
    username: "channel_slug"  # @-less Telegram username; primary identifier
    enabled: true             # set to false to skip without removing
    title: "Human Name"       # optional display label
    notes: "Any context"      # optional operator note
```

### Channel Entry Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | yes | Telegram channel username without @. Used as the channel key throughout the system. |
| `enabled` | boolean | yes | If false, channel is skipped in every run. |
| `channel_id` | integer | no | Numeric Telegram channel ID. Optional; used as fallback. |
| `title` | string | no | Human-readable label. Not used in processing. |
| `notes` | string | no | Operator annotations. Not used in processing. |

---

## Environment Variable Overrides

| Variable | Default | Description |
|---|---|---|
| `TGC_CONFIG` | `config/app.yaml` | Path to main config file |
| `TGC_CHANNELS` | `config/channels.yaml` | Path to channels file |

These allow running with alternate configs without modifying files.

---

## Example: Minimal Production Config

```yaml
telegram:
  api_id: 123456
  api_hash: "abcdef1234567890abcdef1234567890"
  session_name: "prod_session"

collector:
  cron_interval: "0 */4 * * *"
  batch_size: 100
  overlap_messages: 5
  initial_search_depth: 500
  retry_count: 3
  retry_backoff_seconds: 5

storage:
  base_path: "/data/tg_collector"
  raw_format: "jsonl"

logging:
  level: "INFO"
  file_path: "/data/tg_collector/logs/collector.log"
```
