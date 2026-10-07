"""Sync the local logs/ingestion_log.csv (written by ingestion scripts) into
meta.ingestion_log so it's queryable alongside the rest of the warehouse and visible on
the dashboard's pipeline-health view."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from config import INGESTION_LOG_CSV  # noqa: E402

from db_utils import get_engine


def run() -> None:
    if not Path(INGESTION_LOG_CSV).exists():
        print("[ingestion_log] no log file yet")
        return
    df = pd.read_csv(INGESTION_LOG_CSV)
    engine = get_engine()
    with engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text("TRUNCATE TABLE meta.ingestion_log"))
        df.to_sql("ingestion_log", conn, schema="meta", if_exists="append", index=False)
    print(f"[ingestion_log] synced {len(df)} rows")


if __name__ == "__main__":
    run()
