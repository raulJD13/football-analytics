-- Intermediate: rolling advanced stats from the 5 matches before each fixture.
with advanced as (
    select * from {{ ref('stg_advanced_stats') }}
),

team_rows as (
    select
        match_id,
        league_code,
        match_date,
        season_start_date,
        home_team_id                             as team_id,
        1                                        as is_home,
        home_expected_goals                      as expected_goals_for,
        away_expected_goals                      as expected_goals_against,
        home_shots_on_target                     as shots_on_target_for,
        away_shots_on_target                     as shots_on_target_against,
        home_possession_pct                      as possession_pct
    from advanced

    union all

    select
        match_id,
        league_code,
        match_date,
        season_start_date,
        away_team_id                             as team_id,
        0                                        as is_home,
        away_expected_goals                      as expected_goals_for,
        home_expected_goals                      as expected_goals_against,
        away_shots_on_target                     as shots_on_target_for,
        home_shots_on_target                     as shots_on_target_against,
        away_possession_pct                      as possession_pct
    from advanced
)

select
    league_code,
    team_id,
    match_id,
    avg(expected_goals_for) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    ) as xg_for_avg_last_5,
    avg(expected_goals_against) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    ) as xg_against_avg_last_5,
    avg(shots_on_target_for) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    ) as shots_on_target_for_avg_last_5,
    avg(shots_on_target_against) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    ) as shots_on_target_against_avg_last_5,
    avg(possession_pct) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    ) as possession_avg_last_5
from team_rows
