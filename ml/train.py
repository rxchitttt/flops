"""
Part 2 - model training & evaluation.

- Reads gold.ml_features_daily (built by ml/build_features.py).
- Chronological split (not random - this is a time series): oldest ~70% train,
  next ~15% validation, most recent ~15% test. Prevents leaking future data into
  training, which a random split would do.
- Trains and compares models for both tasks:
    Regression   -> predict tomorrow's AQI value    (metrics: RMSE, MAE)
    Classification -> predict tomorrow's AQI category (metrics: precision/recall/F1)
- Every run, every model, every metric is logged to MLflow. The best model per task
  (by validation metric) is registered in the MLflow Model Registry and also dumped
  to models/ as a joblib fallback so FastAPI can serve without a live MLflow server.

Run: python ml/train.py
"""
import sys
from pathlib import Path

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import f1_score, mean_absolute_error, precision_score, recall_score, root_mean_squared_error
from sklearn.preprocessing import LabelEncoder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "etl"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # ml/ itself, for build_features
from build_features import FEATURE_COLUMNS  # noqa: E402
from config import (  # noqa: E402
    CLASSIFIER_MODEL_NAME,
    MLFLOW_TRACKING_URI,
    MODEL_REGISTRY_DIR,
    REGRESSOR_MODEL_NAME,
)
from db_utils import get_engine  # noqa: E402

MIN_ROWS_REQUIRED = 15  # below this, a chronological 70/15/15 split isn't meaningful


def chronological_split(df: pd.DataFrame):
    df = df.sort_values("observation_date").reset_index(drop=True)
    n = len(df)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


def _prep_xy(df: pd.DataFrame, target_col: str):
    X = df[FEATURE_COLUMNS].fillna(df[FEATURE_COLUMNS].median(numeric_only=True))
    y = df[target_col]
    return X, y


def train_regression(train, val, test):
    candidates = {
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(n_estimators=200, max_depth=6, random_state=42),
        "gradient_boosting": GradientBoostingRegressor(random_state=42),
    }
    X_train, y_train = _prep_xy(train, "target_next_day_aqi")
    X_val, y_val = _prep_xy(val, "target_next_day_aqi")
    X_test, y_test = _prep_xy(test, "target_next_day_aqi")

    best_name, best_model, best_val_rmse = None, None, float("inf")
    for name, model in candidates.items():
        with mlflow.start_run(run_name=f"regression_{name}"):
            model.fit(X_train, y_train)
            val_pred = model.predict(X_val)
            val_rmse = root_mean_squared_error(y_val, val_pred)
            val_mae = mean_absolute_error(y_val, val_pred)
            mlflow.log_param("model_type", name)
            mlflow.log_param("task", "regression")
            mlflow.log_param("n_train", len(train))
            mlflow.log_metric("val_rmse", val_rmse)
            mlflow.log_metric("val_mae", val_mae)
            mlflow.sklearn.log_model(model, artifact_path="model")
            print(f"[train][regression:{name}] val_rmse={val_rmse:.2f} val_mae={val_mae:.2f}")

            if val_rmse < best_val_rmse:
                best_val_rmse, best_name, best_model = val_rmse, name, model

    test_pred = best_model.predict(X_test)
    test_rmse = root_mean_squared_error(y_test, test_pred)
    test_mae = mean_absolute_error(y_test, test_pred)
    with mlflow.start_run(run_name=f"regression_BEST_{best_name}"):
        mlflow.log_param("model_type", best_name)
        mlflow.log_param("task", "regression")
        mlflow.log_param("selected_as_best", True)
        mlflow.log_metric("val_rmse", best_val_rmse)
        mlflow.log_metric("test_rmse", test_rmse)
        mlflow.log_metric("test_mae", test_mae)
        model_info = mlflow.sklearn.log_model(
            best_model, artifact_path="model", registered_model_name=REGRESSOR_MODEL_NAME)
    print(f"[train][regression] BEST = {best_name} | test_rmse={test_rmse:.2f} test_mae={test_mae:.2f}")

    joblib.dump(best_model, MODEL_REGISTRY_DIR / "aqi_regressor.joblib")
    joblib.dump(FEATURE_COLUMNS, MODEL_REGISTRY_DIR / "feature_columns.joblib")
    return best_name, test_rmse, test_mae


