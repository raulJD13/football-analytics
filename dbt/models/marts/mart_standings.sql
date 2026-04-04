{{
    config(
        order_by = ['team_id']
    )
}}
-- order_by uses team_id (always non-null) because ClickHouse rejects nullable
-- columns in MergeTree sorting keys unless allow_nullable_key is enabled.
-- Mart: current season standings derived from match results.
-- Position is computed via window function on points → GD → GF.
with aggregated as (
    select
        team_id,
        count()                                                 as played_games,
        countIf(result = 'W')                                   as won,
        countIf(result = 'D')                                   as draw,
        countIf(result = 'L')                                   as lost,
        sum(points)                                             as points,
        sum(goals_scored)                                       as goals_for,
        sum(goals_conceded)                                     as goals_against,
        sum(goals_scored) - sum(goals_conceded)                 as goal_difference
    from {{ ref('int_team_match_results') }}
    group by team_id
)

select
    toUInt8(
        row_number() over (
            order by points desc, goal_difference desc, goals_for desc
        )
    )                   as position,
    t.team_name,
    a.team_id,
    a.played_games,
    a.won,
    a.draw,
    a.lost,
    a.points,
    a.goals_for,
    a.goals_against,
    a.goal_difference
from aggregated a
inner join {{ ref('stg_teams') }} t on t.team_id = a.team_id
