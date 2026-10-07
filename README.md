# Air Quality Index (AQI) Analysis and Prediction

Data Engineering & MLOps individual project for **Bengaluru** air quality.
- **Part 1**: full data pipeline (ingestion → ETL → storage → dashboard) using OpenAQ
  (pollutants), Open-Meteo (weather), and a Kaggle CSV as historical fallback.
- **Part 2**: MLOps extension — next-day AQI forecasting (regression + classification),
  MLflow tracking/registry, FastAPI + Docker serving, monitoring, retraining policy.

See `docs/` for the architecture diagram, data dictionary, data sources, report outline,
and model lifecycle doc.

## Project layout
```
ingestion/          Python extractors (OpenAQ, Open-Meteo, Kaggle CSV) + shared config/logging
etl/                staging -> clean -> gold transformation scripts + AQI calculator
orchestration/dags/ Airflow DAG (aqi_pipeline_dag.py)
db/                 PostgreSQL schema (schema.sql) + multi-db init script
dashboard/          Streamlit app (5 Part 1 views + Part 2 forecast/monitoring section)
docs/               architecture diagram, data dictionary, data sources, report outline, model lifecycle
scripts/            discover_stations.py (find OpenAQ station IDs), run_pipeline.py (manual E2E run)
data/raw/           raw landing zone (gitignored; created on first run)
logs/               ingestion_log.csv, rejected records

ml/                 Part 2: build_features.py (lag/rolling features), train.py (MLflow-tracked training)
serving/            Part 2: FastAPI inference app + Dockerfile
monitoring/         Part 2: monitor.py (missing data, drift, forecast error)
models/             Part 2: joblib model artifacts (gitignored, produced by ml/train.py)
mlruns/             Part 2: local MLflow tracking store (gitignored, produced by ml/train.py)
```

## 1. Prerequisites
- Docker Desktop (for Postgres + Airflow)
- Python 3.11+ (for running scripts locally / the dashboard)
- A free OpenAQ API key: https://explore.openaq.org/register

## 2. Setup
```bash
cp .env.example .env
# edit .env: set OPENAQ_API_KEY, and confirm CITY_NAME/CITY_LAT/CITY_LON (defaults to Bengaluru)

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Find OpenAQ station IDs near your city and paste them into .env as OPENAQ_LOCATION_IDS
python scripts/discover_stations.py
```

## 3. Start the infrastructure (Postgres + Airflow)
```bash
docker compose up -d postgres        # start the warehouse first
# wait ~10s for healthcheck, then:
docker compose up -d airflow         # Airflow UI: http://localhost:8080 (user/pass: admin/admin)
```
The `db/schema.sql` and `db/init_multi_db.sh` are applied automatically on Postgres's first
boot (via `docker-entrypoint-initdb.d`). If you change `schema.sql` after the volume already
exists, re-apply manually:
```bash
docker exec -i aqi_postgres psql -U aqi_user -d aqi_dw < db/schema.sql
```

## 4. Run the pipeline
**Option A — via Airflow (scheduled/repeatable, matches the assignment's suggested design):**
Open http://localhost:8080, unpause the `aqi_pipeline` DAG, and trigger a run (▶). It runs
daily on its own after that.

**Option B — manual one-shot run (fastest way to demo end-to-end locally):**
```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)   # or use python-dotenv, already wired into the scripts
python scripts/run_pipeline.py
```
This runs: extract OpenAQ → extract Open-Meteo → load staging → transform clean → build gold
→ sync ingestion log — the same steps the DAG runs.

**Fallback/backfill with the Kaggle dataset** (see `docs/data_sources.md` for the download
link):
```bash
python ingestion/load_kaggle_csv.py data/raw/kaggle/<downloaded_file>.csv
```

## 5. View the dashboard
```bash
streamlit run dashboard/app.py
```
Open http://localhost:8501. Five views: AQI trend, pollutant contribution, station
comparison, hourly/monthly patterns, weather impact — plus a pipeline-health panel reading
`meta.ingestion_log`.

## 6. Verify data landed correctly
```bash
docker exec -it aqi_postgres psql -U aqi_user -d aqi_dw -c "\dt gold.*"
docker exec -it aqi_postgres psql -U aqi_user -d aqi_dw -c "SELECT * FROM gold.city_daily_aqi LIMIT 5;"
docker exec -it aqi_postgres psql -U aqi_user -d aqi_dw -c "SELECT * FROM meta.rejected_records LIMIT 5;"
```

## 7. Stopping / resetting
```bash
docker compose down          # stop containers, keep data volume
docker compose down -v       # stop and wipe Postgres/Airflow data (full reset)
```

## Notes
- All credentials/config are read from `.env` (never committed — see `.gitignore`).
- Raw files under `data/raw/` are never edited manually; only the ingestion scripts write
  there, and only the ETL scripts read from them.

---

## Part 2 — MLOps: Forecasting, Serving, Monitoring

Requires Part 1's gold layer to be populated first (`gold.station_daily_aqi` needs at
least ~15 days of data for a meaningful chronological train/val/test split; 40+ days is
better and closer to a real classifier evaluation).

### 8. Start MLflow, build features, and train
```bash
docker compose up -d mlflow    # MLflow tracking server + registry -> http://localhost:5001
                                # (mapped from container port 5000; macOS AirPlay Receiver
                                # usually already owns host port 5000, so don't reuse it)
```
In `.env`, set `MLFLOW_TRACKING_URI=http://localhost:5001` (or leave it blank to use a
local `./mlruns` file store instead — no server needed, but less convenient for the UI).
```bash
source .venv/bin/activate
python ml/build_features.py    # gold.station_daily_aqi -> gold.ml_features_daily
python ml/train.py             # trains + compares 3 models per task, logs every run to
                                # MLflow, registers the best of each, saves joblib copies
                                # to models/ for FastAPI to load
```
Open http://localhost:5001 to see tracked experiments/runs/metrics and the two registered
models (`aqi_next_day_regressor`, `aqi_next_day_classifier`) in the Model Registry.

### 9. Serve predictions (FastAPI + Docker)
Local (no Docker):
```bash
uvicorn serving.app:app --reload --port 8000
```
Or containerized, alongside the rest of the stack:
```bash
docker compose --profile serving up -d --build fastapi
```
Endpoints: `GET /health`, `GET /stations`, `POST /predict {"station_id": "..."}`,
`POST /reload_models` (after retraining, without rebuilding the container).

### 10. Monitor
```bash
python monitoring/monitor.py
```
Checks missing data, feature drift vs. the training baseline, and backfills/measures
forecast error for past predictions — writes results to `meta.model_monitoring`, visible
in the dashboard's "Part 2 — AQI Forecast & Model Monitoring" section.

### 11. Retraining
See `docs/model_lifecycle.md` for the concrete retraining criteria (schedule, forecast
error degradation, feature drift, data-quality regression) and the promote/rollback
procedure.
