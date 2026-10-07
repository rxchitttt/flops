"""
Shared configuration loaded from environment variables (.env).
Every script in this project imports from here instead of reading os.environ directly,
so there is exactly one place that knows about credentials and project scope.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Project scope ---
CITY_NAME = os.getenv("CITY_NAME", "Bengaluru")
CITY_LAT = float(os.getenv("CITY_LAT", "12.9716"))
CITY_LON = float(os.getenv("CITY_LON", "77.5946"))
OPENAQ_LOCATION_IDS = [
    int(x) for x in os.getenv("OPENAQ_LOCATION_IDS", "").split(",") if x.strip()
]

# --- OpenAQ ---
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "")
OPENAQ_BASE_URL = "https://api.openaq.org/v3"

# --- Open-Meteo ---
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# --- Postgres ---
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "aqi_dw")
POSTGRES_USER = os.getenv("POSTGRES_USER", "aqi_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

POSTGRES_DSN = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# --- Paths ---
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_STAGING_DIR = PROJECT_ROOT / "data" / "staging"
LOGS_DIR = PROJECT_ROOT / "logs"
INGESTION_LOG_CSV = LOGS_DIR / "ingestion_log.csv"
REJECTED_LOG_CSV = LOGS_DIR / "rejected_records.csv"

for d in (DATA_RAW_DIR / "openaq", DATA_RAW_DIR / "open_meteo", DATA_STAGING_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --- Part 2: MLOps ---
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI") or f"file://{PROJECT_ROOT / 'mlruns'}"
MODEL_REGISTRY_DIR = PROJECT_ROOT / "models"
MODEL_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
REGRESSOR_MODEL_NAME = "aqi_next_day_regressor"
CLASSIFIER_MODEL_NAME = "aqi_next_day_classifier"
