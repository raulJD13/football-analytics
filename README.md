# Football Analytics

Data engineering and ML platform for LaLiga match prediction. Ingests data from external football APIs, transforms it through a dbt pipeline into ClickHouse, and will serve predictions via a FastAPI + React frontend.

> **Status:** Phases 1–4 complete (infrastructure, ingestion, dbt, ML + FastAPI predict endpoint). Phases 5–6 (remaining FastAPI routes, frontend) are planned.

---

## Architecture

```
football-data.org API
  └─► Airflow DAG (daily 02:00)
        ├─► MinIO raw/  (Parquet, partitioned by date)  ← archive
        └─► ClickHouse football.raw_*  ← source for dbt
              └─► dbt staging → intermediate → marts
                    └─► ClickHouse football.*  (OLAP tables)
                          └─► FastAPI  ──► React dashboard  [planned]
                                └─► POST /predict
                                      └─► MLflow model registry
```

### Services

| Service | Image | Host port | Purpose |
|---|---|---|---|
| `airflow-webserver` | apache/airflow:2.9.0 | **8080** | DAG UI and triggering |
| `airflow-scheduler` | apache/airflow:2.9.0 | — | Runs DAGs on schedule |
| `postgres` | postgres:15 | — | Airflow metadata DB (internal only) |
| `minio` | minio/minio | **9000** (S3 API), **9001** (UI) | Object storage for raw Parquet files |
| `clickhouse` | clickhouse-server:24.3 | **8124** (HTTP), 9010 (native TCP) | OLAP database; dbt reads/writes here |
| `mlflow` | ghcr.io/mlflow/mlflow:v2.11.0 | **5001** | Experiment tracking and model registry |
| `fastapi` | _not yet implemented_ | 8000 | Prediction and stats API |
| `react` | _not yet implemented_ | 3000 | Dashboard frontend |

> **Port notes:** ClickHouse is on **8124** (not 8123) to avoid conflicts with other ClickHouse instances. MLflow is on **5001** (not 5000) to avoid macOS AirPlay Receiver. Inside Docker, services communicate on `clickhouse:8123` and `mlflow:5000`.

---

## Project structure

```
football-analytics/
├── dags/                         # Airflow DAGs
│   ├── ingest_matches.py         # LaLiga matches → MinIO + ClickHouse
│   └── ingest_standings.py       # LaLiga standings → MinIO + ClickHouse
│
├── dbt/                          # dbt project (run all commands from here)
│   ├── dbt_project.yml
│   ├── profiles.yml              # ClickHouse connection (localhost:8124)
│   └── models/
│       ├── staging/              # Cast + rename only; materialized as views
│       │   ├── sources.yml       # Declares raw_matches, raw_standings sources
│       │   ├── stg_matches.sql
│       │   ├── stg_teams.sql
│       │   └── schema.yml
│       ├── intermediate/         # Business logic; materialized as views
│       │   ├── int_team_match_results.sql  # Unpivots to 1 row/team/match
│       │   ├── int_form_last_5.sql         # Rolling form (5 prev matches)
│       │   └── schema.yml
│       └── marts/                # Final tables; MergeTree in ClickHouse
│           ├── mart_standings.sql
│           ├── mart_team_stats.sql         # Home vs away split + strength metrics
│           ├── mart_match_features.sql     # ML feature table
│           └── schema.yml
│
├── infra/
│   └── clickhouse/
│       └── init.sql              # DDL: creates football DB + raw_* tables on first start
│
├── scripts/
│   └── bootstrap_clickhouse.py  # Dev helper: load API data without Airflow
│
├── ml/
│   └── scripts/
│       └── train_poisson.py      # Poisson model training + MLflow registration
├── api/
│   ├── main.py                   # FastAPI app setup, CORS, lifespan
│   ├── routers/
│   │   └── predict.py            # POST /predict endpoint
│   └── schemas/
│       └── predict.py            # PredictRequest / PredictResponse
├── frontend/                     # Planned: React + TypeScript dashboard
│
├── docs/
│   ├── architecture.md
│   ├── api-reference.md          # football-data.org + API-Football endpoints
│   ├── dbt-conventions.md
│   ├── ml-model.md               # Poisson + XGBoost feature spec
│   └── progress.md               # Phase checklist
│
├── docker-compose.yml
├── .env                          # Local secrets (gitignored)
├── .env.example                  # Template
├── Makefile                      # Convenience wrappers (see below)
└── venv/                         # Python virtual environment
```

---

## External APIs

