# dbt — Football Analytics

## Layer rules (strict)
- staging/      → stg_ prefix, rename + cast only
- intermediate/ → int_ prefix, joins + business logic
- marts/        → mart_ prefix, final tables for ClickHouse

## Every model needs
- Entry in schema.yml with description
- not_null + unique tests on PK
- At least 2 data quality tests total

## ClickHouse dialect
- toDate() instead of CAST(x AS Date)
- toFloat64() for metrics
- ENGINE = MergeTree() ORDER BY (date_col, id_col)

## See @docs/dbt-conventions.md for full conventions
