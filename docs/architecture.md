# Architecture

## Pipeline overview
football-data.org API
  └─► Airflow DAG (daily 02:00)
        └─► MinIO raw/  (Parquet, partitioned by date)
              └─► dbt staging → intermediate → marts
                    └─► ClickHouse (OLAP)
                          └─► FastAPI  ──► React dashboard
                                └─► /predict endpoint
                                      └─► MLflow model registry

## MinIO bucket structure
raw/
  matches/{YYYY-MM-DD}/data.parquet
  standings/{YYYY-MM-DD}/data.parquet
  goals/{YYYY-MM-DD}/data.parquet
refined/
  (dbt writes here after transformation)

## ClickHouse tables (match dbt mart names)
- mart_standings
- mart_team_stats
- mart_match_features

## Ports (docker compose)
- Airflow UI:   8080
- MinIO UI:     9001
- ClickHouse:   8123
- MLflow UI:    5000
- FastAPI:      8000
- React dev:    3000
