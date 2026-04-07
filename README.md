# Football Analytics

Data engineering and ML platform for football match prediction. Historical data flows from football-data.org and API-Football through Airflow + dbt into ClickHouse, powering Poisson and XGBoost models served via FastAPI and a Next.js dashboard.

> **Status:** All six phases complete. Single-command deployment via Docker Compose. Current cleaned out-of-sample XGBoost accuracy: **55.9%** vs **49.0%** home-win baseline.

---

## Architecture

```
football-data.org + API-Football  (current multi-season window)
  └─► Airflow DAGs
        ├─► MinIO  raw/   (Parquet archive, partitioned by date)
        └─► ClickHouse  football.raw_*
              └─► dbt  staging → intermediate → marts
                    └─► ClickHouse  football.mart_*  (OLAP)
                          └─► FastAPI  (port 8001)
                                ├─► POST /predict  ──► MLflow ensemble registry
                                ├─► GET  /fixtures · /standings · /model/metrics
                                └─► GET  /teams/{id}/stats · /form · /xg
                                          └─► Next.js dashboard  (port 3001)
```

---

## Services

| Service | Image | Host port | Purpose |
|---|---|---|---|
| `airflow-webserver` | _(custom Airflow image)_ | **8080** | DAG UI |
| `airflow-scheduler` | _(custom Airflow image)_ | — | Runs DAGs on schedule |
| `postgres` | postgres:15 | — | Airflow metadata DB |
| `mlflow-postgres` | postgres:15 | — | MLflow backend store |
| `minio` | minio/minio | **9000** (S3), **9001** (UI) | Raw Parquet archive |
| `clickhouse` | clickhouse-server:24.3 | **8124** (HTTP) | OLAP database |
| `mlflow` | ghcr.io/mlflow/mlflow:v2.11.0 | **5001** | Experiment tracking + model registry |
| `db-init` | _(project image)_ | — | One-shot: bootstrap data + dbt run |
| `trainer` | _(project image)_ | — | One-shot: train Poisson + XGBoost + ensemble |
| `api` | _(project image)_ | **8001** | FastAPI prediction and stats API |
| `frontend` | _(Node 20)_ | **3001** | Next.js React dashboard |

> **Port notes:** ClickHouse on **8124** (not 8123) and MLflow on **5001** (not 5000) avoid common host conflicts. Inside Docker, services communicate on `clickhouse:8123` and `mlflow:5000`.

---

## Quick start — single command

```bash
cp .env.example .env          # fill in FOOTBALL_API_KEY at minimum
docker compose up -d
```

Docker Compose runs the services in dependency order:

1. Infrastructure (ClickHouse, MLflow, MinIO) starts and becomes healthy
2. `db-init` bootstraps ClickHouse with 3 seasons of data and runs `dbt run && dbt test`
3. `trainer` trains Poisson → XGBoost → ensemble and registers all three in MLflow
4. `api` starts and loads the ensemble from MLflow
5. `frontend` builds and starts Next.js

Open **http://localhost:3001** once all services are healthy (~3–5 min on first run, faster after image build cache warms).

---

## Local development setup

```bash
# Python environment
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# macOS only — XGBoost needs OpenMP
brew install libomp

# Start infrastructure only (skip api/frontend containers)
docker compose up -d clickhouse mlflow minio airflow-webserver airflow-scheduler postgres

# Seed data (3 seasons)
python scripts/bootstrap_clickhouse.py --seasons 2023 2024 2025

# Transform
cd dbt && dbt run && dbt test

# Train
python ml/scripts/train_poisson.py
python ml/scripts/train_classifier.py
python ml/scripts/ensemble.py

# API
PYTHONPATH=. uvicorn api.main:app --port 8001 --reload

# Frontend
cd frontend && npm install && npm run dev    # http://localhost:3001
```

---

## Project structure

