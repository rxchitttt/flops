# Project Report Outline (target: 8–10 pages)

Fill each section in below; this skeleton maps directly to the rubric ("Suggested Mark
Distribution", section 9 of the assignment).

## 1. Introduction & Problem Understanding (~1 page)
- Project objective, motivation (air quality in Bengaluru), scope of Part 1 vs. Part 2.
- Chosen city/stations and why.

## 2. Data Sources (~1 page)
- Table of sources used (OpenAQ, Open-Meteo, Kaggle fallback), access method, license.
- Reference: `docs/data_sources.md`.

## 3. Architecture & Design (~1.5 pages)
- Architecture diagram (from `docs/architecture_diagram.md`) with explanation of each layer.
- Why PostgreSQL, why Airflow (or chosen equivalent), why Streamlit.
- Design decisions and tradeoffs (e.g., CPCB AQI standard, hourly vs. 24-hr averaging
  assumption, station scope limited to ~25km radius).

## 4. Data Ingestion (~1 page)
- How each ingestion script works, scheduling via Airflow DAG.
- Error handling & retry strategy; extraction metadata logging (`meta.ingestion_log`).
- Screenshot: a successful DAG run in the Airflow UI.

## 5. ETL, Validation & Storage (~1.5–2 pages)
- Staging → clean → gold pipeline walkthrough.
- Validation rules applied (see `docs/data_dictionary.md`) and what gets rejected.
- Screenshot: `meta.rejected_records` sample rows.
- Schema diagram / table list, with row counts from a real run.

## 6. Visualization & Interpretation (~1.5 pages)
- Screenshot each of the 5 dashboard views.
- Key insights observed in the data (e.g., which pollutant dominates, hourly/monthly
  patterns, weather correlation) — write these AFTER running the real pipeline; do not
  fabricate numbers.

## 7. Data Dictionary & Validation Rules (~0.5 page, or appendix)
- Summarized table; full detail in `docs/data_dictionary.md`.

## 8. Execution Evidence (~0.5–1 page)
- Screenshots: Docker Compose services running, Airflow DAG graph view, populated Postgres
  tables (`\dt` + row counts), Streamlit dashboard live.

## 9. Limitations (Part 1) (~0.5 page)
- Known limitations (station coverage, hourly-vs-24hr AQI approximation, no CPCB API).

## 10. Part 2 — Model Development & Evaluation (~1.5 pages)
- Feature pipeline: lag (1/2/3-day) and rolling (3/7-day mean, 3-day std) AQI features,
  plus same-day pollutant/weather features (`ml/build_features.py`).
- Chronological 70/15/15 split rationale (no leakage from future to past).
- Regression models compared (linear regression, random forest, gradient boosting) with
  RMSE/MAE; classification models compared (logistic regression, random forest, gradient
  boosting) with precision/recall/F1 — report actual numbers from a real `ml/train.py` run.
- Which model won each task and why (test-set metric comparison table).

## 11. Part 2 — MLflow, Registry, Deployment, Docker (~1 page)
- Screenshot: MLflow UI showing tracked runs/metrics for both tasks.
- Model registry: registered model names/versions (`aqi_next_day_regressor`,
  `aqi_next_day_classifier`).
- FastAPI endpoints and a screenshot of a real `/predict` response.
- Screenshot: `docker build`/`docker run` (or `docker compose --profile serving up`)
  succeeding, and a curl/Postman call against the containerized service.

## 12. Part 2 — Monitoring & Retraining (~0.5–1 page)
- Screenshot: `meta.model_monitoring` rows from a real `monitoring/monitor.py` run
  (missing data, feature drift, forecast error statuses).
- Retraining criteria and lifecycle — summarize from `docs/model_lifecycle.md`.

## 13. References
- OpenAQ docs, Open-Meteo docs, Kaggle dataset link, CPCB AQI standard reference, MLflow
  docs, FastAPI docs.

---
**Reminder**: Populate every screenshot/number in this report from an actual successful
pipeline run — do not pre-fill placeholder statistics as if they were real results.
