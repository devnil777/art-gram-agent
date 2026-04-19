# Reliability and Recovery

## Core Invariants

The system guarantees the following invariants at all times:

1. **Raw data is immutable after write.** JSONL files are only appended to. Existing records are never deleted or modified.

2. **State never advances ahead of stored data.** The checkpoint (`last_success_message_id`) is updated only after `append_messages()` has returned successfully.

3. **`message_id` is unique within a channel.** Enforced by deduplication against loaded existing IDs before writing.

4. **Retry is safe.** Re-running the collector after any failure produces the same result as if no failure occurred. No duplicates. No data loss.

5. **A skipped run causes no data loss.** Missing a scheduled run means messages from that period will be collected in the next run, because the checkpoint has not advanced.

6. **Mid-cycle failure does not corrupt history.** If the collector fails mid-channel, channels already processed in that run are unaffected.

## Atomic File Write Protocol

All file writes (raw data, state, run log) use the same atomic protocol:

```python
fd, tmp_path = tempfile.mkstemp(dir=target_directory, suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        # write content
        f.flush()
        os.fsync(f.fileno())   # ensure data is on disk
    os.replace(tmp_path, target_path)  # atomic rename
except Exception:
    os.unlink(tmp_path)  # clean up temp file
    raise
```

- The target file is not touched until the rename step.
- If the process crashes before rename, the temp file is abandoned and the original is intact.
- `os.replace` is atomic on POSIX (Linux, macOS). On Windows it is not fully atomic, but acceptable for this use case.

## Retry Behavior

| Error Type | Behavior |
|---|---|
| `FloodWaitError` | Wait `e.seconds + 5` then retry. No retry limit (obeys Telegram). |
| `ChannelPrivateError` | Fatal for this channel. Log and skip. |
| `UsernameNotOccupiedError` | Fatal for this channel. Log and skip. |
| Network / timeout error | Retry up to `retry_count` times with backoff `retry_backoff * attempt`. |
| All retries exhausted | Mark channel as `error` in state. Continue to next channel. |

## Recovery After Failure

### Scenario: Collector crashes mid-channel

- Channels processed before the crash: state is up to date, data is saved.
- Channel being processed when crash occurred: state is unchanged (at previous checkpoint). Raw file may or may not have the temp write committed; the original is intact.
- Next run: re-fetches from last successful checkpoint for the affected channel.

### Scenario: Disk full during write

- Temp file write fails. Exception is caught. Temp file is deleted.
- Original raw file and state file are untouched.
- Error is recorded in state with incremented `error_count`.
- Next run will retry from the same checkpoint.

### Scenario: Telegram API unreachable

- All fetch retries are exhausted. Error state is saved.
- No raw data written (nothing to corrupt).
- Next run retries from the same checkpoint.

### Scenario: Duplicate run (cron fires twice)

- Second run fetches the same message range.
- Deduplication removes all already-stored messages.
- Nothing is written. State is not updated (or updated with same value).
- No side effects.

## Error State Tracking

The state file tracks `error_count` and `last_error` fields.
These accumulate across failed runs without resetting the checkpoint.
On the next successful run, `status` reverts to `"ok"` and `error_count` is preserved
but `last_error` reflects the last failure for reference.