```
football-analytics/
├── dags/                              # Airflow DAGs
│   ├── ingest_matches.py              # League fixtures/results → MinIO + ClickHouse
│   ├── ingest_standings.py            # Standings snapshots → MinIO + ClickHouse
│   ├── ingest_advanced_stats.py       # API-Football xG / possession / shots
│   ├── ingest_scorers.py              # Top scorers snapshots
│   ├── run_dbt_transformations.py     # dbt run/test after ingestions
│   └── retrain_model.py               # Weekly retraining DAG
│
├── dbt/                               # dbt project
│   ├── profiles.yml                   # Reads CLICKHOUSE_HOST/PORT/DB from env
│   └── models/
│       ├── staging/                   # Cast + rename only (views)
│       │   ├── stg_matches.sql        # Finished matches, ISO dates parsed
│       │   ├── stg_advanced_stats.sql # Match-level xG / possession / shots
│       │   └── stg_teams.sql          # Unique teams from match participants
│       ├── intermediate/              # Business logic (views)
│       │   ├── int_team_match_results.sql   # 1 row per team per match (W/D/L, pts)
│       │   ├── int_standings_snapshot.sql   # Matchday-accurate standings snapshots
│       │   └── int_h2h.sql                  # Head-to-head aggregates
│       └── marts/                     # Final tables (MergeTree)
│           ├── mart_standings.sql           # League + season-aware standings
│           ├── mart_team_stats.sql          # Season-aware team strengths
│           └── mart_match_features.sql      # ML feature table (all features pre-joined)
│
├── ml/
│   └── scripts/
│       ├── train_poisson.py           # Season-weighted Poisson baseline
│       ├── train_classifier.py        # XGBoost: Elo + xG + calibration + SMOTE
│       ├── benchmark_classifiers.py   # XGBoost vs CatBoost vs FT-Transformer benchmark
│       └── ensemble.py                # Weight grid search; registers best combo
│
├── api/
│   ├── main.py                        # FastAPI app, CORS, lifespan
│   ├── routers/
│   │   ├── predict.py                 # POST /predict  (ensemble or Poisson fallback)
│   │   ├── fixtures.py                # GET  /fixtures · /fixtures/{id}
│   │   ├── model.py                   # GET  /model/metrics
│   │   ├── standings.py               # GET  /standings
│   │   └── teams.py                   # GET  /teams/{id}/stats · /form
│   ├── schemas/                       # Pydantic request/response models
│   └── db/
│       ├── clickhouse.py              # Client factory (reads env vars)
│       ├── standings.py               # ClickHouse queries for standings
│       ├── teams.py                   # ClickHouse queries for team stats/form
│       └── predict_features.py        # Live feature assembly for XGBoost at inference
│
├── frontend/                          # Next.js 16 + TypeScript + Tailwind v4
│   ├── app/
│   │   ├── overview/                  # KPIs + live model metrics + standings snapshot
│   │   ├── fixtures/                  # Live matchday prediction grid
│   │   ├── matches/[id]/              # Match detail, H2H, form, explanation
│   │   ├── predictions/               # Team selector + POST /predict + explanation
│   │   ├── standings/                 # Full table with form dots + projected points
│   │   ├── teams/[id]/                # Home/away cards + xG accumulated chart
│   │   └── model/                     # Accuracy/Brier/log-loss KPIs + feature chart
│   └── Dockerfile                     # Multi-stage build: deps → build → runner
│
├── scripts/
│   └── bootstrap_clickhouse.py        # Load 1–3 seasons from API without Airflow
│
├── infra/
│   └── clickhouse/
│       └── init.sql                   # DDL: football DB + raw_* tables (ReplacingMergeTree)
│
├── docs/
│   ├── architecture.md
│   ├── api-reference.md               # football-data.org + API-Football endpoints
│   ├── dbt-conventions.md
│   ├── ml-model.md                    # Model features, training logic, MLflow setup
│   └── progress.md                    # Phase checklist
│
├── Dockerfile                         # Python image for api / db-init / trainer
├── docker-compose.yml                 # Full stack (single command deploy)
├── requirements.txt                   # All Python deps (pinned)
├── .env.example                       # Secrets template
└── Makefile                           # Convenience wrappers
```

---

## Data pipeline

### Seasons available

football-data.org free tier gives access to the recent seasons used here, and the project now supports multiple leagues (`PD`, `PL`, `SA`, `BL1`) plus API-Football advanced stats:

| `--seasons` arg | Season | Matches |
|---|---|---|
| `2023` | 2023/24 | 380 |
| `2024` | 2024/25 | 380 |
| `2025` | 2025/26 (current) | 380 (season in progress / mixed statuses depending on snapshot date) |

```bash
# Add a new season (e.g. after the window opens each August):
python scripts/bootstrap_clickhouse.py --seasons 2025
# ReplacingMergeTree deduplicates on match_id automatically
```

### dbt models

