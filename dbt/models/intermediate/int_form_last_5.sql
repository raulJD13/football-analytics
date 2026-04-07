-- Intermediate: rolling form over the 5 matches immediately preceding each match.
-- Uses ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING to avoid data leakage in ML features.
-- form_points_last_5 is NULL for a team's first match (no prior history).
with results as (
    select * from {{ ref('int_team_match_results') }}
)

select
    league_code,
    team_id,
    match_id,
    match_date,
    points,
    result,

    -- Points accumulated in the 5 matches before this one
    sum(points) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    )                                                           as form_points_last_5,

    -- Wins in the last 5
    sum(if(result = 'W', 1, 0)) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    )                                                           as form_wins_last_5,

    -- Draws in the last 5
    sum(if(result = 'D', 1, 0)) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    )                                                           as form_draws_last_5,

    -- Losses in the last 5
    sum(if(result = 'L', 1, 0)) over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    )                                                           as form_losses_last_5,

    -- How many prior matches are available (capped at 5; useful for early-season rows)
    count() over (
        partition by league_code, team_id
        order by match_date, match_id
        rows between 5 preceding and 1 preceding
    )                                                           as form_matches_available

from results
