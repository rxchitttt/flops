"""
Append-only ingestion log: one row per extraction attempt, per assignment requirement
"Record extraction date, source, file/API status, and row count."
"""
import csv
import datetime as dt
import sys
from pathlib import Path

# Ensure the ingestion/ directory is always on sys.path so that `from config import`
# resolves correctly regardless of how this module was imported or from where.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import INGESTION_LOG_CSV

FIELDS = ["extracted_at_utc", "source", "endpoint", "status", "row_count", "raw_file", "error_message"]


def log_extraction(source: str, endpoint: str, status: str, row_count: int,
                    raw_file: str = "", error_message: str = "") -> None:
    """status should be one of: SUCCESS, EMPTY, FAILED."""
    is_new = not Path(INGESTION_LOG_CSV).exists()
    with open(INGESTION_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "extracted_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": source,
            "endpoint": endpoint,
            "status": status,
            "row_count": row_count,
            "raw_file": raw_file,
            "error_message": error_message,
        })
