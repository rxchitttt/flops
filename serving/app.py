"""
Part 2 - FastAPI inference service.

Serves the two registered models (regressor + classifier) trained by ml/train.py.
Loads from the joblib fallback in models/ (works with no MLflow server running,
which is what a Dockerized deployment needs); swapping to
`mlflow.pyfunc.load_model(f"models:/{name}/Production")` is a one-line change once a
tracking server + registry stage promotion is in place (see docs/model_lifecycle.md).

Run locally: uvicorn serving.app:app --reload --port 8000
Run in Docker: see serving/Dockerfile
"""
import datetime as dt
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "ingestion"))
sys.path.insert(0, str(ROOT / "ml"))
from build_features import FEATURE_COLUMNS  # noqa: E402
from config import MODEL_REGISTRY_DIR  # noqa: E402
from db_utils import get_engine  # noqa: E402


_state = {"regressor": None, "classifier": None, "encoder": None, "loaded_at": None}


def _load_models():
    reg_path = MODEL_REGISTRY_DIR / "aqi_regressor.joblib"
    clf_path = MODEL_REGISTRY_DIR / "aqi_classifier.joblib"
    enc_path = MODEL_REGISTRY_DIR / "category_encoder.joblib"
    if not (reg_path.exists() and clf_path.exists() and enc_path.exists()):
        return False
    _state["regressor"] = joblib.load(reg_path)
    _state["classifier"] = joblib.load(clf_path)
    _state["encoder"] = joblib.load(enc_path)
    _state["loaded_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_models()
    yield


app = FastAPI(title="AQI Next-Day Prediction API", version="1.0.0", lifespan=lifespan)


class PredictRequest(BaseModel):
    station_id: str


class PredictResponse(BaseModel):
    station_id: str
    based_on_date: str
    target_date: str
    predicted_aqi: float
    predicted_category: str
    model_regressor: str = "aqi_next_day_regressor"
    model_classifier: str = "aqi_next_day_classifier"


@app.get("/health")
def health():
    return {
        "status": "ok" if _state["regressor"] is not None else "models_not_loaded",
        "models_loaded_at": _state["loaded_at"],
    }


@app.get("/stations")
def list_stations():
    engine = get_engine()
    df = pd.read_sql(
        "SELECT DISTINCT station_id, station_name FROM gold.ml_features_daily", engine)
    return df.to_dict(orient="records")


@app.post("/reload_models")
def reload_models():
    ok = _load_models()
    if not ok:
        raise HTTPException(503, "Model artifacts not found in models/ - run ml/train.py first")
    return {"status": "reloaded", "loaded_at": _state["loaded_at"]}


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if _state["regressor"] is None:
        raise HTTPException(503, "Models not loaded yet - run ml/train.py, then POST /reload_models")

    engine = get_engine()
    with engine.begin() as conn:
        latest = pd.read_sql(text("""
            SELECT * FROM gold.ml_features_daily
            WHERE station_id = :sid
            ORDER BY observation_date DESC
            LIMIT 1
        """), conn, params={"sid": req.station_id})

    if latest.empty:
        raise HTTPException(404, f"No feature data found for station_id={req.station_id!r}. "
                                  f"Run etl/build_gold.py and ml/build_features.py first.")

    row = latest.iloc[0]
    X = latest[FEATURE_COLUMNS].fillna(latest[FEATURE_COLUMNS].median(numeric_only=True))

    predicted_aqi = float(_state["regressor"].predict(X)[0])
    predicted_category_encoded = _state["classifier"].predict(X)[0]
    predicted_category = _state["encoder"].inverse_transform([predicted_category_encoded])[0]

    based_on_date = pd.to_datetime(row["observation_date"]).date()
    target_date = based_on_date + dt.timedelta(days=1)

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO meta.predictions_log
                (station_id, target_date, model_name, predicted_aqi, predicted_category, served_by)
            VALUES (:station_id, :target_date, 'aqi_next_day_regressor', :predicted_aqi, :predicted_category, 'fastapi')
        """), {"station_id": req.station_id, "target_date": target_date,
               "predicted_aqi": round(predicted_aqi, 1), "predicted_category": predicted_category})

    return PredictResponse(
        station_id=req.station_id,
        based_on_date=str(based_on_date),
        target_date=str(target_date),
        predicted_aqi=round(predicted_aqi, 1),
        predicted_category=predicted_category,
    )
