# Collection Algorithm

## Entry Point

The collector is started by external cron (e.g., every 4 hours):

```
python collector.py
```

Environment variables `TGC_CONFIG` and `TGC_CHANNELS` may override default config paths.

## Full Cycle

```
START
  |
  v
Load app.yaml and channels.yaml
  |
  v
Generate run_id (timestamp-based, UTC)
  |
  v
Set up logger with run_id context
  |
  v
Open Telethon client session
  |
  v
For each ENABLED channel in channels.yaml:
  |
  +-- Load channel state from state/channel_<id>.json
  |
  +-- Determine min_id:
  |     - If state exists: min_id = last_success_message_id - overlap_messages
  |     - If no state (new channel): min_id = 0
  |
  +-- Fetch messages from Telegram:
  |     - Use Telethon get_messages with min_id and batch_size
  |     - Paginate until no more new messages
  |     - Retry on transient errors (FloodWait, network errors)
  |     - Sort result ascending by message_id
  |
  +-- If new channel: truncate to last initial_search_depth messages
  |
  +-- Load existing stored message_ids for deduplication
  |
  +-- Normalize each unseen message to dict format
  |
  +-- Write normalized messages to raw/channel_<id>/YYYY-MM-DD.jsonl
  |     (atomically, using temp file + fsync + os.replace)
  |
  +-- If write succeeded:
  |     Update state/channel_<id>.json with last message_id
  |
  +-- If write or fetch failed:
        Save error info to state (do not advance checkpoint)
        Continue to next channel
  |
  v
Write run log to runs/run_<run_id>.json
  |
  v
Log run summary
  |
END
```

## Key Design Decisions

### State Advancement Rule
State is updated ONLY after confirmed successful write to raw storage.
If write fails, state stays at the previous checkpoint.
Next run will re-fetch from the same starting point.

### Overlap
The collector goes back `overlap_messages` positions from the last checkpoint.
This catches messages that may have been missed near the boundary
(e.g., due to Telegram ID gaps or delivery ordering).
Deduplication prevents re-storing already-seen messages.

### Initial Depth
For channels with no prior state, only the most recent `initial_search_depth`
messages are collected. This bounds first-run cost for active channels.

### Per-Channel Isolation
Failure in one channel does not stop collection for subsequent channels.
Each channel is fully independent. A run log records per-channel outcomes.

### Idempotency
The collector may be run multiple times safely:
- Deduplication prevents duplicate records.
- State checkpoint prevents redundant Telegram API calls.
- Atomic writes prevent partial-write corruption.

## Pagination

Telethon's `get_messages` is called in a loop with `offset_id` set to the
smallest `message_id` seen in the previous page.
`min_id` is set to the last checkpoint so only new messages are returned.
The loop exits when a page is smaller than `batch_size` (no more pages).