| Layer | Model | Materialization | Description |
|---|---|---|---|
| staging | `stg_matches` | view | Finished matches; ISO 8601 dates via `parseDateTimeBestEffort` |
| staging | `stg_teams` | view | Unique teams from match participants |
| intermediate | `int_team_match_results` | view | Unpivots matches → 1 row/team/match |
| intermediate | `int_form_last_5` | view | Rolling 5-match form (window excludes current match) |
| intermediate | `int_standings_snapshot` | view | Matchday-accurate standings snapshots |
| intermediate | `int_h2h` | view | Materialised head-to-head history |
| mart | `mart_standings` | MergeTree | League + season-aware standings computed from results |
| mart | `mart_team_stats` | MergeTree | Season-aware home/away averages + strength ratios |
| mart | `mart_match_features` | MergeTree | One row/match: all ML features pre-joined, no leakage in form or standings |

---

## ML models

All models follow a **temporal evaluation setup**. After fixing season contamination and standings leakage, the current reported numbers come from cleaned temporal folds over the available seasons.

### Poisson model (`train_poisson.py`)

```
λ_home = attack_home × defence_away × HOME_ADVANTAGE(1.2) × league_avg_goals
λ_away = attack_away × defence_home × league_avg_goals
```

P(H/D/A) computed by summing the joint PMF over an 11×11 goal grid.  
Registered in MLflow as `poisson-match-predictor` · alias `Production`.

| Metric | Value (current holdout) |
|---|---|
| Accuracy | 48.8% |
| Baseline (home win) | 49.0% |
| Brier score | 0.602 |

### XGBoost classifier (`train_classifier.py`)

Multi-class classifier with `TimeSeriesSplit(n_splits=3)` — no random shuffling, no future leakage. The pipeline includes Elo, API-Football advanced stats, Optuna tuning, draw-focused SMOTE, and Platt scaling calibration.

**Features** (16 total):

| Feature | Description |
|---|---|
| `home_form_5_ppg` | Home team points-per-game in last 5 matches |
| `away_form_5_ppg` | Away team points-per-game in last 5 matches |
| `home_xg_for_avg_last_5` | Home team average xG in last 5 matches |
| `away_xg_for_avg_last_5` | Away team average xG in last 5 matches |
| `xg_diff` | Home xG rolling average minus away xG rolling average |
| `shots_on_target_diff` | Rolling shots-on-target differential |
| `possession_diff` | Rolling possession differential |
| `home_attack_strength` | Home avg goals scored / league avg |
| `away_defence_weakness` | Away avg goals conceded / league avg |
| `home_elo_diff` | Pre-match home Elo minus away Elo |
| `h2h_home_win_rate` | Historical H2H win rate for home team |
| `h2h_matches_played` | H2H sample size (reliability proxy) |
| `home_rest_days` | Days since home team's last match (capped at 14) |
| `away_rest_days` | Days since away team's last match (capped at 14) |
| `rest_days_diff` | `home_rest_days − away_rest_days` |
| `position_diff` | Matchday snapshot home position − away position |

Registered as `xgboost-match-classifier` · alias `Production`.

| Metric | Value |
|---|---|
| CV accuracy (mean ± std) | 50.4% ± 3.4% |
| Accuracy — last fold | **55.9%** |
| Brier — last fold | 0.558 |
| Baseline — last fold | 49.0% |

**Feature importance (gain):**

| Rank | Feature | Weight |
|---|---|---|
| 1 | `h2h_home_win_rate` | 39.9% |
| 2 | `position_diff` | 9.5% |
| 3 | `h2h_matches_played` | 7.8% |
| 4 | `away_defence_weakness` | 7.4% |
| 5 | `home_attack_strength` | 6.3% |

### Ensemble (`ensemble.py`)

Grid search over `(w_poisson, w_xgb)` pairs with a calibration guard.  
Current best combo on the cleaned evaluation is still effectively **XGBoost only** — blending with Poisson worsens calibration.

Registered as `ensemble-match-predictor` · alias `Production`.

---

## API endpoints

Start the server:
```bash
PYTHONPATH=. uvicorn api.main:app --port 8001
```