def train_classification(train, val, test):
    all_categories = pd.concat([train["target_next_day_category"], val["target_next_day_category"],
                                 test["target_next_day_category"]]).dropna().unique()
    encoder = LabelEncoder().fit(all_categories)

    candidates = {
        "logistic_regression": LogisticRegression(max_iter=1000),
        "random_forest": RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42),
        "gradient_boosting": GradientBoostingClassifier(random_state=42),
    }
    X_train, y_train_raw = _prep_xy(train, "target_next_day_category")
    X_val, y_val_raw = _prep_xy(val, "target_next_day_category")
    X_test, y_test_raw = _prep_xy(test, "target_next_day_category")
    y_train, y_val, y_test = encoder.transform(y_train_raw), encoder.transform(y_val_raw), encoder.transform(y_test_raw)

    best_name, best_model, best_val_f1 = None, None, -1
    for name, model in candidates.items():
        with mlflow.start_run(run_name=f"classification_{name}"):
            model.fit(X_train, y_train)
            val_pred = model.predict(X_val)
            val_f1 = f1_score(y_val, val_pred, average="weighted", zero_division=0)
            val_precision = precision_score(y_val, val_pred, average="weighted", zero_division=0)
            val_recall = recall_score(y_val, val_pred, average="weighted", zero_division=0)
            mlflow.log_param("model_type", name)
            mlflow.log_param("task", "classification")
            mlflow.log_param("n_train", len(train))
            mlflow.log_metric("val_f1", val_f1)
            mlflow.log_metric("val_precision", val_precision)
            mlflow.log_metric("val_recall", val_recall)
            mlflow.sklearn.log_model(model, artifact_path="model")
            print(f"[train][classification:{name}] val_f1={val_f1:.3f} "
                  f"val_precision={val_precision:.3f} val_recall={val_recall:.3f}")

            if val_f1 > best_val_f1:
                best_val_f1, best_name, best_model = val_f1, name, model

    test_pred = best_model.predict(X_test)
    test_f1 = f1_score(y_test, test_pred, average="weighted", zero_division=0)
    test_precision = precision_score(y_test, test_pred, average="weighted", zero_division=0)
    test_recall = recall_score(y_test, test_pred, average="weighted", zero_division=0)
    with mlflow.start_run(run_name=f"classification_BEST_{best_name}"):
        mlflow.log_param("model_type", best_name)
        mlflow.log_param("task", "classification")
        mlflow.log_param("selected_as_best", True)
        mlflow.log_metric("val_f1", best_val_f1)
        mlflow.log_metric("test_f1", test_f1)
        mlflow.log_metric("test_precision", test_precision)
        mlflow.log_metric("test_recall", test_recall)
        mlflow.sklearn.log_model(
            best_model, artifact_path="model", registered_model_name=CLASSIFIER_MODEL_NAME)
    print(f"[train][classification] BEST = {best_name} | test_f1={test_f1:.3f}")

    joblib.dump(best_model, MODEL_REGISTRY_DIR / "aqi_classifier.joblib")
    joblib.dump(encoder, MODEL_REGISTRY_DIR / "category_encoder.joblib")
    return best_name, test_f1


def run():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("aqi_next_day_forecasting")

    engine = get_engine()
    features = pd.read_sql("SELECT * FROM gold.ml_features_daily ORDER BY observation_date", engine)
    features = features.dropna(subset=["target_next_day_aqi", "target_next_day_category"])

    if len(features) < MIN_ROWS_REQUIRED:
        print(f"[train] only {len(features)} labeled rows available (need >= {MIN_ROWS_REQUIRED} "
              f"for a meaningful chronological split). Run the pipeline for more days, or "
              f"backfill historical data, before training.")
        return

    train, val, test = chronological_split(features)
    print(f"[train] split sizes -> train={len(train)} val={len(val)} test={len(test)}")

    # Baseline feature distribution (from TRAIN only) - monitoring/monitor.py compares
    # newly-ingested data against this to detect drift.
    baseline = train[FEATURE_COLUMNS].describe().to_dict()
    joblib.dump(baseline, MODEL_REGISTRY_DIR / "feature_baseline.joblib")

    reg_name, reg_rmse, reg_mae = train_regression(train, val, test)
    clf_name, clf_f1 = train_classification(train, val, test)

    print("\n=== Training summary ===")
    print(f"Regression best model:     {reg_name} (test RMSE={reg_rmse:.2f}, MAE={reg_mae:.2f})")
    print(f"Classification best model: {clf_name} (test F1={clf_f1:.3f})")
    print(f"Models registered in MLflow at: {MLFLOW_TRACKING_URI}")
    print(f"Joblib fallback copies saved under: {MODEL_REGISTRY_DIR}")


if __name__ == "__main__":
    run()