### football-data.org (primary)
- **Auth:** `X-Auth-Token` header → `FOOTBALL_API_KEY`
- **Rate limit:** 10 req/min on the free tier
- **Used for:**
  - `GET /competitions/PD/matches` — all LaLiga matches (current season)
  - `GET /competitions/PD/standings` — current classification table
  - `GET /competitions/PD/scorers` — top scorers _(DAG planned)_
- Competition codes: `PD` = LaLiga, `PL` = Premier League, `BL1` = Bundesliga, `SA` = Serie A

### API-Football (advanced stats, planned)
- **Auth:** `x-apisports-key` header → `API_FOOTBALL_KEY`
- **Rate limit:** 100 req/day on the free tier
- **Planned for:** shots, possession stats per fixture

---

## Environment variables

Copy `.env.example` to `.env` and fill in real values before starting:

```bash
cp .env.example .env
```

| Variable | Used by | Description |
|---|---|---|
| `FOOTBALL_API_KEY` | Airflow DAGs, bootstrap script | football-data.org API token |
| `API_FOOTBALL_KEY` | Planned DAGs | api-sports.io token |
| `MINIO_ROOT_USER` | MinIO, DAGs | MinIO admin username |
| `MINIO_ROOT_PASSWORD` | MinIO, DAGs | MinIO admin password |
| `MINIO_ENDPOINT` | DAGs (inside Docker) | `http://minio:9000` |
| `CLICKHOUSE_HOST` | DAGs (inside Docker) | `clickhouse` (service name) |
| `CLICKHOUSE_PORT` | Host-side tools | `8124` (host-mapped port) |
| `CLICKHOUSE_DB` | DAGs, ClickHouse init | `football` |
| `AIRFLOW__CORE__FERNET_KEY` | Airflow | Encryption key for secrets |
| `AIRFLOW__WEBSERVER__SECRET_KEY` | Airflow webserver | Session key |
| `AIRFLOW_ADMIN_PASSWORD` | Airflow init | Password for the `admin` UI user |
| `MLFLOW_TRACKING_URI` | DAGs, ML scripts | `http://mlflow:5000` (Docker-internal); host scripts use `http://localhost:5001` |

> **Note:** `CLICKHOUSE_HOST=clickhouse` and `MLFLOW_TRACKING_URI=http://mlflow:5000` are Docker-internal addresses for DAGs running inside the container network. Host-side tools (dbt, train script, API) use `localhost:8124` and `localhost:5001` respectively.

---

## Local setup

### Prerequisites
- Docker Desktop (or Docker Engine + Compose v2)
- Python 3.11+
- `make`

### One-time setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd football-analytics

# 2. Create Python venv and install dependencies
python3.12 -m venv venv
source venv/bin/activate
pip install dbt-clickhouse clickhouse-connect requests pandas pyarrow python-dotenv

