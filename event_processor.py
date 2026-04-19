"""
event_processor.py - Main LLM event extraction pipeline.

Implements the full extraction + validation workflow with nested retry logic:
  Outer loop (L times):
    -> Prompt1: extract events (retry up to N times for valid JSON schema)
    -> Prompt2: validate extraction (retry up to K times for valid JSON schema)
    -> If prompt2 says is_valid=false, restart outer loop
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Set, Dict

from llm_client import call_llm
from processor_config_loader import ProcessorConfig
from schema_validator import validate_json_response
import storage

log = logging.getLogger("tg_collector")
ai_log = logging.getLogger("ai_debug")

# Paths to schemas (relative to project root)
EXTRACTION_SCHEMA = os.path.join("schemas", "event_extraction.schema.json")
VALIDATION_SCHEMA = os.path.join("schemas", "event_validation.schema.json")


@dataclass
class ExtractedEvent:
    """A single event extracted from a message."""
    title: Optional[str]
    description: Optional[str]
    place: Optional[str]
    datetime: Optional[str]
    type: str
    confidence: int
    start_datetime: Optional[str] = None
    short_description: Optional[str] = None
    # Source metadata
    channel_id: str = ""
    channel_username: str = ""
    channel_title: str = ""
    message_id: int = 0
    message_date: str = ""
    source_text: str = ""


@dataclass
class ProcessingResult:
    """Result of processing a single message through the pipeline."""
    channel_id: str
    channel_username: str
    channel_title: str
    message_id: int
    message_date: str
    source_text: str
    events: List[ExtractedEvent] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    processed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _run_extraction(
    config: ProcessorConfig,
    prompt1_text: str,
    message_text: str,
    schema_path: str,
) -> tuple:
    """
    Run prompt1 (event extraction) with up to N retries.

    Returns:
        (parsed_dict, None) on success, or (None, last_error) on failure.
    """
    max_retries = config.processing.extraction_retries
    last_error = None

    for attempt in range(1, max_retries + 1):
        ai_log.debug("--- [EXTRACTION] Message Extraction (Attempt %d/%d) ---", attempt, max_retries)
        ai_log.debug("SYSTEM PROMPT:\n%s", prompt1_text)
        ai_log.debug("USER CONTENT (Text):\n%s", message_text)
        
        log.info(
            "Extraction attempt %d/%d",
            attempt,
            max_retries,
        )
        try:
            raw_response = call_llm(
                config.llm, prompt1_text, message_text
            )
            ai_log.debug("RAW RESPONSE:\n%s", raw_response)
        except Exception as e:
            last_error = "LLM call failed: %s" % str(e)
            ai_log.error("LLM ERROR: %s", last_error)
            log.warning("Extraction LLM error on attempt %d: %s", attempt, last_error)
            continue

        parsed, error = validate_json_response(raw_response, schema_path)
        if parsed is not None:
            ai_log.debug("SCHEMA STATUS: SUCCESS")
            log.info("Extraction succeeded on attempt %d", attempt)
            return parsed, None

        last_error = error
        ai_log.warning("SCHEMA STATUS: FAILED - %s", error)
        log.warning(
            "Extraction schema validation failed on attempt %d: %s",
            attempt,
            error,
        )

    return None, last_error


def _run_validation(
    config: ProcessorConfig,
    prompt2_text: str,
    message_text: str,
    extraction_json: dict,
    schema_path: str,
) -> tuple:
    """
    Run prompt2 (validation) with up to K retries.

    The user content for prompt2 includes both the original text
    and the extraction JSON from prompt1.

    Returns:
        (parsed_dict, None) on success, or (None, last_error) on failure.
    """
    max_retries = config.processing.validation_retries
    last_error = None

    # Build the user content with original text and extracted JSON
    user_content = (
        "Original text:\n"
        "---\n"
        "%s\n"
        "---\n\n"
        "Extracted JSON:\n"
        "%s"
    ) % (message_text, json.dumps(extraction_json, ensure_ascii=False, indent=2))

    for attempt in range(1, max_retries + 1):
        ai_log.debug("--- [VALIDATION] Extraction Validation (Attempt %d/%d) ---", attempt, max_retries)
        ai_log.debug("SYSTEM PROMPT:\n%s", prompt2_text)
        ai_log.debug("USER CONTENT (Extraction Result):\n%s", user_content)
        
        log.info(
            "Validation attempt %d/%d",
            attempt,
            max_retries,
        )
        try:
            raw_response = call_llm(
                config.llm, prompt2_text, user_content
            )
            ai_log.debug("RAW RESPONSE:\n%s", raw_response)
        except Exception as e:
            last_error = "LLM call failed: %s" % str(e)
            ai_log.error("LLM ERROR: %s", last_error)
            log.warning("Validation LLM error on attempt %d: %s", attempt, last_error)
            continue

        parsed, error = validate_json_response(raw_response, schema_path)
        if parsed is not None:
            ai_log.debug("SCHEMA STATUS: SUCCESS")
            log.info("Validation succeeded on attempt %d", attempt)
            return parsed, None

        last_error = error
        ai_log.warning("SCHEMA STATUS: FAILED - %s", error)
        log.warning(
            "Validation schema validation failed on attempt %d: %s",
            attempt,
            error,
        )

    return None, last_error


# ============================================================================
# Helper Functions for Incremental Processing
# ============================================================================

def get_new_messages(messages: List[dict], processed_ids: Set[int]) -> List[dict]:
    """
    Filter messages to include only those not yet processed.

    Args:
        messages: List of raw message dicts
        processed_ids: Set of message_ids that have been processed

    Returns:
        Filtered list of new messages
    """
    return [m for m in messages if m.get("message_id") not in processed_ids]


def load_processed_ids_by_channel(base_path: str) -> Dict[str, Set[int]]:
    """
    Load all processed message IDs grouped by channel.

    Args:
        base_path: Project base path

    Returns:
        Dict mapping channel_id -> set of processed message_ids
    """
    return storage.load_processed_ids_by_channel(base_path)


def _processing_result_to_dict(
    result: ProcessingResult,
    model_name: str,
    model_config: dict,
    run_id: str,
) -> dict:
    """
    Convert a ProcessingResult dataclass to a dict suitable for JSON serialization.

    Args:
        result: ProcessingResult object
        model_name: LLM model name
        model_config: LLM configuration dict
        run_id: Run ID

    Returns:
        Dict ready to be serialized to JSON and saved to processed/ storage
    """
    # Convert extracted events to dicts
    events_list = []
    for event in result.events:
        events_list.append({
            "title": event.title,
            "description": event.description,
            "place": event.place,
            "datetime": event.datetime,
            "type": event.type,
            "confidence": event.confidence,
            "start_datetime": event.start_datetime,
            "short_description": event.short_description,
        })

    return {
        "channel_id": result.channel_id,
        "channel_username": result.channel_username,
        "channel_title": result.channel_title,
        "message_id": result.message_id,
        "message_date": result.message_date,
        "source_text": result.source_text,
        "success": result.success,
        "error": result.error,
        "events": events_list,
        "processed_at": result.processed_at,
        "run_id": run_id,
        "model_name": model_name,
        "model_config": model_config,
    }


# ============================================================================
# Main Processing Functions
# ============================================================================

def process_message(
    config: ProcessorConfig,
    message: dict,
    channel_title: str,
    prompt1_text: str,
    prompt2_text: str,
    base_path: str,
) -> ProcessingResult:
    """
    Process a single message through the full extraction + validation pipeline.

    Implements the outer retry loop (L times) wrapping both prompt1 and prompt2.

    Args:
        config: Processor configuration.
        message: Raw message dict from JSONL storage.
        channel_title: Human-readable channel title.
        prompt1_text: Content of prompt1.md.
        prompt2_text: Content of prompt2.md.
        base_path: Project base path for schema resolution.

    Returns:
        ProcessingResult with extracted events or error info.
    """
    channel_id = message.get("channel_id", "")
    channel_username = message.get("channel_username", "")
    message_id = message.get("message_id", 0)
    message_date = message.get("message_date", "")
    message_text = message.get("text", "")

    prompt_message_text = (
        f"Название канала: {channel_title}\n"
        f"Дата поста: {message_date}\n\n"
        f"Текст поста:\n{message_text}"
    )

    result = ProcessingResult(
        channel_id=channel_id,
        channel_username=channel_username,
        channel_title=channel_title,
        message_id=message_id,
        message_date=message_date,
        source_text=message_text,
    )

    extraction_schema = os.path.join(base_path, EXTRACTION_SCHEMA)
    validation_schema = os.path.join(base_path, VALIDATION_SCHEMA)

    max_outer = config.processing.outer_retries
    last_error = None

    for outer_attempt in range(1, max_outer + 1):
        log.info(
            "Outer attempt %d/%d for message_id=%d (channel=%s)",
            outer_attempt,
            max_outer,
            message_id,
            channel_username,
        )

        # Stage 1: Extract events
        extraction, ext_error = _run_extraction(
            config, prompt1_text, prompt_message_text, extraction_schema
        )
        if extraction is None:
            last_error = "Extraction failed: %s" % ext_error
            log.warning(
                "Extraction exhausted retries on outer attempt %d: %s",
                outer_attempt,
                ext_error,
            )
            continue

        # If no events found, that is a valid result
        events_list = extraction.get("events", [])
        if not events_list:
            log.info(
                "No events found in message_id=%d (channel=%s)",
                message_id,
                channel_username,
            )
            result.success = True
            return result

	
        # Success - build extracted events
        log.info(
            "Pipeline succeeded for message_id=%d: %d events extracted",
            message_id,
            len(events_list),
        )
        for ev_data in events_list:
            event = ExtractedEvent(
                title=ev_data.get("title"),
                description=ev_data.get("description"),
                place=ev_data.get("place"),
                datetime=ev_data.get("datetime"),
                type=ev_data.get("type"),
                confidence=ev_data["confidence"],
                start_datetime=ev_data.get("start_datetime"),
                short_description=ev_data.get("short_description"),
                channel_id=channel_id,
                channel_username=channel_username,
                channel_title=channel_title,
                message_id=message_id,
                message_date=message_date,
                source_text=message_text,
            )
            result.events.append(event)

        result.success = True
        return result

    # All outer attempts exhausted
    result.error = last_error or "All retry attempts exhausted"
    log.error(
        "All outer attempts exhausted for message_id=%d (channel=%s): %s",
        message_id,
        channel_username,
        result.error,
    )
    return result


def load_all_messages(base_path: str) -> List[dict]:
    """
    Load all raw messages from the JSONL storage.

    Returns:
        List of message dicts from all channels and dates.
    """
    raw_root = os.path.join(base_path, "raw")
    messages = []

    if not os.path.isdir(raw_root):
        log.warning("Raw data directory not found: %s", raw_root)
        return messages

    for channel_dir_name in sorted(os.listdir(raw_root)):
        channel_path = os.path.join(raw_root, channel_dir_name)
        if not os.path.isdir(channel_path):
            continue

        for filename in sorted(os.listdir(channel_path)):
            if not filename.endswith(".jsonl"):
                continue

            filepath = os.path.join(channel_path, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        messages.append(msg)
                    except json.JSONDecodeError as e:
                        log.warning(
                            "Skipping malformed JSON in %s line %d: %s",
                            filepath,
                            line_num,
                            str(e),
                        )

    log.info("Loaded %d total messages from raw storage", len(messages))
    return messages


def load_channel_metadata(base_path: str) -> dict:
    """
    Load channel metadata (title, username) from state files.

    Returns:
        Dict mapping channel_id -> {title, username}.
    """
    state_dir = os.path.join(base_path, "state")
    metadata = {}

    if not os.path.isdir(state_dir):
        return metadata

    for filename in os.listdir(state_dir):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(state_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                state = json.load(f)

            # State files use channel_id like "channel_-1001158225587"
            # But raw messages use channel_id like "-1001158225587"
            raw_channel_id = state.get("channel_id", "")
            # Strip "channel_" prefix if present to match raw data
            if raw_channel_id.startswith("channel_"):
                raw_channel_id = raw_channel_id[len("channel_"):]

            metadata[raw_channel_id] = {
                "title": state.get("channel_title", raw_channel_id),
                "username": state.get("channel_username", ""),
            }
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("Failed to load state file %s: %s", filename, str(e))

    return metadata


def process_all_messages(
    config: ProcessorConfig,
    base_path: str,
    prompt1_text: str,
    prompt2_text: str,
    filter_channel: Optional[str] = None,
    exclude_channel_names: Optional[List[str]] = None,
    filter_message_id: Optional[int] = None,
    incremental: bool = True,
    model_name: Optional[str] = None,
    model_config: Optional[dict] = None,
    run_id: Optional[str] = None,
) -> List[ProcessingResult]:
    """
    Load and process all raw messages through the extraction pipeline.

    Supports incremental processing: only processes messages not yet in the
    processed/ storage.

    Args:
        config: Processor configuration.
        base_path: Project root path.
        prompt1_text: Content of prompt1.md.
        prompt2_text: Content of prompt2.md.
        filter_channel: Optional channel username or ID to filter by.
        exclude_channel_names: Optional list of channel titles or usernames to exclude.
        filter_message_id: Optional specific message ID to process (debug mode).
        incremental: If True, skip already-processed messages. Default: True.
        model_name: LLM model name to record (default: from config.llm.model).
        model_config: LLM configuration dict (default: from config.llm).
        run_id: Run ID for this processing batch (default: current ISO timestamp).

    Returns:
        List of ProcessingResult for each processed message.
    """
    # Default values
    if model_name is None:
        model_name = config.llm.model
    if model_config is None:
        model_config = {
            "temperature": config.llm.temperature,
            "max_tokens": config.llm.max_tokens,
        }
    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    messages = load_all_messages(base_path)
    channel_meta = load_channel_metadata(base_path)

    exclude_names = {
        name.strip().lower()
        for name in (exclude_channel_names or [])
        if name and name.strip()
    }
    if exclude_names:
        log.info("Excluding channel names from processing: %s", ", ".join(sorted(exclude_names)))

    # If filtering by message ID, skip incremental processing for that message
    if filter_message_id is not None:
        log.info("Debug mode: filtering to message_id=%d", filter_message_id)
        incremental = False  # Force reprocessing of the target message

    # Load processed IDs if incremental mode
    processed_ids_by_channel: Dict[str, Set[int]] = {}
    if incremental:
        processed_ids_by_channel = load_processed_ids_by_channel(base_path)
        log.info("Incremental mode enabled: loaded processed message IDs")

    results = []
    skipped = 0
    already_processed = 0
    processed = 0
    errors = 0

    for msg in messages:
        text = msg.get("text", "")
        channel_id = msg.get("channel_id", "")
        message_id = msg.get("message_id", 0)

        # If filtering by message ID, skip non-matching messages
        if filter_message_id is not None:
            if message_id != filter_message_id:
                continue

        # Get channel title and username from metadata
        meta = channel_meta.get(channel_id, {})
        channel_title = meta.get("title", channel_id)
        channel_username = meta.get("username", "")

        # Exclude channels by title or username
        if exclude_names:
            channel_title_lower = (channel_title or "").lower()
            channel_username_lower = (channel_username or "").lower()
            if channel_title_lower in exclude_names or channel_username_lower in exclude_names:
                log.debug(
                    "Skipping excluded channel '%s' (%s)",
                    channel_title,
                    channel_username,
                )
                continue

        # Filter by channel if requested
        if filter_channel:
            if filter_channel.lower() not in [channel_id.lower(), channel_username.lower()]:
                continue

        # Skip empty or short texts
        if config.processing.skip_empty_text and not text.strip():
            skipped += 1
            continue

        if len(text.strip()) < config.processing.min_text_length:
            skipped += 1
            continue

        # Check if already processed (incremental mode)
        if incremental:
            processed_ids = processed_ids_by_channel.get(channel_id, set())
            if message_id in processed_ids:
                already_processed += 1
                log.debug(
                    "Skipping already-processed message_id=%d from channel '%s'",
                    message_id,
                    channel_title,
                )
                continue

        log.info(
            "Processing message_id=%d from channel '%s'",
            message_id,
            channel_title,
        )

        result = process_message(
            config=config,
            message=msg,
            channel_title=channel_title,
            prompt1_text=prompt1_text,
            prompt2_text=prompt2_text,
            base_path=base_path,
        )

        # Save result to persistent storage
        result_dict = _processing_result_to_dict(
            result,
            model_name=model_name,
            model_config=model_config,
            run_id=run_id,
        )
        try:
            storage.save_processing_result(result_dict, base_path)
            log.debug("Saved processing result for message_id=%d", message_id)
        except Exception as e:
            log.error(
                "Failed to save processing result for message_id=%d: %s",
                message_id,
                str(e),
            )

        results.append(result)
        processed += 1

        if not result.success:
            errors += 1

    log.info(
        "Processing complete: %d processed, %d already processed, %d skipped, %d errors",
        processed,
        already_processed,
        skipped,
        errors,
    )
    return results