Loads the ensemble from MLflow at startup. Falls back to Poisson if ensemble is not registered.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe → `{"status": "ok"}` |
| `POST` | `/predict` | P(home win / draw / away win) + expected goals |
| `POST` | `/predict/explain` | Prediction plus per-feature contribution summary |
| `GET` | `/fixtures` | Current-season fixtures with live probabilities |
| `GET` | `/fixtures/{id}` | Match detail, H2H, form, explanation |
| `GET` | `/standings` | Full LaLiga table with projected points and form strings |
| `GET` | `/model/metrics` | Live registered-model metrics from MLflow |
| `GET` | `/teams/{id}/stats` | Home/away split: goals, points, clean sheets, strength |
| `GET` | `/teams/{id}/form` | Last N matches with result, score, opponent |
| `GET` | `/teams/{id}/xg` | Accumulated xG/xGA series |

#### `POST /predict` example

```bash
curl -X POST http://localhost:8001/predict \
  -H "Content-Type: application/json" \
  -d '{"home_team_id": 86, "away_team_id": 81}'
```

```json
{
  "home_team_id": 86,
  "away_team_id": 81,
  "home_win": 0.583,
  "draw": 0.257,
  "away_win": 0.160,
  "expected_home_goals": 1.526,
  "expected_away_goals": 0.657,
  "model_version": "ensemble-v3"
}
```

Interactive docs: **http://localhost:8001/docs**

---

## Frontend pages

| Path | Content |
|---|---|
| `/overview` | Season KPIs, top predictions, standings snapshot, live model metrics |
| `/fixtures` | Full matchday prediction grid with live probabilities |
| `/predictions` | Interactive team selector, probability bars, feature explanations |
| `/matches/[id]` | Fixture detail, H2H, recent form, model explanation |
| `/standings` | Full table with form dots (W/D/L), points, projected final points |
| `/teams/[id]` | Home vs away stat cards, strength metrics, last matches, accumulated xG |
| `/model` | Accuracy / Brier / log-loss KPIs, feature importance bar chart |

---

## Environment variables

```bash
cp .env.example .env
```

| Variable | Used by | Notes |
|---|---|---|
| `FOOTBALL_API_KEY` | bootstrap script, Airflow DAGs | football-data.org token (required) |
| `API_FOOTBALL_KEY` | planned DAGs | api-sports.io token |
| `MINIO_ROOT_USER` | MinIO, DAGs | MinIO admin user |
| `MINIO_ROOT_PASSWORD` | MinIO, DAGs | MinIO admin password |
| `CLICKHOUSE_HOST` | Docker services | `clickhouse` inside Docker, `localhost` on host |
| `CLICKHOUSE_PORT` | Host-side tools | `8124` (host-mapped) |
| `CLICKHOUSE_DB` | All | `football` |
| `MLFLOW_TRACKING_URI` | Docker services | `http://mlflow:5000` inside Docker |
| `AIRFLOW__CORE__FERNET_KEY` | Airflow | Encryption key |
| `AIRFLOW__WEBSERVER__SECRET_KEY` | Airflow | Session key |
| `AIRFLOW_ADMIN_PASSWORD` | Airflow | Default: `admin` |

---

## Makefile reference

```
make up              Start all Docker services
make down            Stop all Docker services
make bootstrap       Seed ClickHouse for current season (no Airflow)
make dbt-run         Run all 7 dbt models
make dbt-test        Run all data quality tests
make dbt-docs        Generate + serve dbt docs at localhost:8080
```

---

## Troubleshooting

**ClickHouse connection refused**
```bash
docker compose up -d clickhouse && docker compose ps clickhouse   # wait for "healthy"
```

**`raw_matches` is empty after `docker compose up`**  
The `db-init` service exits non-zero (check logs). Re-run manually:
```bash
docker compose run --rm db-init bash -c "python scripts/bootstrap_clickhouse.py --host clickhouse --port 8123 --seasons 2023 2024 2025"
```

**XGBoost import fails on macOS**
```bash
brew install libomp
```

**MLflow artifact write fails**  
Delete the old `mlflow_data` volume (it was created before `--serve-artifacts` was added):
```bash
docker compose down -v && docker compose up -d mlflow
```

**HMR WebSocket reload loop in Next.js dev**  
Always start the dev server with `--hostname 127.0.0.1` (already set in `package.json`). Accessing the app from a LAN IP causes HMR to use that IP for WebSocket connections, which fail after 12 retries and trigger `window.location.reload()` every ~40 s.

---

## Known limitations

