# ── Convenience wrapper so dbt can be invoked from the project root ───────────
# dbt_project.yml and profiles.yml live in dbt/, so all dbt commands must run
# from that subdirectory. This Makefile proxies them with the correct paths.

VENV_DBT := dbt/../../venv/bin/dbt
# Resolve relative to the dbt/ dir: ../venv/bin/dbt
_DBT := cd dbt && ../venv/bin/dbt

.PHONY: dbt-run dbt-test dbt-compile dbt-debug dbt-docs \
        up down bootstrap

# ── dbt ───────────────────────────────────────────────────────────────────────
dbt-debug:
	$(_DBT) debug

dbt-compile:
	$(_DBT) compile

dbt-run:
	$(_DBT) run

dbt-test:
	$(_DBT) test

dbt-docs:
	$(_DBT) docs generate && $(_DBT) docs serve

# ── Docker stack ──────────────────────────────────────────────────────────────
up:
	docker compose up -d --build

down:
	docker compose down

# ── Dev bootstrap: load initial data from API into ClickHouse ─────────────────
bootstrap:
	venv/bin/python scripts/bootstrap_clickhouse.py
