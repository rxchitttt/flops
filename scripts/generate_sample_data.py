"""
Generate synthetic raw OpenAQ and Open-Meteo data for Bengaluru so the full pipeline
(ETL, Gold marts, Feature engineering, Model training, Serving, Dashboard) can be tested
end-to-end immediately without needing a live OpenAQ API key or internet access.

Run:
  python scripts/generate_sample_data.py
"""
import datetime as dt
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
OPENAQ_DIR = DATA_RAW / "openaq"
WEATHER_DIR = DATA_RAW / "open_meteo"


def generate_data(days: int = 45):
    print(f"Generating {days} days of realistic sample raw data for Bengaluru...")
    now = dt.datetime.now(dt.timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    openaq_today_dir = OPENAQ_DIR / today_str
    weather_today_dir = WEATHER_DIR / today_str
    openaq_today_dir.mkdir(parents=True, exist_ok=True)
    weather_today_dir.mkdir(parents=True, exist_ok=True)

    stations = [
        {"id": 1001, "name": "BTM Layout, Bengaluru", "lat": 12.9165, "lon": 77.6101},
        {"id": 1002, "name": "Peenya, Bengaluru", "lat": 13.0285, "lon": 77.5197},
        {"id": 1003, "name": "Silk Board, Bengaluru", "lat": 12.9172, "lon": 77.6228},
    ]

    pollutants = [
        ("pm25", "µg/m³", (25.0, 95.0)),
        ("pm10", "µg/m³", (45.0, 160.0)),
        ("no2", "µg/m³", (15.0, 65.0)),
        ("so2", "µg/m³", (5.0, 25.0)),
        ("co", "mg/m3", (0.4, 2.2)),
        ("o3", "µg/m³", (10.0, 50.0)),
    ]

    start_date = now - dt.timedelta(days=days)
    hours = days * 24

    # 1. Generate OpenAQ results for each station
    for station in stations:
        station_results = []
        for h in range(hours):
            t = start_date + dt.timedelta(hours=h)
            iso_t = t.strftime("%Y-%m-%dT%H:%M:%SZ")

            # slight daily cycle
            hour_factor = 1.0 + 0.3 * (h % 24 in [8, 9, 10, 18, 19, 20])

            for param_name, unit, (low, high) in pollutants:
                val = round(random.uniform(low, high) * hour_factor, 2)
                station_results.append({
                    "locationId": station["id"],
                    "location": {"id": station["id"], "name": station["name"]},
                    "parameter": {"name": param_name, "units": unit},
                    "value": val,
                    "coordinates": {"latitude": station["lat"], "longitude": station["lon"]},
                    "period": {"datetimeFrom": {"utc": iso_t}},
                })

        station_file = openaq_today_dir / f"location_{station['id']}_sample.json"
        with open(station_file, "w", encoding="utf-8") as f:
            json.dump({"results": station_results}, f, indent=2)
        print(f"  Created OpenAQ sample: {station_file} ({len(station_results)} records)")

    # 2. Generate Open-Meteo hourly weather
    weather_times = []
    temps = []
    humidities = []
    precips = []
    wind_speeds = []
    wind_dirs = []

    for h in range(hours):
        t = start_date + dt.timedelta(hours=h)
        weather_times.append(t.strftime("%Y-%m-%dT%H:%M"))
        temps.append(round(random.uniform(20.0, 32.0), 1))
        humidities.append(round(random.uniform(45.0, 85.0), 1))
        precips.append(round(random.choice([0.0, 0.0, 0.0, 0.0, 1.5, 4.0]), 1))
        wind_speeds.append(round(random.uniform(1.5, 6.5), 1))
        wind_dirs.append(random.randint(0, 360))

    weather_payload = {
        "hourly": {
            "time": weather_times,
            "temperature_2m": temps,
            "relative_humidity_2m": humidities,
            "precipitation": precips,
            "wind_speed_10m": wind_speeds,
            "wind_direction_10m": wind_dirs,
        }
    }
    weather_file = weather_today_dir / "sample_weather.json"
    with open(weather_file, "w", encoding="utf-8") as f:
        json.dump(weather_payload, f, indent=2)
    print(f"  Created Weather sample: {weather_file} ({len(weather_times)} hourly records)")

    # Update .env if OPENAQ_LOCATION_IDS is empty
    env_file = ROOT / ".env"
    if env_file.exists():
        content = env_file.read_text()
        if "OPENAQ_LOCATION_IDS=" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("OPENAQ_LOCATION_IDS=") and (line == "OPENAQ_LOCATION_IDS=" or not line.split("=")[1].strip()):
                    new_lines.append("OPENAQ_LOCATION_IDS=1001,1002,1003")
                else:
                    new_lines.append(line)
            env_file.write_text("\n".join(new_lines) + "\n")
            print("  Updated .env with OPENAQ_LOCATION_IDS=1001,1002,1003")

    print("\nSample raw data generated successfully! You can now run:")
    print("  python scripts/run_pipeline.py  (or run load_staging, transform_clean, build_gold)")


if __name__ == "__main__":
    generate_data(days=45)