| Area | Detail |
|---|---|
| **API tier** | football-data.org free tier: 10 req/min and access to the 3 most recent seasons only |
| **Static attack/defence strength** | `mart_team_stats` aggregates the whole season. Strength early in the season (small sample) carries the same weight as late in the season |
| **Sparse advanced stats history** | If only a few API-Football matches are ingested, xG-based rolling features and charts are available only for those teams/matches |
| **Ensemble calibration** | With one season of data the Brier-based guard falls back to XGBoost-only because Poisson hurts calibration. With more seasons, a blend may outperform either model individually |

## Model benchmark

Real benchmark run on the cleaned dataset (`1053` finished matches, same temporal folds for all models):

| Model | CV accuracy (mean ± std) | Accuracy last fold | CV Brier | CV log-loss | Draw recall last fold | Verdict |
|---|---:|---:|---:|---:|---:|---|
| XGBoost | **50.4% ± 3.4%** | 54.8% | **0.597** | **1.002** | **15.4%** | Best overall balance |
| CatBoost | 49.9% ± 4.5% | **56.3%** | 0.604 | 1.011 | 6.2% | Worth keeping as challenger, not as replacement |
| FT-Transformer | 50.2% ± 2.7% | 50.6% | 0.613 | 1.026 | 6.2% | Not worth adopting |

Decision: keep **XGBoost** as the main production classifier. CatBoost showed a slightly better last-fold accuracy, but worse calibration and much weaker draw handling.
---

## Next steps

### Model quality
- [x] **Elo ratings** — compute a dynamic Elo rating per team updated after every match; add `home_elo_diff` as feature; expected +3–5 pp accuracy
- [x] **Fix `position_diff` temporal leakage** — store standings snapshot per matchday in dbt (`int_standings_snapshot`) so position at match time is used, not current position
- [x] **Season-weighted Poisson** — give more weight to recent matches when computing attack/defence strengths; reduces the influence of results from 2 seasons ago
- [x] **Hyperparameter tuning** — run Optuna over XGBoost `max_depth`, `learning_rate`, `min_child_weight`; current params are conservative defaults
- [x] **Calibration layer** — add Platt scaling or isotonic regression on top of XGBoost probabilities; improves Brier score independently of accuracy
- [x] **Draw prediction** — the model systematically underestimates draws (hardest class); explore SMOTE oversampling or a dedicated draw-probability sub-model

### Data
- [x] **Ingest xG data** — connect API-Football (`/fixtures/statistics`) to get shots on target, possession, xG per match; add as features
- [x] **`dags/ingest_advanced_stats.py`** — Airflow DAG to automate API-Football ingestion (100 req/day free limit requires careful rate management)
- [x] **`dags/ingest_scorers.py`** — top scorers per matchday for future player-level features
- [x] **`intermediate/int_h2h.sql`** — materialise H2H stats as a proper dbt model instead of computing them inline in `mart_match_features`
- [x] **Multi-season standings snapshots** — `raw_standings` currently only holds the current snapshot; archive end-of-season tables for historical accuracy

### Automation
- [x] **`dags/retrain_model.py`** — weekly Airflow DAG that runs dbt → train_poisson → train_classifier → ensemble in sequence every Monday 03:00 UTC
- [x] **Configure Airflow connections** — add ClickHouse and MinIO connections via the Airflow UI (currently `_PIP_ADDITIONAL_REQUIREMENTS` installs deps but connections are not pre-configured)
- [x] **Scheduled dbt runs** — add a DAG that runs `dbt run && dbt test` after each ingestion DAG completes

### Frontend
- [x] **xG accumulated chart** — per-team xG over the season (requires API-Football data)
- [x] **Match detail page** — click a fixture to see H2H history, both team form, and model explanation
- [x] **SHAP explanations** — show per-prediction feature contributions on the `/predictions` page ("why this probability?")
- [x] **Live score updates** — poll `/standings` and `/fixtures` endpoints on a timer during matchdays

### Infrastructure
- [x] **Custom Airflow image** — bake Python dependencies into the image instead of installing via `_PIP_ADDITIONAL_REQUIREMENTS`; cuts container startup from ~2 min to seconds
- [x] **Multi-league support** — parameterise DAGs and bootstrap script for PL, SA, BL1; each league needs its own dbt `source` and `mart_standings` partition
- [x] **Production MLflow backend** — replace SQLite + local artifact storage with PostgreSQL + S3/MinIO for multi-user or cloud deployment
- [x] **CI pipeline** — GitHub Actions: `dbt compile`, `dbt test` on every PR; `pytest` for API schemas
