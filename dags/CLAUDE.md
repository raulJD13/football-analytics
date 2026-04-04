# Airflow DAGs

## Style
- Use TaskFlow API (@task decorator), no classic operators
- One DAG = one data source
- DAG id matches filename (ingest_matches → ingest_matches.py)

## Connections (configured in Airflow UI)
- clickhouse_default  → ClickHouse on port 8123
- minio_default       → MinIO on port 9000
- football_api        → football-data.org (token in .env)

## Schedule
- Ingestion DAGs: "0 2 * * *"  (daily at 02:00)
- Retrain DAG:    "0 3 * * 1"  (every Monday at 03:00)

## MinIO paths
- raw/{source}/{YYYY-MM-DD}/data.parquet
- refined/{table_name}/data.parquet

## Error handling
- retries=3, retry_delay=timedelta(minutes=5)
- On failure: alert via email (configure in Airflow)
