"""
log_reporter.py - Parses logs and generates a deduplicated error report.
"""

import os
import re
import datetime
from collections import defaultdict
from typing import Tuple

# Configurable constants
ERROR_TRUNCATE_LENGTH = 100
ERROR_CLEANUP_PATTERNS = [
    r"message_id=\d+",                           # Remove message_id
    r"run=[\w\d]+",                              # Remove run_id from logger format
    r"ch=[\w\d\-]+",                             # Remove channel_id
    r"channel=[\w\d]+",                          # Remove channel name from some logs
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",      # Remove timestamps
    r"\| ERROR\s+\| [\w_]+\s+\|",                # Remove the generic log prefix to focus on the message
]


def check_and_generate_report(base_path: str, target_date: datetime.date = None) -> Tuple[bool, str]:
    """
    Checks logs for the target_date (default yesterday) and returns a report.
    Returns (should_send, report_text).
    """
    if target_date is None:
        target_date = datetime.date.today() - datetime.timedelta(days=1)

    date_str = target_date.strftime("%Y-%m-%d")
    logs_dir = os.path.join(base_path, "logs")
    flag_file = os.path.join(logs_dir, ".last_log_report_date")

    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            last_date = f.read().strip()
        if last_date == date_str:
            return False, ""  # Already sent report for this date

    # Process logs
    files_to_check = [
        f"collector_{date_str}.log",
        f"processor_{date_str}.log"
    ]

    errors = []

    # Regex to detect start of a log line: YYYY-MM-DDTHH:MM:SS | LEVEL |
    log_start_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s*\|\s*([A-Z]+)\s*\|")

    for filename in files_to_check:
        filepath = os.path.join(logs_dir, filename)
        if not os.path.exists(filepath):
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            current_error = []
            capturing = False
            for line in f:
                match = log_start_re.match(line)
                if match:
                    level = match.group(1)
                    if level == "ERROR":
                        if current_error:
                            errors.append("".join(current_error))
                        current_error = [line]
                        capturing = True
                    else:
                        if current_error:
                            errors.append("".join(current_error))
                            current_error = []
                        capturing = False
                else:
                    if capturing:
                        current_error.append(line)

            if current_error:
                errors.append("".join(current_error))

    if not errors:
        # Save flag
        os.makedirs(logs_dir, exist_ok=True)
        with open(flag_file, "w") as f:
            f.write(date_str)
        return True, f"Система работает штатно. Ошибок за {date_str} не найдено."

    # Deduplicate errors
    error_counts = defaultdict(int)
    for err in errors:
        # Clean string
        cleaned = err
        for pattern in ERROR_CLEANUP_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned)

        # Clean up double spaces/newlines resulting from removal
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Remove leading punctuation if any
        cleaned = re.sub(r"^[:|\-\s]+", "", cleaned)

        # Truncate
        cleaned = cleaned[:ERROR_TRUNCATE_LENGTH].strip()
        error_counts[cleaned] += 1

    # Generate report
    report_lines = [f"📊 **Отчет об ошибках за {date_str}**\n"]
    for err, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
        report_lines.append(f"❌ **[{count} раз(а)]**\n`{err}...`\n")

    report_text = "\n".join(report_lines)

    # Save flag
    os.makedirs(logs_dir, exist_ok=True)
    with open(flag_file, "w") as f:
        f.write(date_str)

    return True, report_text
