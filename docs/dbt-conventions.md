# dbt Conventions

## Layer rules
- staging/   → rename + cast only. No logic. One source = one model.
- intermediate/ → joins, window functions, business logic. Prefix: int_
- marts/     → final consumable tables. Prefix: mart_

## Naming
- Models:   snake_case, layer prefix (stg_ / int_ / mart_)
- Columns:  snake_case, no abbreviations
- Tests:    in schema.yml next to each model

## Required tests (every model)
- PKs: not_null + unique
- FKs: relationships test
- Marts: at least one accepted_values or custom test

## ClickHouse specifics
- Use toDate() not CAST(x AS Date)
- Use toFloat64() for decimal metrics
- ENGINE = MergeTree() ORDER BY (match_date, team_id)

## schema.yml template
models:
  - name: mart_team_stats
    description: "Aggregated team statistics per season"
    columns:
      - name: team_id
        description: "Unique team identifier"
        tests: [not_null, unique]
