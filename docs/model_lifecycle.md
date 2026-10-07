# Model Lifecycle & Retraining Criteria (Part 2)

## Lifecycle stages
1. **Feature build** — `ml/build_features.py` reads `gold.station_daily_aqi` and writes
   `gold.ml_features_daily` (lag/rolling features + next-day targets). Re-run any time new
   daily data lands.
2. **Train** — `ml/train.py` does a chronological 70/15/15 train/val/test split, trains
   3 candidate models per task (regression: linear/random forest/gradient boosting;
   classification: logistic regression/random forest/gradient boosting), logs every run to
   MLflow, and registers the best-per-task model under `aqi_next_day_regressor` /
   `aqi_next_day_classifier` in the MLflow Model Registry. A joblib copy is also written to
   `models/` so FastAPI can serve without a live MLflow server.
3. **Serve** — `serving/app.py` (FastAPI, containerized via `serving/Dockerfile`) loads the
   joblib models, builds the latest feature row for a requested station, predicts, and logs
   the prediction to `meta.predictions_log`.
4. **Monitor** — `monitoring/monitor.py` checks missing data, feature drift (z-score vs.
   the training baseline), and forecast error (once real next-day AQI is known), writing
   results to `meta.model_monitoring`.
5. **Retrain** — triggered manually or on a schedule when a retraining criterion below is
   met; re-runs steps 1–3.

## Retraining criteria
Retrain (re-run `ml/build_features.py` then `ml/train.py`) when **any** of the following
is true:
- **Scheduled**: at least 14 new labeled days have accumulated since the last training run
  (keeps the model current without retraining on noise from single-day fluctuations).
- **Forecast error degradation**: `meta.model_monitoring` shows `forecast_error` /
  `mae_aqi` at `WARN` (MAE ≥ 40 AQI points) for 3+ consecutive monitoring runs, or a single
  `ALERT` (MAE ≥ 70).
- **Feature drift**: `feature_drift` status is `ALERT` (z-score ≥ 3.0) on any feature for
  2+ consecutive runs — the input distribution has shifted enough that the trained model's
  assumptions may no longer hold (e.g. a new pollution source, sensor recalibration, or a
  seasonal regime change).
- **Data quality regression**: `missing_data` is `ALERT` (≥3 missing days in the last
  week) — don't retrain on a gappy window; instead backfill first, then retrain once data
  is complete again.

## Promotion / rollback
- A newly trained model is registered in MLflow but not automatically put into production;
  compare its `test_rmse`/`test_f1` (in the MLflow UI or `mlflow.search_runs`) against the
  currently served model's metrics (stored in the joblib artifact's paired MLflow run).
- Promote by copying the new joblib artifacts over `models/aqi_regressor.joblib` etc. and
  calling `POST /reload_models` on the FastAPI service — no container rebuild needed.
- Rollback: MLflow keeps every prior run + registered model version; restore the previous
  version's artifacts to `models/` and reload.

## What's intentionally manual in this project
Given the individual-project scope, retraining is **not** auto-triggered by the monitoring
job — `monitoring/monitor.py` flags the need (via `meta.model_monitoring` statuses) and a
person (or a future Airflow task) decides to run `ml/train.py`. This is documented here as
the current lifecycle policy, not a missing feature.
