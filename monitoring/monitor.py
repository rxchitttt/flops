"""
Part 2 - monitoring job.
Run this on a schedule (daily, e.g. as an extra Airflow task or cron) after the Part 1
pipeline and any served predictions. Writes every check to meta.model_monitoring so the
dashboard/report can show pipeline + model health over time. Also backfills actual AQI
values into meta.predictions_log once they become known, to compute real forecast error.

Checks implemented (per assignment: "Monitor missing data, feature drift, and forecasting
error"):
1. missing_data   - gaps in the expected daily sequence per station
2. feature_drift  - current feature distributions vs. the training baseline (z-score of
                     mean shift; a lightweight, dependency-free proxy for population drift)
3. forecast_error - MAE between predicted_aqi and actual_aqi for predictions whose
                     target_date has now passed and has real data

Run: python monitoring/monitor.py
"""
import datetime as dt
import sys
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "ingestion"))
sys.path.insert(0, str(ROOT / "ml"))
from aqi_calculator import category_for_aqi  # noqa: E402
from build_features import FEATURE_COLUMNS  # noqa: E402
from config import MODEL_REGISTRY_DIR  # noqa: E402
from db_utils import get_engine  # noqa: E402

# Thresholds - documented here so they can be tuned/justified in the report
MISSING_DATA_WARN_DAYS = 1     # >=1 missing day in the last week -> WARN
MISSING_DATA_ALERT_DAYS = 3    # >=3 missing days -> ALERT
DRIFT_ZSCORE_WARN = 1.5        # |current_mean - baseline_mean| / baseline_std
DRIFT_ZSCORE_ALERT = 3.0
FORECAST_MAE_WARN = 40         # AQI points
FORECAST_MAE_ALERT = 70


def _log(conn, check_type, metric_name, value, status, details=""):
    conn.execute(text("""
        INSERT INTO meta.model_monitoring (check_type, metric_name, metric_value, status, details)
        VALUES (:check_type, :metric_name, :metric_value, :status, :details)
    """), {"check_type": check_type, "metric_name": metric_name,
           "metric_value": float(value) if value is not None else None,
           "status": status, "details": details})


def check_missing_data(engine) -> None:
    with engine.begin() as conn:
        daily = pd.read_sql(
            "SELECT station_id, station_name, observation_date FROM gold.station_daily_aqi", conn)

        if daily.empty:
            _log(conn, "missing_data", "no_data", 0, "ALERT", "gold.station_daily_aqi is empty")
            return

        for station_id, group in daily.groupby("station_id"):
            dates = pd.to_datetime(group["observation_date"]).sort_values()
            expected = pd.date_range(dates.min(), dates.max(), freq="D")
            missing = expected.difference(dates)
            recent_missing = [d for d in missing if d >= expected.max() - pd.Timedelta(days=7)]
            n_missing = len(recent_missing)
            status = "OK"
            if n_missing >= MISSING_DATA_ALERT_DAYS:
                status = "ALERT"
            elif n_missing >= MISSING_DATA_WARN_DAYS:
                status = "WARN"
            _log(conn, "missing_data", f"missing_days_last_7_{station_id}", n_missing, status,
                 f"station={group['station_name'].iloc[0]}, missing_dates="
                 f"{[str(d.date()) for d in recent_missing]}")
            print(f"[monitor][missing_data] station={station_id} missing_last_7={n_missing} -> {status}")


def check_feature_drift(engine) -> None:
    baseline_path = MODEL_REGISTRY_DIR / "feature_baseline.joblib"
    if not baseline_path.exists():
        print("[monitor][feature_drift] no baseline yet - run ml/train.py first")
        return
    baseline = joblib.load(baseline_path)

    with engine.begin() as conn:
        recent = pd.read_sql("""
            SELECT * FROM gold.ml_features_daily
            WHERE observation_date >= (SELECT MAX(observation_date) FROM gold.ml_features_daily) - INTERVAL '7 days'
        """, conn)

        if recent.empty:
            return

        for col in FEATURE_COLUMNS:
            if col not in baseline or baseline[col]["std"] in (0, None) or pd.isna(baseline[col]["std"]):
                continue
            current_mean = recent[col].mean()
            if pd.isna(current_mean):
                continue
            baseline_mean, baseline_std = baseline[col]["mean"], baseline[col]["std"]
            z = abs(current_mean - baseline_mean) / baseline_std
            status = "ALERT" if z >= DRIFT_ZSCORE_ALERT else ("WARN" if z >= DRIFT_ZSCORE_WARN else "OK")
            _log(conn, "feature_drift", col, z, status,
                 f"current_mean={current_mean:.2f}, baseline_mean={baseline_mean:.2f}, "
                 f"baseline_std={baseline_std:.2f}")
            if status != "OK":
                print(f"[monitor][feature_drift] {col}: z={z:.2f} -> {status}")


def check_forecast_error(engine) -> None:
    with engine.begin() as conn:
        preds = pd.read_sql("""
            SELECT * FROM meta.predictions_log
            WHERE target_date <= CURRENT_DATE AND actual_aqi IS NULL
        """, conn)

        if preds.empty:
            print("[monitor][forecast_error] no unresolved predictions to backfill")
            return

        actuals = pd.read_sql(
            "SELECT station_id, observation_date, avg_aqi FROM gold.station_daily_aqi", conn)
        # station_daily_aqi doesn't store a category column; derive it from avg_aqi here.
        actuals["aqi_category"] = actuals["avg_aqi"].apply(
            lambda v: category_for_aqi(v) if pd.notna(v) else None)

        merged = preds.merge(actuals, left_on=["station_id", "target_date"],
                              right_on=["station_id", "observation_date"], how="inner")
        if merged.empty:
            print("[monitor][forecast_error] actuals not yet available for pending predictions")
            return

        for _, row in merged.iterrows():
            conn.execute(text("""
                UPDATE meta.predictions_log SET actual_aqi = :actual_aqi, actual_category = :actual_category
                WHERE id = :id
            """), {"actual_aqi": row["avg_aqi"], "actual_category": row["aqi_category"], "id": row["id"]})

        mae = (merged["predicted_aqi"] - merged["avg_aqi"]).abs().mean()
        status = "ALERT" if mae >= FORECAST_MAE_ALERT else ("WARN" if mae >= FORECAST_MAE_WARN else "OK")
        _log(conn, "forecast_error", "mae_aqi", mae, status,
             f"resolved {len(merged)} predictions")
        print(f"[monitor][forecast_error] resolved {len(merged)} predictions, MAE={mae:.1f} -> {status}")


def run():
    engine = get_engine()
    check_missing_data(engine)
    check_feature_drift(engine)
    check_forecast_error(engine)
    print(f"[monitor] run complete at {dt.datetime.now(dt.timezone.utc).isoformat()}")


if __name__ == "__main__":
    run()
