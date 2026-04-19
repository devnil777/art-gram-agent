"""Simple HTML report generator."""
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from event_processor import ExtractedEvent, ProcessingResult
from processor_config_loader import ReportConfig
import storage

log = logging.getLogger("tg_collector")


def load_processed_events_from_storage(base_path: str):
    """Load processed events from persistent storage."""
    processed_records = storage.load_processing_results(base_path)
    successful, errors = [], []

    for record in processed_records:
        events = []
        for event_dict in record.get("events", []):
            event = ExtractedEvent(
                title=event_dict.get("title"),
                description=event_dict.get("description"),
                place=event_dict.get("place"),
                datetime=event_dict.get("datetime"),
                type=event_dict.get("type", "other"),
                confidence=event_dict.get("confidence", 1),
                start_datetime=event_dict.get("start_datetime"),
                short_description=event_dict.get("short_description"),
                channel_id=record.get("channel_id", ""),
                channel_username=record.get("channel_username", ""),
                channel_title=record.get("channel_title", ""),
                message_id=record.get("message_id", 0),
                message_date=record.get("message_date", ""),
                source_text=record.get("source_text", ""),
            )
            events.append(event)
        
        result = ProcessingResult(
            channel_id=record.get("channel_id", ""),
            channel_username=record.get("channel_username", ""),
            channel_title=record.get("channel_title", ""),
            message_id=record.get("message_id", 0),
            message_date=record.get("message_date", ""),
            source_text=record.get("source_text", ""),
            events=events,
            success=record.get("success", False),
            error=record.get("error"),
            processed_at=record.get("processed_at", ""),
        )
        
        if result.success:
            successful.append(result)
        else:
            errors.append(result)
    
    return successful, errors


def _parse_iso_datetime(date_value: str) -> datetime:
    """Parse ISO datetime string and return a UTC-aware datetime."""
    parsed = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_event_datetime(event: ExtractedEvent) -> str:
    """Format event date for human-readable report output."""
    date_value = event.start_datetime or event.datetime
    if not date_value:
        return ""

    try:
        if event.start_datetime:
            parsed = _parse_iso_datetime(event.start_datetime)
        else:
            match = re.search(r"(\d{4}-\d{2}-\d{2})", date_value)
            if match:
                parsed = datetime.fromisoformat(match.group(1))
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                return date_value.split()[0]

        if parsed.year == datetime.now(timezone.utc).year:
            return parsed.strftime("%d.%m")
        return parsed.strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return date_value.split()[0]


def _get_event_timestamp(event: ExtractedEvent) -> datetime:
    """Convert event publication date string into a timestamp for sorting."""
    date_value = event.message_date
    if not date_value:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        return _parse_iso_datetime(date_value)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _build_message_link(base_url: str, username: str, message_id: int) -> str:
    """Build link."""
    if not username or not message_id:
        return ""
    return f"{base_url.rstrip('/')}/{username}/{message_id}"


def _is_recent_message(message_date: str, days: int = 1) -> bool:
    """Check if message is from last N days."""
    if not message_date:
        return False
    
    try:
        # Parse ISO format: "2026-04-18T12:00:00+00:00"
        msg_dt = _parse_iso_datetime(message_date)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return msg_dt >= cutoff
    except (ValueError, TypeError):
        return False

def _build_summary_text(
    report_config: ReportConfig,
    events: List[ExtractedEvent],
    page_size_bytes: int,
) -> List[str]:
    """Build a list of event summary pages for Telegram messages.

    Each summary item is treated as a separate page and must fit within
    the provided page size.
    """
    pages: List[str] = []
    limited = events
    current_page = ""

    for index, event in enumerate(limited, start=1):
        description = _get_event_description(event)
        event_date = _format_event_datetime(event)
        place = event.place or ""
        source_name = event.channel_title or event.channel_username or event.channel_id or "Источник"
        source_link = _build_message_link(report_config.telegram_base_url, event.channel_username, event.message_id)

        block_lines = [f"{index}. {description}"]
        details = []
        if event_date:
            details.append(f"**Когда**: {event_date}")
        if place:
            details.append(f"**Место**: {place}")
        if source_link:
            details.append(f"**Источник**: [{source_name}]({source_link})")
        else:
            details.append(f"**Источник**: {source_name}")

        block_lines.append("\n".join(details))
        block_text = "\n".join(block_lines).strip()

        if len(block_text.encode("utf-8")) > page_size_bytes:
            raise ValueError("page_size_bytes too small for a single event summary")

        candidate = block_text if not current_page else f"{current_page}\n\n{block_text}"
        if len(candidate.encode("utf-8")) <= page_size_bytes:
            current_page = candidate
            continue

        if current_page:
            pages.append(current_page)
        current_page = block_text

    if current_page:
        pages.append(current_page)

    return pages


