"""
Stage 1 of ETL: read every raw JSON file landed by the ingestion scripts and load it,
close to as-is, into staging.pollutant_measurements / staging.weather_observations.

Idempotent by design: staging is fully truncated and rebuilt from the raw landing zone on
every run, since staging is a disposable intermediate layer, not the final analytical
dataset (the raw files under data/raw/ remain the immutable source of truth).
"""
import json
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from config import CITY_NAME, DATA_RAW_DIR  # noqa: E402

from db_utils import get_engine


def _extract_timestamp(m: dict) -> str | None:
    """OpenAQ v3 measurements nest the timestamp under period.datetimeFrom.utc; older
    response shapes use a flat 'date.utc'. Handle both defensively."""
    period = m.get("period") or {}
    dt_from = period.get("datetimeFrom") or {}
    if isinstance(dt_from, dict) and dt_from.get("utc"):
        return dt_from["utc"]
    date_field = m.get("date")
    if isinstance(date_field, dict):
        return date_field.get("utc")
    return date_field


def _load_openaq_files() -> pd.DataFrame:
    rows = []
    for path in sorted((DATA_RAW_DIR / "openaq").rglob("*.json")):
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        for m in payload.get("results", []):
            param = m.get("parameter") or {}
            coords = m.get("coordinates") or {}
            location = m.get("location") if isinstance(m.get("location"), dict) else {}
            rows.append({
                "source": "openaq",
                "station_id": str(m.get("locationId") or location.get("id") or ""),
                "station_name": location.get("name") or m.get("location_name") or "",
                "city": CITY_NAME,
                "parameter": (param.get("name") or m.get("parameter") or "").lower()
                              if isinstance(param, dict) else str(m.get("parameter", "")).lower(),
                "value": m.get("value"),
                "unit": param.get("units") if isinstance(param, dict) else m.get("unit"),
                "observed_at_raw": _extract_timestamp(m),
                "latitude": coords.get("latitude"),
                "longitude": coords.get("longitude"),
            })
    return pd.DataFrame(rows)


def _load_weather_files() -> pd.DataFrame:
    rows = []
    for path in sorted((DATA_RAW_DIR / "open_meteo").rglob("*.json")):
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        for i, t in enumerate(times):
            rows.append({
                "city": CITY_NAME,
                "observed_at_raw": t,
                "temperature_2m": _at(hourly, "temperature_2m", i),
                "relative_humidity_2m": _at(hourly, "relative_humidity_2m", i),
                "precipitation": _at(hourly, "precipitation", i),
                "wind_speed_10m": _at(hourly, "wind_speed_10m", i),
                "wind_direction_10m": _at(hourly, "wind_direction_10m", i),
            })
    return pd.DataFrame(rows)


def _at(hourly: dict, key: str, i: int):
    values = hourly.get(key, [])
    return values[i] if i < len(values) else None


def run() -> None:
    engine = get_engine()
    pollutants = _load_openaq_files()
    weather = _load_weather_files()

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE staging.pollutant_measurements"))
        conn.execute(text("TRUNCATE TABLE staging.weather_observations"))

        if not pollutants.empty:
            pollutants.to_sql("pollutant_measurements", conn, schema="staging",
                               if_exists="append", index=False)
        if not weather.empty:
            weather.drop_duplicates(subset=["city", "observed_at_raw"]) \
                .to_sql("weather_observations", conn, schema="staging",
                        if_exists="append", index=False)

    print(f"[staging] loaded {len(pollutants)} pollutant rows, {len(weather)} weather rows")


if __name__ == "__main__":
    run()
