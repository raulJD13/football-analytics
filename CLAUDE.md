# Football Analytics — Project Context

## What this project is
Data engineering + ML platform for football analytics (LaLiga focus).
Predicts match results using historical stats. Full pipeline:
API ingestion → MinIO → dbt → ClickHouse → FastAPI → React dashboard.

## Stack
- Orchestration: Apache Airflow (DAGs in /dags)
- Storage: MinIO — raw/ and refined/ prefixes (Parquet)
- Transformation: dbt (staging → intermediate → marts)
- Database: ClickHouse (OLAP)
- API: FastAPI + Python 3.11
- Frontend: React + TypeScript
- ML: scikit-learn / XGBoost + MLflow tracking
- Infra: Docker Compose (everything up with `docker compose up`)

## Data sources
- football-data.org (matches, standings, scorers) → FOOTBALL_API_KEY in .env
- API-Football (shots, possession)               → API_FOOTBALL_KEY in .env

## Key conventions
- All secrets in .env — never hardcode
- dbt models: stg_ / int_ / mart_ prefix strictly enforced
- Every dbt model needs schema.yml with description + at least 2 tests
- ClickHouse table names match dbt mart names exactly
- Python: type hints always, docstrings on public functions
- Commits: conventional commits (feat: / fix: / chore: / docs:)

## How to run
```bash
docker compose up -d
airflow dags trigger ingest_matches
dbt run && dbt test
```

## Docs (load on demand — do NOT load unless needed)
- @docs/architecture.md    — full pipeline diagram and decisions
- @docs/dbt-conventions.md — detailed dbt naming and testing rules
- @docs/api-reference.md   — football-data.org endpoints and payloads
- @docs/ml-model.md        — model features, training logic, MLflow setup
- @docs/progress.md        — task checklist with current status ← READ THIS FIRST
