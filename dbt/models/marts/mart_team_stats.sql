{{
    config(
        order_by = ['team_id']
    )
}}
-- Mart: aggregated team statistics split by home and away.
-- Written as a single aggregation level to avoid ClickHouse CTE inlining that
-- would produce nested aggregate errors (sum inside sumIf on a CTE alias).
with results as (
    select * from {{ ref('int_team_match_results') }}
),

league_avg as (
    select toFloat64(avg(goals_scored)) as league_avg_goals
    from results
)

select
    r.team_id,

    -- Home
    countIf(r.is_home = 1)                                              as home_played,
    countIf(r.is_home = 1 AND r.result = 'W')                           as home_won,
    countIf(r.is_home = 1 AND r.result = 'D')                           as home_draw,
    countIf(r.is_home = 1 AND r.result = 'L')                           as home_lost,
    sumIf(r.points,          r.is_home = 1)                             as home_points,
    sumIf(r.goals_scored,    r.is_home = 1)                             as home_goals_for,
    sumIf(r.goals_conceded,  r.is_home = 1)                             as home_goals_against,
    toFloat64(avgIf(r.goals_scored,    r.is_home = 1))                  as home_avg_goals_scored,
    toFloat64(avgIf(r.goals_conceded,  r.is_home = 1))                  as home_avg_goals_conceded,
    toFloat64(avgIf(r.points,          r.is_home = 1))                  as home_avg_points_per_game,

    -- Away
    countIf(r.is_home = 0)                                              as away_played,
    countIf(r.is_home = 0 AND r.result = 'W')                           as away_won,
    countIf(r.is_home = 0 AND r.result = 'D')                           as away_draw,
    countIf(r.is_home = 0 AND r.result = 'L')                           as away_lost,
    sumIf(r.points,          r.is_home = 0)                             as away_points,
    sumIf(r.goals_scored,    r.is_home = 0)                             as away_goals_for,
    sumIf(r.goals_conceded,  r.is_home = 0)                             as away_goals_against,
    toFloat64(avgIf(r.goals_scored,    r.is_home = 0))                  as away_avg_goals_scored,
    toFloat64(avgIf(r.goals_conceded,  r.is_home = 0))                  as away_avg_goals_conceded,
    toFloat64(avgIf(r.points,          r.is_home = 0))                  as away_avg_points_per_game,

    -- Attack / defence strength used by the Poisson model
    toFloat64(avgIf(r.goals_scored,    r.is_home = 1))
        / nullIf(any(la.league_avg_goals), 0)                           as home_attack_strength,
    toFloat64(avgIf(r.goals_conceded,  r.is_home = 0))
        / nullIf(any(la.league_avg_goals), 0)                           as away_defence_weakness

from results r
cross join league_avg la
group by r.team_id
