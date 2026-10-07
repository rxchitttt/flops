"""
Extract pollutant measurements from the OpenAQ v3 API for the configured city's stations
and land the raw, untouched API response under data/raw/openaq/<date>/.

Design notes (per assignment "Minimum ingestion expectations"):
- Raw JSON is written before any transformation happens.
- Every attempt (success or failure) is recorded via ingest_logger.log_extraction.
- Designed to be called repeatedly (daily/hourly) by Airflow or run manually.
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_RAW_DIR, OPENAQ_API_KEY, OPENAQ_BASE_URL, OPENAQ_LOCATION_IDS
from ingest_logger import log_extraction

SOURCE = "openaq"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def _get_with_retry(url: str, params: dict, headers: dict) -> requests.Response:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 429:  # rate limited
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last_exc


def fetch_measurements_for_location(location_id: int, date_from: str, date_to: str) -> dict:
    """Fetch one page of hourly measurements for a single OpenAQ location."""
    url = f"{OPENAQ_BASE_URL}/locations/{location_id}/measurements"
    params = {
        "date_from": date_from,
        "date_to": date_to,
        "limit": 1000,
    }
    headers = {"X-API-Key": OPENAQ_API_KEY} if OPENAQ_API_KEY else {}
    resp = _get_with_retry(url, params, headers)
    return resp.json()


def run(date_from: str = None, date_to: str = None) -> None:
    """
    Pull the last 24h of measurements by default. date_from/date_to accept ISO date strings
    for backfill runs (e.g. run("2026-08-01", "2026-08-02")).
    """
    if not OPENAQ_LOCATION_IDS:
        log_extraction(SOURCE, "measurements", "FAILED", 0,
                        error_message="OPENAQ_LOCATION_IDS is empty in .env; "
                                       "run scripts/discover_stations.py first")
        print("No OPENAQ_LOCATION_IDS configured. See scripts/discover_stations.py")
        return

    now = dt.datetime.now(dt.timezone.utc)
    date_to = date_to or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_from = date_from or (now - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    run_date = now.strftime("%Y-%m-%d")
    out_dir = DATA_RAW_DIR / "openaq" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)

    for location_id in OPENAQ_LOCATION_IDS:
        try:
            payload = fetch_measurements_for_location(location_id, date_from, date_to)
            rows = payload.get("results", [])
            out_file = out_dir / f"location_{location_id}_{now.strftime('%H%M%S')}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            status = "SUCCESS" if rows else "EMPTY"
            log_extraction(SOURCE, f"locations/{location_id}/measurements", status,
                            len(rows), raw_file=str(out_file))
            print(f"[openaq] location {location_id}: {len(rows)} rows -> {out_file}")
        except Exception as exc:  # noqa: BLE001 - log and continue with other stations
            log_extraction(SOURCE, f"locations/{location_id}/measurements", "FAILED", 0,
                            error_message=str(exc))
            print(f"[openaq] location {location_id}: FAILED - {exc}")


if __name__ == "__main__":
    run()
