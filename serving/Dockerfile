# Build from the project root: docker build -f serving/Dockerfile -t aqi-inference .
FROM python:3.12-slim

WORKDIR /app

COPY serving/requirements.txt /app/serving/requirements.txt
RUN pip install --no-cache-dir -r /app/serving/requirements.txt

# Only copy what the inference service actually needs (not ingestion/orchestration)
COPY ingestion/config.py /app/ingestion/config.py
COPY etl/db_utils.py /app/etl/db_utils.py
COPY etl/aqi_calculator.py /app/etl/aqi_calculator.py
COPY ml/build_features.py /app/ml/build_features.py
COPY serving/app.py /app/serving/app.py
COPY models/ /app/models/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "serving.app:app", "--host", "0.0.0.0", "--port", "8000"]
