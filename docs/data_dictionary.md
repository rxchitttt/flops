# Data Dictionary & Validation Rules

## Layer overview
| Layer | Schema | Purpose |
|---|---|---|
| Raw | `data/raw/` (filesystem, not DB) | Immutable copy of every API response / CSV, exactly as received |
| Staging | `staging` | Loosely-typed load of raw files into Postgres, one row per source record |
| Clean | `clean` | Validated, deduplicated, unit- and timestamp-normalized time series |
| Gold | `gold` | Aggregated analytical marts consumed by the dashboard |
| Meta | `meta` | Pipeline observability: ingestion log, rejected records |

## `clean.stations`
| Column | Type | Description |
|---|---|---|
| station_id | TEXT (PK) | OpenAQ location ID (string form) |
| station_name | TEXT | Human-readable station name |
| city | TEXT | City the station belongs to |
| latitude / longitude | DOUBLE | Station coordinates |

## `clean.pollutant_measurements`
| Column | Type | Description | Validation rule |
|---|---|---|---|
| station_id | TEXT (FK) | References clean.stations | must exist |
| parameter | TEXT | One of: pm25, pm10, no2, so2, co, o3 | normalized to lowercase; pm2.5→pm25 |
| value | DOUBLE | Concentration | must be non-null, ≥ 0, and within the plausible range in `etl/aqi_calculator.VALID_RANGE`; otherwise rejected |
| unit | TEXT | ug/m3 (pollutants) or mg/m3 (co) | normalized from source unit (ppm→mg/m3 for CO) |
| observed_at_utc | TIMESTAMPTZ | Normalized to UTC | must parse to a valid timestamp; otherwise rejected |
| (station_id, parameter, observed_at_utc) | UNIQUE | | duplicate rows on this key are dropped, keeping one |

## `clean.weather_observations`
| Column | Type | Description |
|---|---|---|
| city | TEXT | City name |
| observed_at_utc | TIMESTAMPTZ | Hourly timestamp, UTC |
| temperature_c | DOUBLE | °C |
| relative_humidity_pct | DOUBLE | % |
| precipitation_mm | DOUBLE | mm |
| wind_speed_ms | DOUBLE | m/s |
| wind_direction_deg | DOUBLE | degrees |

## `gold.station_hourly_aqi`
Station-hour grain: one row per station per hour, pollutant values pivoted to columns,
joined with weather, plus computed AQI fields.
| Column | Description |
|---|---|
| pm25, pm10, no2, so2, co, o3 | Mean concentration for that station-hour |
| aqi | Overall AQI = max of all available pollutant sub-indices (CPCB method) |
| aqi_category | Good / Satisfactory / Moderate / Poor / Very Poor / Severe |
| dominant_pollutant | Pollutant whose sub-index produced the overall AQI |

## `gold.station_daily_aqi` / `gold.city_daily_aqi`
Daily aggregates (mean/max AQI, mean pollutant concentrations, mean/sum weather) at
station and city grain respectively — the core data marts behind the dashboard's trend and
comparison views.

## `gold.pollutant_contribution_daily`
One row per (city, date, pollutant): that pollutant's average sub-index and its % share of
the summed sub-indices that day — powers the "pollutant contribution" pie chart.

## `meta.ingestion_log`
One row per extraction attempt: source, endpoint, status (SUCCESS/EMPTY/FAILED), row count,
raw file path, error message. Mirrors `logs/ingestion_log.csv`.

## `meta.rejected_records`
One row per record that failed a validation rule during staging→clean transformation, with
the rejection reason (`missing_timestamp_or_id`, `null_value`, `out_of_range`, or duplicate
handling done via drop rather than logging here).

## AQI Standard & Categories (CPCB National AQI)
| AQI range | Category |
|---|---|
| 0–50 | Good |
| 51–100 | Satisfactory |
| 101–200 | Moderate |
| 201–300 | Poor |
| 301–400 | Very Poor |
| 401–500 | Severe |

See `etl/aqi_calculator.py` for the full breakpoint table per pollutant and the documented
assumption about applying CPCB's 24-hr/8-hr breakpoints to hourly OpenAQ readings.
