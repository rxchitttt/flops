"""
Fallback/backfill ingestion: load a manually-downloaded Kaggle historical AQI CSV
(e.g. "India Air Quality Data" or a Bengaluru-specific station CSV) using Pandas.

Kaggle requires an authenticated download (Kaggle account + kaggle.json token), so per the
assignment's dataset rule this is treated as a manual-but-documented step rather than an
automated API pull:
  1. Download the CSV from Kaggle (see docs/data_sources.md for the exact dataset link).
  2. Place it at data/raw/kaggle/<original_filename>.csv
  3. Run this script to validate structure and log the ingestion.

This script does NOT invent or edit data - it only copies/validates what's on disk into the
raw landing convention and logs row counts, matching the "raw copy before transformation"
requirement.
"""
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_RAW_DIR
from ingest_logger import log_extraction

SOURCE = "kaggle_csv"
KAGGLE_RAW_DIR = DATA_RAW_DIR / "kaggle"


def run(csv_path: str) -> None:
    src = Path(csv_path)
    if not src.exists():
        log_extraction(SOURCE, src.name, "FAILED", 0, error_message="file not found")
        print(f"[kaggle] FAILED - file not found: {src}")
        return

    try:
        df = pd.read_csv(src)
        KAGGLE_RAW_DIR.mkdir(parents=True, exist_ok=True)
        dest = KAGGLE_RAW_DIR / src.name
        if src.resolve() != dest.resolve():
            shutil.copy(src, dest)

        status = "SUCCESS" if len(df) else "EMPTY"
        log_extraction(SOURCE, src.name, status, len(df), raw_file=str(dest))
        print(f"[kaggle] {len(df)} rows loaded from {src.name} -> {dest}")
        print(f"[kaggle] columns: {list(df.columns)}")
    except Exception as exc:  # noqa: BLE001
        log_extraction(SOURCE, src.name, "FAILED", 0, error_message=str(exc))
        print(f"[kaggle] FAILED - {exc}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python ingestion/load_kaggle_csv.py <path_to_csv>")
        sys.exit(1)
    run(sys.argv[1])
