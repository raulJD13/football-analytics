# Progress tracker

## Phase 1 — Infraestructura base
- [x] docker-compose.yml (Airflow, MinIO, ClickHouse, MLflow)
- [x] .env con variables de entorno
- [ ] Conexiones Airflow configuradas
- [x] Buckets MinIO: raw/ y refined/

## Phase 2 — Ingesta (DAGs)
- [x] dags/ingest_matches.py
- [x] dags/ingest_standings.py
- [ ] dags/ingest_scorers.py
- [ ] dags/ingest_advanced_stats.py  (API-Football)

## Phase 3 — dbt transformations
- [x] staging/stg_matches.sql
- [x] staging/stg_teams.sql
- [ ] staging/stg_goals.sql
- [x] intermediate/int_team_match_results.sql
- [x] intermediate/int_form_last_5.sql
- [ ] intermediate/int_h2h.sql
- [x] marts/mart_standings.sql
- [x] marts/mart_team_stats.sql
- [x] marts/mart_match_features.sql
- [x] Tests de calidad en todos los modelos

## Phase 4 — ML
- [x] ml/scripts/train_poisson.py
- [ ] ml/scripts/train_classifier.py
- [x] MLflow tracking integrado
- [ ] dags/retrain_model.py (semanal)
- [x] api/routers/predict.py

## Phase 5 — FastAPI
- [x] api/main.py
- [x] api/routers/standings.py
- [x] api/routers/teams.py
- [x] api/routers/predict.py

## Phase 6 — Frontend
- [x] Layout global (Sidebar + Topbar, dark theme)
- [x] /overview — KPIs + top matchup predictions + standings snapshot
- [x] /fixtures — simulated fixture predictions grid
- [x] /predictions — team selector dropdowns + POST /predict + animated bars
- [x] /standings — full table with FormDots + projected points
- [x] /teams/[id] — home vs away cards + last 10 matches + strength metrics
- [x] /model — accuracy/brier/log-loss KPIs + feature importance chart
- [ ] Gráfico xG acumulado por equipo (requires xG data from API-Football)
