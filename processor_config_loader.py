"""
processor_config_loader.py - Configuration loading for the event processing pipeline.

Loads processor_config.yaml with LLM, retry, and report settings.
"""

import yaml
from dataclasses import dataclass, field
from typing import List


@dataclass
class LLMConfig:
    model: str
    api_base: str
    api_key: str
    temperature: float
    max_tokens: int
    timeout: int


@dataclass
class ProcessingConfig:
    extraction_retries: int
    validation_retries: int
    outer_retries: int
    skip_empty_text: bool
    min_text_length: int
    exclude_channels: List[str] = field(default_factory=list)


@dataclass
class ReportConfig:
    output_dir: str
    report_filename: str
    telegram_base_url: str
    report_days: int


@dataclass
class ProcessorConfig:
    llm: LLMConfig
    processing: ProcessingConfig
    report: ReportConfig


def load_processor_config(path: str) -> ProcessorConfig:
    """Load and parse the processor configuration file."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    llm = raw["llm"]
    proc = raw["processing"]
    rep = raw["report"]

    return ProcessorConfig(
        llm=LLMConfig(
            model=str(llm["model"]),
            api_base=str(llm["api_base"]),
            api_key=str(llm["api_key"]),
            temperature=float(llm["temperature"]),
            max_tokens=int(llm["max_tokens"]),
            timeout=int(llm["timeout"]),
        ),
        processing=ProcessingConfig(
            extraction_retries=int(proc["extraction_retries"]),
            validation_retries=int(proc["validation_retries"]),
            outer_retries=int(proc["outer_retries"]),
            skip_empty_text=bool(proc["skip_empty_text"]),
            min_text_length=int(proc["min_text_length"]),
            exclude_channels=[str(name).strip() for name in proc.get("exclude_channels", []) if name is not None],
        ),
        report=ReportConfig(
            output_dir=str(rep["output_dir"]),
            report_filename=str(rep["report_filename"]),
            telegram_base_url=str(rep["telegram_base_url"]),
            report_days=int(rep.get("report_days", 1)),
        ),
    )
