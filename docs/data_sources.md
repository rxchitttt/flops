# Data Sources

Dataset rule compliance: all sources below are free, publicly accessible, and require at most
a free self-service registration. No private, personal, or confidential data is used.

## 1. OpenAQ API (primary source)
- **What**: Real/near-real-time air pollutant measurements (PM2.5, PM10, NO2, SO2, CO, O3) from
  government and community monitoring stations worldwide.
- **URL**: https://docs.openaq.org/
- **Access**: Register for a free API key at https://explore.openaq.org/register, put it in
  `.env` as `OPENAQ_API_KEY`.
- **Scope used**: Monitoring stations within ~25km of Bengaluru (12.9716° N, 77.5946° E).
  Station IDs discovered via `scripts/discover_stations.py` and pinned in `.env` as
  `OPENAQ_LOCATION_IDS`.
- **License**: OpenAQ data is provided under CC BY 4.0 (attribution required — see report).

## 2. Open-Meteo API (weather enrichment)
- **What**: Free historical + forecast weather data (temperature, humidity, precipitation,
  wind) with no API key required.
- **URL**: https://open-meteo.com/
- **Access**: No signup needed for the free tier used here (archive + forecast endpoints).
- **Scope used**: Hourly weather for Bengaluru's coordinates, matched to the same time range
  as the pollutant data.

## 3. Kaggle AQI dataset (fallback / historical backfill)
- **What**: Historical CSV air-quality dataset, used to backfill periods before OpenAQ API
  history is available and for rapid local prototyping without hitting the live API.
- **Suggested dataset**: "Air Quality Data in India (2015 - 2020)" —
  https://www.kaggle.com/datasets/rohanrao/air-quality-data-in-india (filter to Bengaluru
  station rows).
- **Access**: Requires a free Kaggle account; download via the website or the Kaggle CLI
  (`kaggle datasets download -d rohanrao/air-quality-data-in-india`), which needs a
  `kaggle.json` API token from your Kaggle account settings.
- **Usage**: Place the downloaded CSV at `data/raw/kaggle/<filename>.csv` and run
  `python ingestion/load_kaggle_csv.py data/raw/kaggle/<filename>.csv`.

## 4. CPCB historical data (optional, not automated in this project)
- **What**: India-specific official AQI/pollutant observations from the Central Pollution
  Control Board.
- **URL**: https://cpcb.nic.in/ / https://airquality.cpcb.gov.in/
- **Status**: Not integrated in Part 1 because CPCB's public download portal does not expose
  a stable, scriptable bulk API for the chosen station set; OpenAQ mirrors much of CPCB's
  station network for Bengaluru already. Documented here as an optional future source.

## AQI Standard
Overall AQI and sub-indices are computed using the **CPCB National Air Quality Index**
breakpoint table (chosen because the target city, Bengaluru, is in India — see
`etl/aqi_calculator.py` for the exact breakpoints and the documented assumption about
applying it to hourly rather than 24-hr-averaged values).
