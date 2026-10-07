# Architecture Diagram

Render this with any Mermaid-compatible viewer (VS Code Mermaid extension, mermaid.live,
or GitHub's native Mermaid rendering) and export a PNG for the report/screenshots folder.

```mermaid
flowchart TD
    subgraph SRC["Source Layer"]
        A1["OpenAQ API<br/>(pollutants)"]
        A2["Open-Meteo API<br/>(weather)"]
        A3["Kaggle CSV<br/>(historical fallback)"]
    end

    subgraph ING["Ingestion Layer (Python)"]
        B1["fetch_openaq.py<br/>requests + retry/backoff"]
        B2["fetch_open_meteo.py"]
        B3["load_kaggle_csv.py<br/>pandas"]
    end

    subgraph RAW["Raw / Landing Zone"]
        C1["data/raw/openaq/&lt;date&gt;/*.json"]
        C2["data/raw/open_meteo/&lt;date&gt;/*.json"]
        C3["data/raw/kaggle/*.csv"]
        C4["logs/ingestion_log.csv<br/>(extraction metadata)"]
    end

    subgraph ETL["Transformation Layer (Airflow-orchestrated)"]
        D1["load_staging.py<br/>parse raw -> staging tables"]
        D2["transform_clean.py<br/>validate, dedupe, normalize,<br/>join pollutants + weather"]
        D3["build_gold.py<br/>compute AQI, aggregate"]
    end

    subgraph STORE["Storage Layer (PostgreSQL)"]
        E1[("staging schema")]
        E2[("clean schema")]
        E3[("gold schema: marts")]
        E4[("meta schema: ingestion_log,<br/>rejected_records")]
    end

    subgraph ANALYTICS["Analytics / Presentation Layer"]
        F1["Streamlit dashboard<br/>(5 views)"]
    end

    subgraph MLOPS["MLOps Layer (Part 2)"]
        G1["ml/build_features.py<br/>(lag/rolling features)"]
        G2["ml/train.py<br/>MLflow tracking + registry"]
        G3["serving/app.py<br/>FastAPI + Docker"]
        G4["monitoring/monitor.py<br/>missing data, drift, forecast error"]
    end

    A1 --> B1 --> C1
    A2 --> B2 --> C2
    A3 --> B3 --> C3
    B1 & B2 & B3 --> C4

    C1 & C2 & C3 --> D1 --> E1
    E1 --> D2 --> E2
    D2 -.rejected rows.-> E4
    C4 -.synced.-> E4
    E2 --> D3 --> E3
    E3 --> F1

    E3 -.gold.station_daily_aqi.-> G1 --> G2 --> G3 --> F1
    G3 --> G4
    G4 -.writes meta.model_monitoring.-> E4
```

## Layer descriptions
- **Source layer**: External free/public APIs and datasets.
- **Ingestion layer**: Python scripts using `requests`/`pandas`, orchestrated by Airflow, with
  retry logic and structured logging.
- **Raw/landing layer**: Immutable, dated JSON/CSV files — the system of record for what was
  actually received from each source.
- **Transformation layer**: Three-stage ETL (staging → clean → gold) with explicit
  validation and rejection handling.
- **Storage layer**: PostgreSQL, schema-separated by layer (staging/clean/gold/meta).
- **Analytics layer**: Streamlit dashboard reading only from `gold`.
- **MLOps layer (Part 2)**: Feature pipeline (`ml/build_features.py`) reads the Part 1 gold
  layer directly — no rework needed. Models are trained and tracked via MLflow
  (`ml/train.py`), served via FastAPI/Docker (`serving/`), and monitored for missing data,
  feature drift, and forecast error (`monitoring/monitor.py`), with results surfaced back
  into the Streamlit dashboard and `meta.model_monitoring`.
