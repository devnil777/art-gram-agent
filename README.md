# tg_collector

Incremental Telegram channel message collector using Telethon.
Designed for cron-based scheduling, file-based storage, and reliable
idempotent operation.

## Requirements

- Python 3.9+
- pip install -r requirements.txt
- A Telegram account with API credentials from https://my.telegram.org

## First-time Setup

1. Edit `config/app.yaml`:
   - Set `telegram.api_id` and `telegram.api_hash`.
   - Optionally adjust `storage.base_path` to an absolute path.

2. Edit `config/channels.yaml`:
   - Add channels you want to collect.
   - Set `enabled: true`.

3. Authenticate Telethon session (first run prompts for phone/code):

```
python collector.py
```

After the first interactive session authentication, subsequent runs are
fully non-interactive.

## Running via Cron

Add to crontab (every 4 hours):

```
0 */4 * * * cd /path/to/tg_collector && python collector.py >> logs/cron.log 2>&1
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TGC_CONFIG` | `config/app.yaml` | Path to main config |
| `TGC_CHANNELS` | `config/channels.yaml` | Path to channels list |

## Output

- `raw/channel_<username>/YYYY-MM-DD.jsonl` - Collected messages
- `state/channel_<username>.json` - Per-channel checkpoint
- `runs/run_<timestamp>.json` - Per-run journal
- `logs/collector.log` - Application log

## Documentation

See `reports/` for full documentation:
- `reports/structure.md` - Directory layout
- `reports/configuration.md` - Config reference
- `reports/collection_algorithm.md` - How collection works
- `reports/storage_format.md` - JSONL record format
- `reports/reliability.md` - Failure handling and invariants
- `reports/logging.md` - Log format and policy
- `reports/data_dictionary.md` - All field definitions

See `schemas/` for JSON Schema definitions of all file formats.
