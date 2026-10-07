"""
End-to-end manual pipeline runner: ingestion -> staging -> clean -> gold.
This is exactly the sequence of tasks encoded in the Airflow DAG
(orchestration/dags/aqi_pipeline_dag.py) - useful for a quick local run/demo without
spinning up Docker/Airflow.

Run: python scripts/run_pipeline.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingestion"))
sys.path.insert(0, str(ROOT / "etl"))

import fetch_open_meteo
import fetch_openaq
import build_gold
import load_staging
import sync_ingestion_log
import transform_clean


def main():
    print("=" * 70)
    print("STEP 1/5: Extract - OpenAQ pollutant measurements")
    print("=" * 70)
    fetch_openaq.run()

    print("\n" + "=" * 70)
    print("STEP 2/5: Extract - Open-Meteo weather")
    print("=" * 70)
    fetch_open_meteo.run()

    print("\n" + "=" * 70)
    print("STEP 3/5: Load raw -> staging")
    print("=" * 70)
    load_staging.run()

    print("\n" + "=" * 70)
    print("STEP 4/5: Transform staging -> clean (validate, dedupe, normalize)")
    print("=" * 70)
    transform_clean.run()

    print("\n" + "=" * 70)
    print("STEP 5/5: Build gold marts (AQI calculation + aggregates)")
    print("=" * 70)
    build_gold.run()
    sync_ingestion_log.run()

    print("\nPipeline run complete. Launch the dashboard with:")
    print("  streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