def _sort_events(events: List[ExtractedEvent]) -> List[ExtractedEvent]:
    """Sort by publication date in channel, then confidence."""
    return sorted(
        events,
        key=lambda e: (_get_event_timestamp(e), -e.confidence),
        reverse=True
    )


def _get_event_description(event: ExtractedEvent) -> str:
    return event.short_description or event.title or event.description or "Без описания"


def generate_report(
    report_config: ReportConfig,
    base_path: str,
    results: Optional[List[ProcessingResult]] = None,
    load_from_storage: bool = False,
) -> List[str]:
    """Generate simple plain HTML report."""
    output_dir = os.path.join(base_path, report_config.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    if load_from_storage:
        successful, _ = load_processed_events_from_storage(base_path)
        results = successful
    elif results is None:
        results = []

    all_events = []
    for result in results:
        if result.success and result.events:
            all_events.extend(result.events)

    # Filter messages from last N days
    days = report_config.report_days
    recent_events = [e for e in all_events if _is_recent_message(e.message_date, days=days)]
    sorted_events = _sort_events(recent_events)

    html = ["<!DOCTYPE html>", "<html><head>"]
    html.append('<meta charset="UTF-8">')
    html.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html.append("<title>Отчёт об обработанных сообщениях</title>")
    html.append("<style>body { font-family: Arial; margin: 20px; }")
    html.append("pre { background: #f5f5f5; padding: 15px; border-radius: 4px; }")
    html.append("a { color: #0066cc; }</style>")
    html.append("</head><body>")
    days_text = "день" if days == 1 else "дня" if days in [2, 3, 4] else "дней"
    html.append(f"<h1>Отчёт об обработанных сообщениях (последние {days} {days_text})</h1>")
    html.append(f"<p style='color: #999; font-size: 0.9em;'>Обработанных сообщений: {len(recent_events)}</p>")
    html.append(f"<p style='color: #999; font-size: 0.9em;'>Сгенерировано: {datetime.now(timezone.utc).strftime('%d.%m.%Y в %H:%M UTC')}</p>")
    html.append("<pre>")

    for event in sorted_events:
        description = _get_event_description(event)
        html.append(f"{description}")

        place_line_parts = []
        event_date = _format_event_datetime(event)
        if event_date:
            place_line_parts.append(f"Когда: {event_date}")

        if event.place:
            place_line_parts.append(f"Место: {event.place}")

        if place_line_parts:
            html.append(". ".join(place_line_parts))

        source_name = event.channel_title or event.channel_username or event.channel_id or "Источник"
        source_link = _build_message_link(report_config.telegram_base_url, event.channel_username, event.message_id)
        if source_link:
            html.append(f"Источник <a href=\"{source_link}\">{source_name}</a>")
        else:
            html.append(f"Источник {source_name}")

        html.append(f"<br/>")


    html.append("</pre></body></html>")
    
    content = "\n".join(html)
    report_filename = report_config.report_filename or "events_report"
    html_path = os.path.join(output_dir, f"{report_filename}.html")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    log.info("HTML report saved to %s", html_path)
    return [html_path]


def generate_report_text(
    report_config: ReportConfig,
    base_path: str,
    results: Optional[List[ProcessingResult]],
    load_from_storage: bool,
    page_size_bytes: int,
    target_identifier: Optional[str] = None,
    skip_already_sent: bool = False,
    days: Optional[int] = None,
) -> List[str]:
    """
    Generate plain text report pages of recent events for Telegram.

    Args:
        report_config: Report configuration
        base_path: Project base path
        results: Optional list of processing results (if load_from_storage=False)
        load_from_storage: Whether to load events from storage
        page_size_bytes: Maximum bytes per page
        target_identifier: If provided and skip_already_sent=True, filter out events already sent to this target
        skip_already_sent: Whether to skip events already sent to the target
        days: Override report_days from config

    Returns:
        List of text pages
    """
    if load_from_storage:
        successful, _ = load_processed_events_from_storage(base_path)
        results = successful
    elif results is None:
        results = []

    all_events = []
    for result in results:
        if result.success and result.events:
            all_events.extend(result.events)

    # Use override days if provided, else use config
    report_days = days if days is not None else report_config.report_days
    
    recent_events = [
        e for e in all_events if _is_recent_message(e.message_date, days=report_days)
    ]

    # Filter out already sent events if requested
    if skip_already_sent and target_identifier:
        sent_map = storage.load_sent_events(base_path, target_identifier)
        sent_ids = sent_map.get(target_identifier, set())
        recent_events = [
            e for e in recent_events
            if f"{e.channel_id}:{e.message_id}" not in sent_ids
        ]

    sorted_events = _sort_events(recent_events)
    return _build_summary_text(
        report_config,
        sorted_events,
        page_size_bytes=page_size_bytes,
    )
