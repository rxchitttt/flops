#!/bin/bash
# Runs once, on first container start, before 02_schema.sql.
# The default POSTGRES_DB (aqi_dw) is created automatically by the postgres image;
# this script additionally creates a separate database for Airflow's own metadata,
# so Airflow's internal tables never mix with our analytical schemas.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    CREATE DATABASE airflow_meta;
EOSQL
