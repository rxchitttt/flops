"""
Part 2 - reusable feature pipeline.
Reads gold.station_daily_aqi (built by Part 1's build_gold.py), adds lag/rolling
features and next-day prediction targets, and writes gold.ml_features_daily.

Designed to be re-run any time new daily data lands (idempotent full rebuild per
station) - the same script is used to build training features and to build the
latest feature row used for a live prediction request.
"""
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "etl"))
from aqi_calculator import category_for_aqi  # noqa: E402
from db_utils import get_engine  # noqa: E402

FEATURE_COLUMNS = [
    "avg_pm25", "avg_pm10", "avg_no2", "avg_so2", "avg_co", "avg_o3",
    "avg_temperature_c", "avg_humidity_pct", "total_precipitation_mm", "avg_wind_speed_ms",
    "aqi_lag1", "aqi_lag2", "aqi_lag3", "aqi_roll_mean_3", "aqi_roll_mean_7",
    "aqi_roll_std_3", "day_of_week", "month",
]


def build_features(df_station: pd.DataFrame) -> pd.DataFrame:
    """df_station: rows for ONE station, sorted by observation_date ascending."""
    df = df_station.sort_values("observation_date").reset_index(drop=True)
    df["aqi_lag1"] = df["avg_aqi"].shift(1)
    df["aqi_lag2"] = df["avg_aqi"].shift(2)
    df["aqi_lag3"] = df["avg_aqi"].shift(3)
    df["aqi_roll_mean_3"] = df["avg_aqi"].shift(1).rolling(window=3, min_periods=1).mean()
    df["aqi_roll_mean_7"] = df["avg_aqi"].shift(1).rolling(window=7, min_periods=1).mean()
    df["aqi_roll_std_3"] = df["avg_aqi"].shift(1).rolling(window=3, min_periods=1).std()
    df["day_of_week"] = pd.to_datetime(df["observation_date"]).dt.dayofweek
    df["month"] = pd.to_datetime(df["observation_date"]).dt.month
    # Targets: TOMORROW's AQI/category, predicted using only data up to and including today
    df["target_next_day_aqi"] = df["avg_aqi"].shift(-1)
    df["target_next_day_category"] = df["target_next_day_aqi"].apply(
        lambda v: category_for_aqi(v) if pd.notna(v) else None)
    return df


def run() -> pd.DataFrame:
    engine = get_engine()
    with engine.begin() as conn:
        daily = pd.read_sql("SELECT * FROM gold.station_daily_aqi ORDER BY station_id, observation_date", conn)

    if daily.empty:
        print("[features] gold.station_daily_aqi is empty - run Part 1's pipeline first")
        return pd.DataFrame()

    all_features = []
    for station_id, group in daily.groupby("station_id"):
        all_features.append(build_features(group))
    features = pd.concat(all_features, ignore_index=True)

    keep_cols = ["station_id", "station_name", "city", "observation_date", "avg_aqi",
                 *FEATURE_COLUMNS, "target_next_day_aqi", "target_next_day_category"]
    features = features[keep_cols]

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE gold.ml_features_daily"))
        features.to_sql("ml_features_daily", conn, schema="gold", if_exists="append", index=False)

    print(f"[features] wrote {len(features)} rows to gold.ml_features_daily "
          f"({features['target_next_day_aqi'].notna().sum()} with a known next-day target)")
    return features


if __name__ == "__main__":
    run()
