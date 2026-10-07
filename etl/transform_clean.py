"""
Stage 2 of ETL: staging -> clean.
- Normalize timestamps to UTC, station names, and pollutant units.
- Deduplicate observations (same station+parameter+timestamp).
- Validate pollutant ranges; anything invalid is written to meta.rejected_records instead
  of being silently dropped.
- Upserts into clean.stations / clean.pollutant_measurements / clean.weather_observations.
"""
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aqi_calculator import is_valid_value
from db_utils import get_engine

# µg/m³ is the CPCB-standard unit for these; ppm-reported CO from some sensors is converted.
PARAMETER_ALIASES = {"pm2.5": "pm25", "pm2_5": "pm25"}


def _normalize_unit(parameter: str, value: float, unit: str) -> tuple[float, str]:
    if value is None:
        return value, unit
    unit = (unit or "").lower()
    if parameter == "co" and unit in ("ppm",):
        # CO: 1 ppm ≈ 1.145 mg/m3 at 25°C (ideal gas approximation, documented assumption)
        return round(value * 1.145, 3), "mg/m3"
    if unit in ("µg/m³", "ug/m3", "µg/m3"):
        return value, "ug/m3"
    if unit in ("mg/m³", "mg/m3"):
        return value, "mg/m3"
    return value, unit or "unknown"


def _insert_rejected(conn, source, station_name, parameter, raw_value, observed_at, reason):
    conn.execute(text("""
        INSERT INTO meta.rejected_records
            (source, station_name, parameter, raw_value, observed_at, rejection_reason)
        VALUES (:source, :station_name, :parameter, :raw_value, :observed_at, :reason)
    """), {"source": source, "station_name": station_name, "parameter": parameter,
           "raw_value": str(raw_value), "observed_at": observed_at, "reason": reason})


def run() -> None:
    engine = get_engine()

    with engine.begin() as conn:
        staged = pd.read_sql("SELECT * FROM staging.pollutant_measurements", conn)
        weather = pd.read_sql("SELECT * FROM staging.weather_observations", conn)

    if staged.empty:
        print("[clean] no staged pollutant rows to process")
    else:
        staged["parameter"] = staged["parameter"].replace(PARAMETER_ALIASES)
        staged["observed_at_utc"] = pd.to_datetime(staged["observed_at_raw"], utc=True, errors="coerce")
        staged["station_id"] = staged["station_id"].fillna("").astype(str)
        staged["station_id"] = staged.apply(
            lambda r: r["station_id"] or f"unknown_{r['station_name']}", axis=1)

        good_rows, rejected_rows = [], []
        for _, r in staged.iterrows():
            if pd.isna(r["observed_at_utc"]) or not r["station_id"] or not r["parameter"]:
                rejected_rows.append((r, "missing_timestamp_or_id"))
                continue
            if r["value"] is None or pd.isna(r["value"]):
                rejected_rows.append((r, "null_value"))
                continue
            if not is_valid_value(r["parameter"], r["value"]):
                rejected_rows.append((r, "out_of_range"))
                continue
            good_rows.append(r)

        good_df = pd.DataFrame(good_rows)
        if not good_df.empty:
            norm = good_df.apply(
                lambda r: _normalize_unit(r["parameter"], r["value"], r["unit"]), axis=1)
            good_df["value"] = [v for v, _ in norm]
            good_df["unit"] = [u for _, u in norm]
            before = len(good_df)
            good_df = good_df.drop_duplicates(subset=["station_id", "parameter", "observed_at_utc"])
            deduped = before - len(good_df)
            if deduped:
                print(f"[clean] removed {deduped} duplicate observations")

        with engine.begin() as conn:
            for r, reason in rejected_rows:
                _insert_rejected(conn, "openaq", r.get("station_name"), r.get("parameter"),
                                  r.get("value"), r.get("observed_at_raw"), reason)

            if not good_df.empty:
                stations = good_df[["station_id", "station_name", "city", "latitude", "longitude"]] \
                    .drop_duplicates(subset=["station_id"])
                for _, s in stations.iterrows():
                    conn.execute(text("""
                        INSERT INTO clean.stations (station_id, station_name, city, latitude, longitude)
                        VALUES (:station_id, :station_name, :city, :latitude, :longitude)
                        ON CONFLICT (station_id) DO UPDATE SET
                            station_name = EXCLUDED.station_name,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude
                    """), s.to_dict())

                for _, m in good_df.iterrows():
                    conn.execute(text("""
                        INSERT INTO clean.pollutant_measurements
                            (station_id, parameter, value, unit, observed_at_utc)
                        VALUES (:station_id, :parameter, :value, :unit, :observed_at_utc)
                        ON CONFLICT (station_id, parameter, observed_at_utc) DO UPDATE SET
                            value = EXCLUDED.value, unit = EXCLUDED.unit
                    """), {"station_id": m["station_id"], "parameter": m["parameter"],
                            "value": float(m["value"]), "unit": m["unit"],
                            "observed_at_utc": m["observed_at_utc"]})

        print(f"[clean] loaded {len(good_df)} valid measurements, "
              f"rejected {len(rejected_rows)} into meta.rejected_records")

    if weather.empty:
        print("[clean] no staged weather rows to process")
    else:
        weather = weather.copy()
        weather["observed_at_utc"] = pd.to_datetime(weather["observed_at_raw"], utc=True, errors="coerce")
        weather = weather.dropna(subset=["observed_at_utc"])
        weather = weather.drop_duplicates(subset=["city", "observed_at_utc"])

        with engine.begin() as conn:
            for _, w in weather.iterrows():
                conn.execute(text("""
                    INSERT INTO clean.weather_observations
                        (city, observed_at_utc, temperature_c, relative_humidity_pct,
                         precipitation_mm, wind_speed_ms, wind_direction_deg)
                    VALUES (:city, :observed_at_utc, :temperature_c, :relative_humidity_pct,
                            :precipitation_mm, :wind_speed_ms, :wind_direction_deg)
                    ON CONFLICT (city, observed_at_utc) DO UPDATE SET
                        temperature_c = EXCLUDED.temperature_c,
                        relative_humidity_pct = EXCLUDED.relative_humidity_pct,
                        precipitation_mm = EXCLUDED.precipitation_mm,
                        wind_speed_ms = EXCLUDED.wind_speed_ms,
                        wind_direction_deg = EXCLUDED.wind_direction_deg
                """), {"city": w["city"], "observed_at_utc": w["observed_at_utc"],
                       "temperature_c": w["temperature_2m"],
                       "relative_humidity_pct": w["relative_humidity_2m"],
                       "precipitation_mm": w["precipitation"],
                       "wind_speed_ms": w["wind_speed_10m"],
                       "wind_direction_deg": w["wind_direction_10m"]})

        print(f"[clean] loaded {len(weather)} weather observations")


if __name__ == "__main__":
    run()
