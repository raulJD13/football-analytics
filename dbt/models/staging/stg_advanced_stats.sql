-- Staging: cast advanced API-Football statistics already matched to match_id.
with source as (
    select * from {{ source('raw', 'advanced_stats') }}
)

select
    match_id,
    league_code,
    api_football_fixture_id,
    toDate(match_date)                  as match_date,
    toDate(season_start_date)           as season_start_date,
    home_team_id,
    away_team_id,
    home_team_name,
    away_team_name,
    toFloat64(home_shots_on_target)     as home_shots_on_target,
    toFloat64(away_shots_on_target)     as away_shots_on_target,
    toFloat64(home_total_shots)         as home_total_shots,
    toFloat64(away_total_shots)         as away_total_shots,
    toFloat64(home_possession_pct)      as home_possession_pct,
    toFloat64(away_possession_pct)      as away_possession_pct,
    toFloat64(home_expected_goals)      as home_expected_goals,
    toFloat64(away_expected_goals)      as away_expected_goals,
    fetched_at
from source
