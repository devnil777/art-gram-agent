# Project Directory Structure

## Overview

The collector is organized into distinct directories by concern.
No business logic lives in the storage or state layers.

```
tg_collector/
|-- collector.py              # Main orchestrator - entry point
|-- fetcher.py                # Telegram fetch logic (Telethon)
|-- storage.py                # Raw JSONL write layer
|-- state.py                  # Channel checkpoint management
|-- run_log.py                # Per-run journal writer
|-- config_loader.py          # Config parsing and dataclasses
|-- logger.py                 # Logging setup and context filter
|-- utils.py                  # Shared utilities (run_id generation)
|-- requirements.txt          # Python dependencies
|
|-- config/
|   |-- app.yaml              # Main application configuration
|   |-- channels.yaml         # List of channels to collect
|
|-- state/
|   |-- channel_<id>.json     # Per-channel checkpoint (one per channel)
|
|-- raw/
|   |-- channel_<id>/
|       |-- YYYY-MM-DD.jsonl  # Daily raw message files (append-only)
|
|-- runs/
|   |-- run_<timestamp>.json  # Per-run execution journal
|
|-- logs/
|   |-- collector.log         # Application log (rotating text)
|
|-- reports/
|   |-- structure.md          # This file
|   |-- configuration.md      # Config parameter reference
|   |-- logging.md            # Logging policy
|   |-- storage_format.md     # JSONL format specification
|   |-- collection_algorithm.md # Collection cycle description
|   |-- reliability.md        # Reliability and recovery guarantees
|   |-- data_dictionary.md    # Field definitions
|
|-- schemas/
    |-- raw_message.schema.json   # JSON Schema for raw JSONL records
    |-- channel_state.schema.json # JSON Schema for state files
    |-- run_log.schema.json       # JSON Schema for run log files
```

## Directory Roles

### config/
Read-only at runtime. Contains all operator-supplied configuration.
Never written to by the collector process.

### state/
Written by the collector only after successful raw data persistence.
One JSON file per channel. Acts as the durable checkpoint.

### raw/
Append-only JSONL storage. Files are never overwritten once created.
Organized by channel and date. The source of truth for collected data.

### runs/
One JSON file per execution. Immutable after write.
Useful for auditing and debugging past runs.

### logs/
Rolling text log. All entries in English, no Unicode symbols.

### reports/ and schemas/
Human-readable and machine-readable documentation.
Generated once during project setup; updated manually as needed.
