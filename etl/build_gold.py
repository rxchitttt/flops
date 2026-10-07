"""
Stage 3 of ETL: clean -> gold.
- Pivot pollutant measurements to station-hour grain and join with weather by station city
  and nearest hour.
- Compute per-pollutant sub-indices and overall AQI + category + dominant pollutant.
- Aggregate to station-day and city-day grains, and build the pollutant contribution mart.
"""
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aqi_calculator import BREAKPOINTS, category_for_aqi, overall_aqi, sub_index
from db_utils import get_engine

POLLUTANTS = list(BREAKPOINTS.keys())


def run() -> None:
    engine = get_engine()

    with engine.begin() as conn:
        measurements = pd.read_sql("""
            SELECT m.station_id, s.station_name, s.city, m.parameter, m.value, m.observed_at_utc
            FROM clean.pollutant_measurements m
            JOIN clean.stations s ON s.station_id = m.station_id
        """, conn)
        weather = pd.read_sql("SELECT * FROM clean.weather_observations", conn)

    if measurements.empty:
        print("[gold] no clean measurements available yet - skipping gold build")
        return

    # Round to the hour so pollutant readings and weather can be joined on a common key,
    # even though the two sources don't share identical timestamps.
    measurements["hour_utc"] = measurements["observed_at_utc"].dt.floor("h")
    pivot = measurements.pivot_table(
        index=["station_id", "station_name", "city", "hour_utc"],
        columns="parameter", values="value", aggfunc="mean",
    ).reset_index()
    for p in POLLUTANTS:
        if p not in pivot.columns:
            pivot[p] = None

    if not weather.empty:
        weather = weather.copy()
        weather["hour_utc"] = weather["observed_at_utc"].dt.floor("h")
        weather_hourly = weather.groupby(["city", "hour_utc"]).agg(
            temperature_c=("temperature_c", "mean"),
            relative_humidity_pct=("relative_humidity_pct", "mean"),
            precipitation_mm=("precipitation_mm", "sum"),
            wind_speed_ms=("wind_speed_ms", "mean"),
        ).reset_index()
        pivot = pivot.merge(weather_hourly, on=["city", "hour_utc"], how="left")
    else:
        for col in ("temperature_c", "relative_humidity_pct", "precipitation_mm", "wind_speed_ms"):
            pivot[col] = None

    aqi_values, categories, dominants = [], [], []
    for _, row in pivot.iterrows():
        subs = {p: sub_index(p, row.get(p)) for p in POLLUTANTS}
        aqi, dominant = overall_aqi(subs)
        aqi_values.append(round(aqi) if aqi is not None else None)
        categories.append(category_for_aqi(aqi) if aqi is not None else None)
        dominants.append(dominant)
    pivot["aqi"] = aqi_values
    pivot["aqi_category"] = categories
    pivot["dominant_pollutant"] = dominants
    pivot = pivot.rename(columns={"hour_utc": "observed_at_utc"})

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE gold.station_hourly_aqi"))
        pivot[["station_id", "station_name", "city", "observed_at_utc", *POLLUTANTS,
               "aqi", "aqi_category", "dominant_pollutant", "temperature_c",
               "relative_humidity_pct", "precipitation_mm", "wind_speed_ms"]] \
            .to_sql("station_hourly_aqi", conn, schema="gold", if_exists="append", index=False)

    print(f"[gold] station_hourly_aqi: {len(pivot)} rows")
    _build_daily_and_contribution_marts(engine, pivot)


def _build_daily_and_contribution_marts(engine, hourly: pd.DataFrame) -> None:
    hourly = hourly.copy()
    hourly["observation_date"] = hourly["observed_at_utc"].dt.date

    station_daily = hourly.groupby(["station_id", "station_name", "city", "observation_date"]).agg(
        avg_pm25=("pm25", "mean"), avg_pm10=("pm10", "mean"), avg_no2=("no2", "mean"),
        avg_so2=("so2", "mean"), avg_co=("co", "mean"), avg_o3=("o3", "mean"),
        avg_aqi=("aqi", "mean"), max_aqi=("aqi", "max"),
        avg_temperature_c=("temperature_c", "mean"),
        avg_humidity_pct=("relative_humidity_pct", "mean"),
        total_precipitation_mm=("precipitation_mm", "sum"),
        avg_wind_speed_ms=("wind_speed_ms", "mean"),
    ).reset_index()
    # dominant pollutant of the day = whichever pollutant had the highest single sub-index
    # Use skipna-safe idxmax: drop groups where all AQI values are NaN to avoid KeyError
    _hourly_with_aqi = hourly.dropna(subset=["aqi"])
    if not _hourly_with_aqi.empty:
        dom_idx = _hourly_with_aqi.groupby(["station_id", "observation_date"])["aqi"].idxmax()
        dom = _hourly_with_aqi.loc[dom_idx, ["station_id", "observation_date", "dominant_pollutant"]]
    else:
        dom = pd.DataFrame(columns=["station_id", "observation_date", "dominant_pollutant"])
    station_daily = station_daily.merge(dom, on=["station_id", "observation_date"], how="left")

    city_daily = hourly.groupby(["city", "observation_date"]).agg(
        avg_aqi=("aqi", "mean"), max_aqi=("aqi", "max"),
        station_count=("station_id", "nunique"),
    ).reset_index()
    if not _hourly_with_aqi.empty:
        dom_city_idx = _hourly_with_aqi.groupby(["city", "observation_date"])["aqi"].idxmax()
        dom_city = _hourly_with_aqi.loc[dom_city_idx, ["city", "observation_date", "dominant_pollutant"]]
    else:
        dom_city = pd.DataFrame(columns=["city", "observation_date", "dominant_pollutant"])
    city_daily = city_daily.merge(dom_city, on=["city", "observation_date"], how="left")

    contrib_rows = []
    for p in POLLUTANTS:
        sub_col = f"_sub_{p}"
        hourly[sub_col] = hourly.apply(lambda r: sub_index(p, r.get(p)), axis=1)
    sub_cols = [f"_sub_{p}" for p in POLLUTANTS]
    daily_city_subs = hourly.groupby(["city", "observation_date"])[sub_cols].mean().reset_index()
    for _, row in daily_city_subs.iterrows():
        total = sum(row[c] for c in sub_cols if pd.notna(row[c]))
        for p in POLLUTANTS:
            val = row[f"_sub_{p}"]
            if pd.isna(val):
                continue
            contrib_rows.append({
                "city": row["city"], "observation_date": row["observation_date"], "parameter": p,
                "avg_sub_index": round(val, 1),
                "contribution_pct": round(100 * val / total, 1) if total else None,
            })
    contribution = pd.DataFrame(contrib_rows)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE gold.station_daily_aqi"))
        conn.execute(text("TRUNCATE TABLE gold.city_daily_aqi"))
        conn.execute(text("TRUNCATE TABLE gold.pollutant_contribution_daily"))
        station_daily.to_sql("station_daily_aqi", conn, schema="gold", if_exists="append", index=False)
        city_daily.to_sql("city_daily_aqi", conn, schema="gold", if_exists="append", index=False)
        if not contribution.empty:
            contribution.to_sql("pollutant_contribution_daily", conn, schema="gold",
                                 if_exists="append", index=False)

    print(f"[gold] station_daily_aqi: {len(station_daily)} rows | "
          f"city_daily_aqi: {len(city_daily)} rows | "
          f"pollutant_contribution_daily: {len(contribution)} rows")


if __name__ == "__main__":
    run()
