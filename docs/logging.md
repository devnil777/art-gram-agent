# Logging Policy

## Requirements

- All log messages in English.
- No Unicode symbols in any log message.
- Format: plain text, one line per event.
- Level controlled by `logging.level` in config.
- Log file path controlled by `logging.file_path` in config.

## Log Format

```
YYYY-MM-DDTHH:MM:SS | LEVEL    | module               | run=<run_id> | ch=<channel_id> | message
```

Example lines:

```
2024-06-01T08:00:01 | INFO     | collector            | run=20240601T080001Z | ch=none        | === Collector run started: 20240601T080001Z ===
2024-06-01T08:00:02 | INFO     | collector            | run=20240601T080001Z | ch=example_ch  | Processing channel: example_ch
2024-06-01T08:00:03 | INFO     | fetcher              | run=20240601T080001Z | ch=example_ch  | Total messages fetched from example_ch: 42
2024-06-01T08:00:04 | INFO     | collector            | run=20240601T080001Z | ch=example_ch  | New unique messages to store: 42
2024-06-01T08:00:05 | INFO     | collector            | run=20240601T080001Z | ch=example_ch  | Channel example_ch: saved 42 messages, last_message_id=1234
2024-06-01T08:00:06 | INFO     | collector            | run=20240601T080001Z | ch=none        | === Run 20240601T080001Z finished. Channels: 3, Errors: 0, Messages: 87 ===
```

## Context Fields

| Field | Description |
|---|---|
| `run=` | Current run_id. Set at start of each run. |
| `ch=` | Current channel being processed. Set per channel loop iteration. `none` when outside channel scope. |

These fields are injected via a `logging.Filter` subclass (`ContextFilter` in `logger.py`).
They are attached to every log record without modifying the call site.

## Log Levels

| Level | When to use |
|---|---|
| DEBUG | Per-page fetch details, internal loop state. Enable during development. |
| INFO | Normal operation events: run start/end, channel start, message counts, state updates. |
| WARNING | Recoverable issues: FloodWaitError, retry attempts, skipped channels. |
| ERROR | Failures that affect a channel: fetch failure, write failure, unexpected exception. |

## Questions the Log Should Answer

- Which channel was being processed at time T?
- How many messages were collected from each channel in run R?
- At which message_id did a failure occur?
- How many retries happened and why?
- Was a previous run interrupted, and did the next run resume correctly?
- What is the last successful checkpoint per channel?

## Output Destinations

Logs are written to both:
1. The file at `logging.file_path`.
2. Standard output (stdout) via a `StreamHandler`.

Both use the same format and level.
