"""
process_runner.py - CLI entry point for the event extraction pipeline.

Usage:
    python process_runner.py [--config CONFIG_PATH]

Loads raw JSONL messages, processes them through the LLM extraction
and validation pipeline, and generates a sorted event report.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from event_processor import process_all_messages
from processor_config_loader import load_processor_config
from report_generator import generate_report
from utils import set_workspace_root_from_env

# Setup basic logging for the pipeline
log = logging.getLogger("tg_collector")


def setup_pipeline_logger(level: str = "INFO"):
    """Configure logging for the processing pipeline."""
    fmt = (
        "%(asctime)s | %(levelname)-8s | %(module)-20s | %(message)s"
    )
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S")

    logger = logging.getLogger("tg_collector")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers
    if not logger.handlers:
        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # File handler for processor logs
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(log_dir, "processor.log"), encoding="utf-8"
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        # Dedicated AI Debug Logger
        ai_debug_logger = logging.getLogger("ai_debug")
        ai_debug_logger.setLevel(logging.DEBUG)  # Always capture full detail in the debug log
        
        ai_fh = logging.FileHandler(
            os.path.join(log_dir, "ai_debug.log"), encoding="utf-8"
        )
        # Use simpler formatter for AI debug to make it more like a transcript
        ai_formatter = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        ai_fh.setFormatter(ai_formatter)
        ai_debug_logger.addHandler(ai_fh)
        # Ensure it doesn't propagate to the root/console logger to avoid clutter
        ai_debug_logger.propagate = False


def load_prompt_file(path: str) -> str:
    """Load a prompt template from a markdown file."""
    if not os.path.exists(path):
        log.error("Prompt file not found: %s", path)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        log.error("Prompt file is empty: %s", path)
        sys.exit(1)

    return content


def main():
    workspace_root = set_workspace_root_from_env("ART_GRAM_HOME")

    parser = argparse.ArgumentParser(
        description="Event extraction pipeline - process Telegram messages via LLM"
    )
    parser.add_argument(
        "--config",
        default="config/processor_config.yaml",
        help="Path to processor config file (default: config/processor_config.yaml)",
    )
    parser.add_argument(
        "--base-path",
        default=workspace_root,
        help="Project base path (default: ART_GRAM_HOME or current directory)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--channel",
        help="Filter by channel username or ID (optional)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        default=True,
        help="Use incremental processing (skip already-processed messages). Default: True",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Reprocess all messages (equivalent to --no-incremental). Overrides --incremental.",
    )
    parser.add_argument(
        "--generate-report",
        action="store_true",
        default=True,
        help="Generate report after processing. Default: True",
    )
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="Skip report generation",
    )
    parser.add_argument(
        "--model-name",
        help="LLM model name to record in processing results (default: from config)",
    )
    args = parser.parse_args()

    # Determine incremental mode
    incremental = not args.full

    # Determine report generation
    generate_report_flag = args.generate_report and not args.skip_report

    setup_pipeline_logger(args.log_level)

    started_at = datetime.now(timezone.utc)
    log.info("=== Event processing pipeline started ===")

    # Resolve base path and load configuration
    base_path = os.path.abspath(args.base_path)
    config_path = os.path.join(base_path, args.config)
    log.info("Loading config from: %s", config_path)
    config = load_processor_config(config_path)

    log.info(
        "LLM config: model=%s, api_base=%s, temperature=%.2f",
        config.llm.model,
        config.llm.api_base,
        config.llm.temperature,
    )
    log.info(
        "Retry config: extraction=%d, validation=%d, outer=%d",
        config.processing.extraction_retries,
        config.processing.validation_retries,
        config.processing.outer_retries,
    )

    # Processing mode
    log.info(
        "Processing mode: %s",
        "incremental (skip already-processed)" if incremental else "full (reprocess all)",
    )

    # Load prompts
    prompt1_path = os.path.join(base_path, "prompt1.md")
    prompt2_path = os.path.join(base_path, "prompt2.md")

    log.info("Loading prompt1 from: %s", prompt1_path)
    prompt1_text = load_prompt_file(prompt1_path)

    log.info("Loading prompt2 from: %s", prompt2_path)
    prompt2_text = load_prompt_file(prompt2_path)

    # Determine model name for recording
    model_name = args.model_name if args.model_name else config.llm.model
    model_config = {
        "temperature": config.llm.temperature,
        "max_tokens": config.llm.max_tokens,
    }

    # Generate run ID
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Process all messages
    results = process_all_messages(
        config=config,
        base_path=base_path,
        prompt1_text=prompt1_text,
        prompt2_text=prompt2_text,
        filter_channel=args.channel,
        incremental=incremental,
        model_name=model_name,
        model_config=model_config,
        run_id=run_id,
    )

    # Generate report
    if generate_report_flag:
        log.info("Generating HTML reports grouped by date...")
        report_files = generate_report(
            report_config=config.report,
            base_path=args.base_path,
            results=results,
            load_from_storage=True,  # Use in-memory results
        )
    else:
        log.info("Report generation skipped (use --generate-report to enable)")
        report_files = []

    # Summary
    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    total_events = sum(len(r.events) for r in results)
    total_errors = sum(1 for r in results if not r.success)
    total_success = sum(1 for r in results if r.success)

    log.info("=== Pipeline complete ===")
    log.info("Duration: %.1f seconds", duration)
    log.info("Messages processed: %d", len(results))
    log.info("Successful: %d, Errors: %d", total_success, total_errors)
    log.info("Total events extracted: %d", total_events)
    if report_files:
        log.info("Generated %d HTML report(s):", len(report_files))
        for report_path in report_files:
            log.info("  - %s", report_path)


if __name__ == "__main__":
    main()
