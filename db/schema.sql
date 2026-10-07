-- AQI Analytics Warehouse schema
-- Layers: staging (loosely-typed load from raw files) -> clean (validated, normalized,
-- deduplicated time-series) -> gold (aggregated analytical tables / data marts).
-- Run: psql -h localhost -U aqi_user -d aqi_dw -f db/schema.sql

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS clean;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS meta;

-- =========================================================================
-- META LAYER: pipeline observability (ingestion + rejected records)
-- =========================================================================

CREATE TABLE IF NOT EXISTS meta.ingestion_log (
    id              BIGSERIAL PRIMARY KEY,
    extracted_at_utc TIMESTAMPTZ NOT NULL,
    source          TEXT NOT NULL,          -- 'openaq' | 'open_meteo' | 'kaggle_csv'
    endpoint        TEXT,
    status          TEXT NOT NULL,          -- 'SUCCESS' | 'EMPTY' | 'FAILED'
    row_count       INTEGER NOT NULL DEFAULT 0,
    raw_file        TEXT,
    error_message   TEXT,
    loaded_at_utc   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meta.rejected_records (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    station_name    TEXT,
    parameter       TEXT,
    raw_value       TEXT,
    observed_at     TIMESTAMPTZ,
    rejection_reason TEXT NOT NULL,          -- e.g. 'out_of_range', 'null_timestamp', 'duplicate'
    rejected_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_payload     JSONB
);

-- =========================================================================
-- STAGING LAYER: near-raw load, one row per source measurement, unvalidated
-- =========================================================================

CREATE TABLE IF NOT EXISTS staging.pollutant_measurements (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'openaq',
    station_id      TEXT,
    station_name    TEXT,
    city            TEXT,
    parameter       TEXT,          -- pm25, pm10, no2, so2, co, o3
    value           DOUBLE PRECISION,
    unit            TEXT,
    observed_at_raw TEXT,          -- original timestamp string, pre-normalization
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    loaded_at_utc   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staging.weather_observations (
    id              BIGSERIAL PRIMARY KEY,
    city            TEXT,
    observed_at_raw TEXT,
    temperature_2m  DOUBLE PRECISION,
    relative_humidity_2m DOUBLE PRECISION,
    precipitation   DOUBLE PRECISION,
    wind_speed_10m  DOUBLE PRECISION,
    wind_direction_10m DOUBLE PRECISION,
    loaded_at_utc   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================================
-- CLEAN LAYER: validated, deduplicated, unit-normalized, timezone-normalized
-- =========================================================================

CREATE TABLE IF NOT EXISTS clean.stations (
    station_id      TEXT PRIMARY KEY,
    station_name    TEXT NOT NULL,
    city            TEXT NOT NULL,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS clean.pollutant_measurements (
    id              BIGSERIAL PRIMARY KEY,
    station_id      TEXT NOT NULL REFERENCES clean.stations(station_id),
    parameter       TEXT NOT NULL,          -- normalized lowercase: pm25, pm10, no2, so2, co, o3
    value           DOUBLE PRECISION NOT NULL,
    unit            TEXT NOT NULL,          -- normalized: ug/m3 or ppm depending on parameter
    observed_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (station_id, parameter, observed_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_clean_measurements_time
    ON clean.pollutant_measurements (observed_at_utc);
CREATE INDEX IF NOT EXISTS idx_clean_measurements_station
    ON clean.pollutant_measurements (station_id);

CREATE TABLE IF NOT EXISTS clean.weather_observations (
    id              BIGSERIAL PRIMARY KEY,
    city            TEXT NOT NULL,
    observed_at_utc TIMESTAMPTZ NOT NULL,
    temperature_c   DOUBLE PRECISION,
    relative_humidity_pct DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    wind_speed_ms   DOUBLE PRECISION,
    wind_direction_deg DOUBLE PRECISION,
    UNIQUE (city, observed_at_utc)
);

-- =========================================================================
-- GOLD LAYER: analytical marts for the dashboard (city/station/pollutant/date)
-- =========================================================================

-- Station-hour grain: pollutant + weather joined, with computed AQI sub-index per pollutant
CREATE TABLE IF NOT EXISTS gold.station_hourly_aqi (
    station_id      TEXT NOT NULL,
    station_name    TEXT NOT NULL,
    city            TEXT NOT NULL,
    observed_at_utc TIMESTAMPTZ NOT NULL,
    pm25            DOUBLE PRECISION,
    pm10            DOUBLE PRECISION,
    no2             DOUBLE PRECISION,
    so2             DOUBLE PRECISION,
    co              DOUBLE PRECISION,
    o3              DOUBLE PRECISION,
    aqi             INTEGER,                -- overall AQI = max of sub-indices
    aqi_category    TEXT,                   -- Good/Satisfactory/Moderate/Poor/Very Poor/Severe
    dominant_pollutant TEXT,
    temperature_c   DOUBLE PRECISION,
    relative_humidity_pct DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    wind_speed_ms   DOUBLE PRECISION,
    PRIMARY KEY (station_id, observed_at_utc)
);

-- Station-day grain
CREATE TABLE IF NOT EXISTS gold.station_daily_aqi (
    station_id      TEXT NOT NULL,
    station_name    TEXT NOT NULL,
    city            TEXT NOT NULL,
    observation_date DATE NOT NULL,
    avg_pm25 DOUBLE PRECISION, avg_pm10 DOUBLE PRECISION, avg_no2 DOUBLE PRECISION,
    avg_so2 DOUBLE PRECISION, avg_co DOUBLE PRECISION, avg_o3 DOUBLE PRECISION,
    avg_aqi         DOUBLE PRECISION,
    max_aqi         INTEGER,
    dominant_pollutant TEXT,
    avg_temperature_c DOUBLE PRECISION,
    avg_humidity_pct  DOUBLE PRECISION,
    total_precipitation_mm DOUBLE PRECISION,
    avg_wind_speed_ms DOUBLE PRECISION,
    PRIMARY KEY (station_id, observation_date)
);

-- City-day grain (average across stations)
CREATE TABLE IF NOT EXISTS gold.city_daily_aqi (
    city            TEXT NOT NULL,
    observation_date DATE NOT NULL,
    avg_aqi         DOUBLE PRECISION,
    max_aqi         INTEGER,
    dominant_pollutant TEXT,
    station_count   INTEGER,
    PRIMARY KEY (city, observation_date)
);

-- Pollutant contribution mart (share of each pollutant's sub-index toward overall AQI)
CREATE TABLE IF NOT EXISTS gold.pollutant_contribution_daily (
    city            TEXT NOT NULL,
    observation_date DATE NOT NULL,
    parameter       TEXT NOT NULL,
    avg_sub_index   DOUBLE PRECISION,
    contribution_pct DOUBLE PRECISION,
    PRIMARY KEY (city, observation_date, parameter)
);

-- =========================================================================
-- PART 2 (MLOps): feature store, predictions log, monitoring
-- =========================================================================

-- Reusable feature-engineering output: one row per station-day, with lag/rolling
-- features and the next-day AQI/category as prediction targets. This is what
-- ml/build_features.py writes and ml/train.py reads.
CREATE TABLE IF NOT EXISTS gold.ml_features_daily (
    station_id      TEXT NOT NULL,
    station_name    TEXT NOT NULL,
    city            TEXT NOT NULL,
    observation_date DATE NOT NULL,
    avg_aqi         DOUBLE PRECISION,
    avg_pm25 DOUBLE PRECISION, avg_pm10 DOUBLE PRECISION, avg_no2 DOUBLE PRECISION,
    avg_so2 DOUBLE PRECISION, avg_co DOUBLE PRECISION, avg_o3 DOUBLE PRECISION,
    avg_temperature_c DOUBLE PRECISION, avg_humidity_pct DOUBLE PRECISION,
    total_precipitation_mm DOUBLE PRECISION, avg_wind_speed_ms DOUBLE PRECISION,
    aqi_lag1        DOUBLE PRECISION,
    aqi_lag2        DOUBLE PRECISION,
    aqi_lag3        DOUBLE PRECISION,
    aqi_roll_mean_3 DOUBLE PRECISION,
    aqi_roll_mean_7 DOUBLE PRECISION,
    aqi_roll_std_3  DOUBLE PRECISION,
    day_of_week     INTEGER,
    month           INTEGER,
    target_next_day_aqi DOUBLE PRECISION,   -- regression target: tomorrow's avg_aqi
    target_next_day_category TEXT,          -- classification target: tomorrow's AQI category
    PRIMARY KEY (station_id, observation_date)
);

-- Every prediction served (batch or via the FastAPI endpoint) is logged here so
-- forecasting error can be computed once the real next-day AQI becomes known.
CREATE TABLE IF NOT EXISTS meta.predictions_log (
    id                  BIGSERIAL PRIMARY KEY,
    predicted_at_utc    TIMESTAMPTZ NOT NULL DEFAULT now(),
    station_id          TEXT NOT NULL,
    target_date         DATE NOT NULL,       -- the date being predicted (observation_date + 1)
    model_name          TEXT NOT NULL,       -- 'aqi_regressor' | 'aqi_classifier'
    model_version       TEXT,
    predicted_aqi       DOUBLE PRECISION,
    predicted_category  TEXT,
    actual_aqi          DOUBLE PRECISION,    -- backfilled later by monitoring job
    actual_category     TEXT,
    served_by           TEXT                 -- 'batch' | 'fastapi'
);

-- Monitoring job results: missing-data checks, feature drift, forecasting error,
-- written by monitoring/monitor.py and read by the dashboard's monitoring view.
CREATE TABLE IF NOT EXISTS meta.model_monitoring (
    id              BIGSERIAL PRIMARY KEY,
    checked_at_utc  TIMESTAMPTZ NOT NULL DEFAULT now(),
    check_type      TEXT NOT NULL,          -- 'missing_data' | 'feature_drift' | 'forecast_error' | 'latency'
    metric_name     TEXT NOT NULL,
    metric_value    DOUBLE PRECISION,
    status          TEXT NOT NULL,          -- 'OK' | 'WARN' | 'ALERT'
    details         TEXT
);
