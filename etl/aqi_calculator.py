"""
AQI sub-index calculation using the CPCB (Central Pollution Control Board) National Air
Quality Index breakpoint standard - chosen because the project targets an Indian city
(Bengaluru) and CPCB is the applicable regulatory standard (vs. US-EPA breakpoints, which
use different pollutant units/averaging periods).

Reference breakpoints (µg/m3 unless noted; CO in mg/m3):
https://cpcb.nic.in/displaypdf.php?id=aXVwbG9hZC9DUENCX3JlcG9ydF8yMDIwLnBkZg==  (CPCB AQI
manual). Values below are the standard published breakpoint table.

IMPORTANT ASSUMPTION documented in the report: OpenAQ typically reports hourly (not
24-hr/8-hr averaged) pollutant concentrations. This project applies the CPCB sub-index
formula directly to hourly values as an approximation for near-real-time AQI, and
separately computes true 24-hr averages in the gold layer (station_daily_aqi) which are
closer to the CPCB-intended averaging window. This tradeoff is called out explicitly in
the project report.
"""

# (C_low, C_high, I_low, I_high) breakpoints per pollutant
BREAKPOINTS = {
    "pm25": [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200),
             (91, 120, 201, 300), (121, 250, 301, 400), (251, 380, 401, 500)],
    "pm10": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200),
             (251, 350, 201, 300), (351, 430, 301, 400), (431, 520, 401, 500)],
    "no2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 180, 101, 200),
            (181, 280, 201, 300), (281, 400, 301, 400), (401, 520, 401, 500)],
    "so2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 380, 101, 200),
            (381, 800, 201, 300), (801, 1600, 301, 400), (1601, 2100, 401, 500)],
    "co": [(0, 1.0, 0, 50), (1.1, 2.0, 51, 100), (2.1, 10, 101, 200),
           (10.1, 17, 201, 300), (17.1, 34, 301, 400), (34.1, 50, 401, 500)],
    "o3": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 168, 101, 200),
           (169, 208, 201, 300), (209, 748, 301, 400), (749, 1000, 401, 500)],
}

# Physically-plausible max value per pollutant used for range validation (data-quality gate)
VALID_RANGE = {
    "pm25": (0, 1000), "pm10": (0, 1500), "no2": (0, 2000),
    "so2": (0, 3000), "co": (0, 100), "o3": (0, 1500),
}

CATEGORY_BOUNDS = [
    (0, 50, "Good"), (51, 100, "Satisfactory"), (101, 200, "Moderate"),
    (201, 300, "Poor"), (301, 400, "Very Poor"), (401, 500, "Severe"),
]


def is_valid_value(parameter: str, value: float) -> bool:
    if value is None or value < 0:
        return False
    bounds = VALID_RANGE.get(parameter)
    if not bounds:
        return True  # unknown parameter: don't reject, but it also won't get an AQI sub-index
    lo, hi = bounds
    return lo <= value <= hi


def sub_index(parameter: str, value: float) -> float | None:
    """Linear interpolation of concentration -> AQI sub-index for one pollutant."""
    table = BREAKPOINTS.get(parameter)
    if table is None or value is None or value < 0:
        return None
    for c_low, c_high, i_low, i_high in table:
        if c_low <= value <= c_high:
            return round(i_low + (i_high - i_low) / (c_high - c_low) * (value - c_low), 1)
    # above the top breakpoint: clamp to worst category's upper bound
    if value > table[-1][1]:
        return float(table[-1][3])
    return None


def category_for_aqi(aqi: float) -> str:
    for lo, hi, label in CATEGORY_BOUNDS:
        if lo <= aqi <= hi:
            return label
    return "Severe" if aqi > 500 else "Unknown"


def overall_aqi(sub_indices: dict) -> tuple[float | None, str | None]:
    """
    Overall AQI = max of available pollutant sub-indices (CPCB 'One Number - One Colour'
    approach), with the dominant pollutant being whichever produced that max.
    sub_indices: {parameter: sub_index_value}
    """
    valid = {p: v for p, v in sub_indices.items() if v is not None}
    if not valid:
        return None, None
    dominant = max(valid, key=valid.get)
    return valid[dominant], dominant
