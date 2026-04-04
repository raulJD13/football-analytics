# FastAPI

## Structure
api/
  main.py          # app setup, CORS, router includes
  routers/         # one file per domain
  schemas/         # Pydantic models
  db/              # ClickHouse connection helpers

## Conventions
- All endpoints return Pydantic schemas (not raw dicts)
- ClickHouse queries in db/ helpers, not inline in routers
- /predict endpoint calls MLflow model registry (production tag)
- Type hints on every function
