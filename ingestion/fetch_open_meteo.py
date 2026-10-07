"""
Extract weather variables (temperature, humidity, rainfall, wind) from the free Open-Meteo
API for the configured city and land the raw JSON under data/raw/open_meteo/<date>/.

Uses the archive endpoint for historical backfill and the forecast endpoint's "past_days"
for recent/near-real-time data - both are free, no API key required.
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    CITY_LAT,
    CITY_LON,
    DATA_RAW_DIR,
    OPEN_METEO_ARCHIVE_URL,
    OPEN_METEO_FORECAST_URL,
)
from ingest_logger import log_extraction

SOURCE = "open_meteo"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

HOURLY_VARS = ",".join([
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "wind_speed_10m", "wind_direction_10m",
])


def _get_with_retry(url: str, params: dict) -> requests.Response:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last_exc


def run(date_from: str = None, date_to: str = None, backfill: bool = False) -> None:
    """
    Default: pull the last 2 days of hourly weather via the forecast endpoint's past_days
    param. Pass backfill=True with date_from/date_to (YYYY-MM-DD) to use the archive
    endpoint for historical data (e.g. matching a Kaggle dataset's date range).
    """
    now = dt.datetime.now(dt.timezone.utc)
    run_date = now.strftime("%Y-%m-%d")
    out_dir = DATA_RAW_DIR / "open_meteo" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)

    if backfill:
        if not (date_from and date_to):
            raise ValueError("backfill=True requires date_from and date_to (YYYY-MM-DD)")
        url = OPEN_METEO_ARCHIVE_URL
        params = {
            "latitude": CITY_LAT, "longitude": CITY_LON,
            "start_date": date_from, "end_date": date_to,
            "hourly": HOURLY_VARS, "timezone": "UTC",
        }
        endpoint_label = f"archive/{date_from}_{date_to}"
    else:
        url = OPEN_METEO_FORECAST_URL
        params = {
            "latitude": CITY_LAT, "longitude": CITY_LON,
            "past_days": 2, "forecast_days": 1,
            "hourly": HOURLY_VARS, "timezone": "UTC",
        }
        endpoint_label = "forecast/past_days"

    try:
        resp = _get_with_retry(url, params)
        payload = resp.json()
        times = payload.get("hourly", {}).get("time", [])
        out_file = out_dir / f"weather_{now.strftime('%H%M%S')}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        status = "SUCCESS" if times else "EMPTY"
        log_extraction(SOURCE, endpoint_label, status, len(times), raw_file=str(out_file))
        print(f"[open_meteo] {len(times)} hourly rows -> {out_file}")
    except Exception as exc:  # noqa: BLE001
        log_extraction(SOURCE, endpoint_label, "FAILED", 0, error_message=str(exc))
        print(f"[open_meteo] FAILED - {exc}")


if __name__ == "__main__":
    run()
