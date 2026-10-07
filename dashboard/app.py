"""
Streamlit dashboard for the AQI Analysis project (Part 1).
Reads only from the gold-layer marts and meta.ingestion_log - never touches raw/staging.

Run: streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from config import CITY_NAME, POSTGRES_DSN  # noqa: E402

st.set_page_config(page_title=f"{CITY_NAME} AQI Dashboard", layout="wide")

AQI_COLORS = {
    "Good": "#2ecc71", "Satisfactory": "#a3d977", "Moderate": "#f1c40f",
    "Poor": "#e67e22", "Very Poor": "#e74c3c", "Severe": "#8e44ad",
}


@st.cache_resource
def get_engine():
    return create_engine(POSTGRES_DSN, pool_pre_ping=True)


@st.cache_data(ttl=300)
def load_data():
    engine = get_engine()
    hourly = pd.read_sql("SELECT * FROM gold.station_hourly_aqi ORDER BY observed_at_utc", engine)
    daily = pd.read_sql("SELECT * FROM gold.station_daily_aqi ORDER BY observation_date", engine)
    city_daily = pd.read_sql("SELECT * FROM gold.city_daily_aqi ORDER BY observation_date", engine)
    contribution = pd.read_sql("SELECT * FROM gold.pollutant_contribution_daily", engine)
    try:
        ingestion_log = pd.read_sql(
            "SELECT * FROM meta.ingestion_log ORDER BY extracted_at_utc DESC LIMIT 50", engine)
    except Exception:
        ingestion_log = pd.DataFrame()
    return hourly, daily, city_daily, contribution, ingestion_log


st.title(f"🌫️ {CITY_NAME} Air Quality Index — Analysis Dashboard")
st.caption("Data Engineering & MLOps Project — Part 1 (Pipeline & Analytics)")

hourly, daily, city_daily, contribution, ingestion_log = load_data()

if hourly.empty:
    st.warning(
        "No data in the gold layer yet. Run the pipeline first: "
        "`python scripts/run_pipeline.py` (or trigger the Airflow DAG), then refresh."
    )
    st.stop()

stations = sorted(hourly["station_name"].dropna().unique())
selected_stations = st.sidebar.multiselect("Stations", stations, default=stations)
date_min, date_max = daily["observation_date"].min(), daily["observation_date"].max()
date_range = st.sidebar.date_input("Date range", (date_min, date_max), min_value=date_min, max_value=date_max)

f_hourly = hourly[hourly["station_name"].isin(selected_stations)]
f_daily = daily[daily["station_name"].isin(selected_stations)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    f_daily = f_daily[(f_daily["observation_date"] >= date_range[0]) &
                       (f_daily["observation_date"] <= date_range[1])]

latest = f_daily.sort_values("observation_date").groupby("station_name").tail(1)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations tracked", len(stations))
c2.metric("Latest avg AQI", f"{latest['avg_aqi'].mean():.0f}" if not latest.empty else "—")
c3.metric("Days of data", f_daily["observation_date"].nunique())
c4.metric("Records (hourly)", len(f_hourly))

st.divider()

# 1. AQI trend by date and station
st.subheader("1️⃣ AQI Trend by Date and Station")
fig1 = px.line(f_daily, x="observation_date", y="avg_aqi", color="station_name", markers=True)
fig1.update_layout(yaxis_title="Average AQI", xaxis_title="Date")
st.plotly_chart(fig1, use_container_width=True)

# 2. Pollutant contribution analysis
st.subheader("2️⃣ Pollutant Contribution Analysis")
if not contribution.empty:
    contrib_avg = contribution.groupby("parameter")["contribution_pct"].mean().reset_index()
    fig2 = px.pie(contrib_avg, names="parameter", values="contribution_pct",
                  title="Average contribution to overall AQI by pollutant")
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("Not enough data yet to compute pollutant contribution.")

# 3. City/station comparison
st.subheader("3️⃣ Station Comparison (Average AQI)")
comp = f_daily.groupby("station_name")["avg_aqi"].mean().reset_index().sort_values("avg_aqi")
fig3 = px.bar(comp, x="station_name", y="avg_aqi", color="avg_aqi",
              color_continuous_scale="RdYlGn_r")
fig3.update_layout(yaxis_title="Average AQI", xaxis_title="Station")
st.plotly_chart(fig3, use_container_width=True)

# 4. Hourly and monthly AQI patterns
st.subheader("4️⃣ Hourly & Monthly AQI Patterns")
h1, h2 = st.columns(2)
with h1:
    tmp = f_hourly.copy()
    tmp["hour"] = pd.to_datetime(tmp["observed_at_utc"]).dt.hour
    hourly_pattern = tmp.groupby("hour")["aqi"].mean().reset_index()
    fig4a = px.line(hourly_pattern, x="hour", y="aqi", markers=True, title="Average AQI by hour of day")
    st.plotly_chart(fig4a, use_container_width=True)
with h2:
    tmp2 = f_daily.copy()
    tmp2["month"] = pd.to_datetime(tmp2["observation_date"]).dt.to_period("M").astype(str)
    monthly_pattern = tmp2.groupby("month")["avg_aqi"].mean().reset_index()
    fig4b = px.bar(monthly_pattern, x="month", y="avg_aqi", title="Average AQI by month")
    st.plotly_chart(fig4b, use_container_width=True)

# 5. Weather impact on AQI
st.subheader("5️⃣ Weather Impact on AQI")
w1, w2 = st.columns(2)
with w1:
    fig5a = px.scatter(f_hourly, x="temperature_c", y="aqi", color="aqi_category",
                       color_discrete_map=AQI_COLORS, trendline="ols",
                       title="Temperature vs. AQI")
    st.plotly_chart(fig5a, use_container_width=True)
with w2:
    fig5b = px.scatter(f_hourly, x="wind_speed_ms", y="aqi", color="aqi_category",
                       color_discrete_map=AQI_COLORS, trendline="ols",
                       title="Wind speed vs. AQI")
    st.plotly_chart(fig5b, use_container_width=True)

st.divider()
with st.expander("🛠️ Pipeline health (ingestion log)"):
    if ingestion_log.empty:
        st.info("No ingestion log synced yet. Run scripts/run_pipeline.py.")
    else:
        st.dataframe(ingestion_log, use_container_width=True)

st.divider()
st.header("🤖 Part 2 — AQI Forecast & Model Monitoring")
engine = get_engine()
try:
    predictions_log = pd.read_sql(
        "SELECT * FROM meta.predictions_log ORDER BY predicted_at_utc DESC LIMIT 100", engine)
    model_monitoring = pd.read_sql(
        "SELECT * FROM meta.model_monitoring ORDER BY checked_at_utc DESC LIMIT 100", engine)
except Exception:
    predictions_log, model_monitoring = pd.DataFrame(), pd.DataFrame()

pcol1, pcol2 = st.columns(2)
with pcol1:
    st.subheader("Predicted vs. Actual AQI")
    resolved = predictions_log.dropna(subset=["actual_aqi"]) if not predictions_log.empty else predictions_log
    if resolved.empty:
        st.info("No resolved predictions yet — call the FastAPI /predict endpoint and let "
                "monitoring/monitor.py backfill actuals once the target date has passed.")
    else:
        fig6 = px.scatter(resolved, x="predicted_aqi", y="actual_aqi", color="station_id",
                          title="Predicted vs. actual next-day AQI")
        fig6.add_shape(type="line", x0=0, y0=0, x1=500, y1=500, line=dict(dash="dash", color="gray"))
        st.plotly_chart(fig6, use_container_width=True)

with pcol2:
    st.subheader("Model Monitoring Status")
    if model_monitoring.empty:
        st.info("No monitoring runs yet. Run `python monitoring/monitor.py`.")
    else:
        status_counts = model_monitoring.groupby(["check_type", "status"]).size().reset_index(name="count")
        fig7 = px.bar(status_counts, x="check_type", y="count", color="status",
                      color_discrete_map={"OK": "#2ecc71", "WARN": "#f1c40f", "ALERT": "#e74c3c"},
                      title="Monitoring checks by status (last 100 runs)")
        st.plotly_chart(fig7, use_container_width=True)
        st.dataframe(model_monitoring.head(20), use_container_width=True)

with st.expander("🔮 Try a live prediction (calls the FastAPI service on localhost:8000)"):
    station_options = sorted(f_hourly["station_id"].dropna().unique())
    chosen = st.selectbox("Station ID", station_options) if station_options else None
    if st.button("Predict tomorrow's AQI") and chosen:
        try:
            import requests
            resp = requests.post("http://localhost:8000/predict", json={"station_id": chosen}, timeout=10)
            if resp.ok:
                st.json(resp.json())
            else:
                st.error(f"API returned {resp.status_code}: {resp.text}")
        except Exception as exc:
            st.error(f"Could not reach FastAPI service at localhost:8000 — is it running? ({exc})")
