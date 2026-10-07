"""
Airflow DAG: schedules the daily AQI/weather ingestion and ETL pipeline.

Dependency graph:
    fetch_openaq  ---\
                       >-- load_staging -> transform_clean -> build_gold -> sync_ingestion_log
    fetch_open_meteo -/

Each extraction task is independent and allowed to fail without blocking the other source
(load_staging processes whatever raw files exist); retries and logging are handled inside
each script via ingest_logger.log_extraction.
"""
from __future__ import annotations

import datetime as dt
import sys

sys.path.insert(0, "/opt/airflow/project/ingestion")
sys.path.insert(0, "/opt/airflow/project/etl")

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "aqi_project",
    "retries": 2,
    "retry_delay": dt.timedelta(minutes=5),
}

with DAG(
    dag_id="aqi_pipeline",
    description="Ingest OpenAQ + Open-Meteo data and build the AQI analytics warehouse",
    default_args=default_args,
    schedule="@daily",
    start_date=dt.datetime(2026, 8, 1),
    catchup=False,
    tags=["aqi", "part1"],
) as dag:

    def _fetch_openaq():
        import fetch_openaq
        fetch_openaq.run()

    def _fetch_open_meteo():
        import fetch_open_meteo
        fetch_open_meteo.run()

    def _load_staging():
        import load_staging
        load_staging.run()

    def _transform_clean():
        import transform_clean
        transform_clean.run()

    def _build_gold():
        import build_gold
        build_gold.run()

    def _sync_ingestion_log():
        import sync_ingestion_log
        sync_ingestion_log.run()

    fetch_openaq_task = PythonOperator(task_id="fetch_openaq", python_callable=_fetch_openaq)
    fetch_weather_task = PythonOperator(task_id="fetch_open_meteo", python_callable=_fetch_open_meteo)
    load_staging_task = PythonOperator(task_id="load_staging", python_callable=_load_staging)
    transform_clean_task = PythonOperator(task_id="transform_clean", python_callable=_transform_clean)
    build_gold_task = PythonOperator(task_id="build_gold", python_callable=_build_gold)
    sync_log_task = PythonOperator(task_id="sync_ingestion_log", python_callable=_sync_ingestion_log)

    [fetch_openaq_task, fetch_weather_task] >> load_staging_task
    load_staging_task >> transform_clean_task >> build_gold_task >> sync_log_task
