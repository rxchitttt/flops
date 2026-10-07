"""
One-off helper: list OpenAQ monitoring locations near the configured city so you can
pick which station IDs to put in OPENAQ_LOCATION_IDS in .env.

Run: python scripts/discover_stations.py
Requires OPENAQ_API_KEY to be set in .env (free key: https://explore.openaq.org/register).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))

import requests
from config import CITY_LAT, CITY_LON, CITY_NAME, OPENAQ_API_KEY, OPENAQ_BASE_URL


def main():
    if not OPENAQ_API_KEY or OPENAQ_API_KEY == "your_openaq_api_key_here":
        print("=" * 70)
        print("ERROR: OPENAQ_API_KEY is not configured in .env.")
        print("OpenAQ v3 requires an API key.")
        print("1. Get a free API key at: https://explore.openaq.org/register")
        print("2. Open .env and set: OPENAQ_API_KEY=<your_actual_key>")
        print("=" * 70)
        sys.exit(1)

    try:
        resp = requests.get(
            f"{OPENAQ_BASE_URL}/locations",
            headers={"X-API-Key": OPENAQ_API_KEY},
            params={"coordinates": f"{CITY_LAT},{CITY_LON}", "radius": 25000, "limit": 50},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        if resp.status_code == 401:
            print("=" * 70)
            print("ERROR: 401 Unauthorized from OpenAQ API.")
            print("Your OPENAQ_API_KEY appears invalid or expired.")
            print("Please verify your API key at: https://explore.openaq.org/")
            print("=" * 70)
            sys.exit(1)
        raise exc
    results = resp.json().get("results", [])

    print(f"Found {len(results)} OpenAQ locations within 25km of {CITY_NAME} "
          f"({CITY_LAT}, {CITY_LON}):\n")
    ids = []
    for loc in results:
        loc_id = loc.get("id")
        name = loc.get("name")
        sensors = [s.get("parameter", {}).get("name") for s in loc.get("sensors", [])]
        print(f"  id={loc_id:<8} name={name!r:<35} pollutants={sensors}")
        ids.append(str(loc_id))

    print("\nSuggested .env line:")
    print(f"OPENAQ_LOCATION_IDS={','.join(ids)}")


if __name__ == "__main__":
    main()
