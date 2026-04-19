"""
schema_validator.py - JSON response parsing and schema validation.

Parses raw LLM text output into JSON and validates against JSON Schema.
Handles common LLM quirks like markdown code fences.
"""

import json
import logging
import os
import re
from typing import Optional, Tuple

import jsonschema

log = logging.getLogger("tg_collector")

# Cache loaded schemas to avoid repeated file reads
_schema_cache: dict = {}


def _load_schema(schema_path: str) -> dict:
    """Load and cache a JSON schema from disk."""
    if schema_path not in _schema_cache:
        with open(schema_path, "r", encoding="utf-8") as f:
            _schema_cache[schema_path] = json.load(f)
    return _schema_cache[schema_path]


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that LLMs sometimes wrap around JSON."""
    stripped = text.strip()

    # Handle ```json ... ``` or ``` ... ```
    pattern = r"^```(?:json)?\s*\n?(.*?)\n?\s*```$"
    match = re.match(pattern, stripped, re.DOTALL)
    if match:
        return match.group(1).strip()

    return stripped


def validate_json_response(
    text: str, schema_path: str
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Parse JSON from LLM text and validate against a schema.

    Args:
        text: Raw text response from the LLM.
        schema_path: Absolute path to the JSON schema file.

    Returns:
        Tuple of (parsed_dict, None) on success,
        or (None, error_message) on failure.
    """
    # Step 1: Strip code fences
    cleaned = _strip_code_fences(text)

    # Step 2: Parse JSON
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        error_msg = "JSON parse error: %s" % str(e)
        log.warning(error_msg)
        return None, error_msg

    # Step 3: Validate against schema
    schema = _load_schema(schema_path)
    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.ValidationError as e:
        error_msg = "Schema validation error: %s (path: %s)" % (
            e.message,
            ".".join(str(p) for p in e.absolute_path),
        )
        log.warning(error_msg)
        return None, error_msg

    return parsed, None