# 3. Copy and fill in secrets
cp .env.example .env
# Edit .env: set FOOTBALL_API_KEY at minimum
```

---

## Running the stack

### Start everything

```bash
make up
# or: docker compose up -d
```

This starts all services in dependency order. `airflow-init` runs migrations and creates the `admin` user, then exits. `minio-init` creates the `raw/` and `refined/` buckets, then exits. ClickHouse runs `infra/clickhouse/init.sql` on first start to create the `football` database and raw tables.

Allow ~60 s for Airflow to become healthy. Check status:

```bash
docker compose ps
```

### Stop

```bash
make down
# or: docker compose down
```

---

## Data pipeline

### Step 1 — Seed initial data (dev only)

On a fresh install, the ClickHouse raw tables are empty. Use the bootstrap script to load the current season data directly from the API, bypassing Airflow:

```bash
make bootstrap
# or: source venv/bin/activate && python scripts/bootstrap_clickhouse.py
```

This fetches ~380 matches and 20 standings rows and inserts them into `football.raw_matches` / `football.raw_standings`. Respects the API rate limit with a 7 s pause between calls.

### Step 2 — Run dbt transformations

```bash
make dbt-run    # creates 7 models: 4 views + 3 MergeTree tables
make dbt-test   # runs 58 data quality tests
```

All commands run from the project root. The Makefile automatically changes to the `dbt/` subdirectory (where `dbt_project.yml` and `profiles.yml` live).

### Step 3 — Trigger Airflow DAGs (ongoing)

After the stack is up, open the Airflow UI at **http://localhost:8080** (user: `admin`, password: value of `AIRFLOW_ADMIN_PASSWORD` in `.env`, default `admin`).

Enable and trigger:
- `ingest_matches` — fetches all LaLiga matches for the current season
- `ingest_standings` — fetches the current classification table

Both DAGs run daily at 02:00 UTC. Each DAG:
1. Fetches data from football-data.org
2. Writes a Parquet snapshot to MinIO at `raw/{source}/{YYYY-MM-DD}/data.parquet`
3. Inserts rows into the ClickHouse raw table

After a DAG run, re-run dbt to refresh the marts:

```bash
make dbt-run && make dbt-test
```

---

## dbt models

| Layer | Model | Materialization | Description |
|---|---|---|---|
| staging | `stg_matches` | view | Finished matches only; ISO 8601 dates parsed with `parseDateTimeBestEffort` |
| staging | `stg_teams` | view | Unique teams derived from match participants |
| intermediate | `int_team_match_results` | view | Unpivots matches → 1 row per team per match with W/D/L and points |
| intermediate | `int_form_last_5` | view | Rolling 5-match form using `ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING` (no data leakage) |
| mart | `mart_standings` | MergeTree table | Current season standings computed from match results |
| mart | `mart_team_stats` | MergeTree table | Home/away stats split + attack strength and defence weakness ratios |
| mart | `mart_match_features` | MergeTree table | One row per match with all ML features pre-joined |

### ClickHouse-specific conventions

- Use `toDate(parseDateTimeBestEffort(col))` for ISO 8601 datetime strings from the API (not plain `toDate()`)
- Use `toFloat64()` for decimal metrics
- MergeTree `ORDER BY` must use non-nullable columns; avoid column names that also appear in window function `ORDER BY` clauses inside referenced views (ClickHouse 24.3 DDL resolution bug)
- See `docs/dbt-conventions.md` for full conventions

### Running dbt commands

```bash
make dbt-debug    # verify ClickHouse connection
make dbt-compile  # compile Jinja → SQL without executing
make dbt-run      # run all models
make dbt-test     # run all 58 data quality tests
make dbt-docs     # generate + serve docs at http://localhost:8080
```

---

## ML model — Poisson predictor

**Level 1 — Poisson model** (`ml/scripts/train_poisson.py`)

Goals scored by each side are modelled as independent Poisson random variables:

```
λ_home = home_attack × away_defence × HOME_ADVANTAGE(1.2) × league_avg_goals
λ_away = away_attack × home_defence × league_avg_goals
```

P(H/D/A) is computed by summing the joint PMF over an 11×11 goal grid (0–10 goals).

Training reads from `mart_team_stats` and `mart_match_features`. Metrics are logged to MLflow and the model artifact is registered as `poisson-match-predictor` with the `Production` alias.

```bash
# Retrain (requires MLflow + ClickHouse running)
venv/bin/python ml/scripts/train_poisson.py
# Optional flags: --ch-host, --ch-port, --mlflow-uri
```

**Current performance on 293 LaLiga matches:**
| Metric | Value |
|---|---|
| Accuracy | 54.6% |
| Baseline (always home win) | 48.8% |
| Baseline (most frequent) | 48.8% |

MLflow UI: **http://localhost:5001** · Experiment: `football-match-prediction`

**Level 2 — XGBoost classifier** (`ml/scripts/train_classifier.py`, planned)
- Target: `result ∈ {H, D, A}`
- Input features from `mart_match_features`: form, attack/defence strength, h2h win rate, rest days, position diff

---

## API

### Start the API server

```bash
venv/bin/uvicorn api.main:app --reload --port 8000
```

The server loads the `Production` model from MLflow at startup. If MLflow is unreachable it will refuse to start.

### Endpoints

#### `GET /health`
```json
{"status": "ok"}
```

#### `POST /predict`
Predict outcome probabilities for a LaLiga fixture.

Request:
```json
{"home_team_id": 86, "away_team_id": 81}
```

Response:
```json
{
  "home_team_id": 86,
  "away_team_id": 81,
  "home_win": 0.5831,
  "draw": 0.2574,
  "away_win": 0.1595,
  "expected_home_goals": 1.526,
  "expected_away_goals": 0.657,
  "model_version": "1"
}
```

Team IDs are `football-data.org` identifiers. Unknown team IDs fall back to league-average strength (graceful degradation, no error).

---

## Makefile reference

```
make up           Start all Docker services
make down         Stop all Docker services
make bootstrap    Seed ClickHouse with live API data (dev only)
make dbt-debug    Verify dbt → ClickHouse connection
make dbt-compile  Compile models (no DB writes)
make dbt-run      Run all dbt models
make dbt-test     Run all 58 dbt data quality tests
make dbt-docs     Generate and serve dbt documentation
```

### Full pipeline (dev)

```bash
make up                                   # 1. start stack
make bootstrap                            # 2. seed data
make dbt-run && make dbt-test             # 3. build mart tables
venv/bin/python ml/scripts/train_poisson.py  # 4. train + register model
venv/bin/uvicorn api.main:app --port 8000    # 5. start API
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"home_team_id": 86, "away_team_id": 81}'
```

---

## Troubleshooting

### `dbt debug` fails — cannot connect to ClickHouse
```
Connection test: ERROR
```
The ClickHouse container is not running or is still starting.
```bash
docker compose up -d clickhouse
docker compose ps clickhouse       # wait for "healthy"
```
If port 8124 is already in use, another process is on that port. Check with `lsof -i :8124`.

### `dbt run` — `football.raw_matches` does not exist
The ClickHouse raw tables were not created. This means either:
- ClickHouse was started before the `infra/clickhouse/init.sql` volume mount was in place (the init script only runs on a **fresh** data volume)
- Solution: delete the volume and restart, or run the DDL manually:
```bash
docker compose down -v             # destroys data — dev only
docker compose up -d clickhouse
```

### `football.raw_matches` is empty — dbt models produce no rows
The raw tables exist but have no data. Run the bootstrap script:
```bash
make bootstrap
```

### Airflow DAG fails — `ModuleNotFoundError`
The Airflow workers install `pandas pyarrow boto3 clickhouse-connect` via `_PIP_ADDITIONAL_REQUIREMENTS` on every container start. On a slow network this can time out. Restart the scheduler:
```bash
docker compose restart airflow-scheduler
```

### ClickHouse port conflict (8124 or 9010 already in use)
Another project is occupying these ports. Either stop the conflicting containers, or change the ports in `docker-compose.yml` and update `dbt/profiles.yml` and `.env` to match.

### `dbt test` — `not_null` failures on `mart_match_features`
This usually means some matches have no form history yet (first matches of the season). The `form_points_last_5` column defaults to 0 for those rows. Verify with:
```bash
curl "http://localhost:8124/?database=football&query=SELECT+count()+FROM+football.raw_matches+WHERE+status='FINISHED'"
```
If the count is low (< 5 matches), there is not enough history for form calculation.

---

## Known limitations

| Area | Limitation |
|---|---|
| **Data coverage** | Only LaLiga (competition code `PD`) is ingested. Other leagues require adding DAGs. |
| **API rate limit** | football-data.org free tier: 10 req/min. The bootstrap script adds a 7 s delay between calls. Burst usage can trigger 429 errors. |
| **Standings source** | `mart_standings` is derived from match results, not from the standings API snapshot. It will differ slightly from the official table if points deductions or administrative decisions exist. |
| **XGBoost not yet trained** | `mart_match_features` is ready but `ml/scripts/train_classifier.py` is not yet implemented. |
| **No frontend** | `frontend/` is an empty stub. React dashboard is planned for Phase 6. |
| **Airflow slow start** | `_PIP_ADDITIONAL_REQUIREMENTS` installs packages on every container start (~2 min on first run). Consider building a custom image for faster restarts. |
| **MLflow local storage** | MLflow uses SQLite + local artifacts (served via `--serve-artifacts`). Not suitable for multi-user or production use without switching to a shared backend. |
| **ClickHouse MergeTree dedup** | Raw tables use `ReplacingMergeTree`. Deduplication happens asynchronously during background merges, not immediately on insert. Use `FINAL` keyword in queries if exact dedup is needed. |
| **dbt ORDER BY bug (ClickHouse 24.3)** | `mart_match_features` uses `ORDER BY tuple()` because naming any column that appears in a window function ORDER BY inside a referenced view causes `UNKNOWN_IDENTIFIER` during DDL. |

---

## Roadmap

See `docs/progress.md` for the detailed checklist. Remaining work:

- **Phase 2:** `dags/ingest_scorers.py`, `dags/ingest_advanced_stats.py` (API-Football)
- **Phase 3:** `staging/stg_goals.sql`, `intermediate/int_h2h.sql`; configure Airflow connections in UI
- **Phase 4 (partial):** XGBoost training script (`train_classifier.py`), weekly retrain DAG
- **Phase 5:** FastAPI — `/standings`, `/teams` endpoints
- **Phase 6:** React dashboard — standings table, form widget, match prediction, xG chart
