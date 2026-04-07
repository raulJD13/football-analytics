-- Intermediate: exact-fixture head-to-head metrics available before each match.
with matches as (
    select * from {{ ref('stg_matches') }}
)

select
    match_id,
    home_team_id,
    away_team_id,
    coalesce(
        toFloat64(
            countIf(winner = 'HOME_TEAM') over (
                partition by home_team_id, away_team_id
                order by match_date, match_id
                rows between unbounded preceding and 1 preceding
            )
        ) / nullIf(
            count() over (
                partition by home_team_id, away_team_id
                order by match_date, match_id
                rows between unbounded preceding and 1 preceding
            ),
            0
        ),
        0.45
    ) as h2h_home_win_rate,
    count() over (
        partition by home_team_id, away_team_id
        order by match_date, match_id
        rows between unbounded preceding and 1 preceding
    ) as h2h_matches_played
from matches
