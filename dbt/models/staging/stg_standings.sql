-- Staging: rename and cast raw standings snapshots.
with source as (
    select * from {{ source('raw', 'standings') }}
)

select
    position,
    team_id,
    team_name,
    team_short_name,
    played_games,
    won,
    draw,
    lost,
    points,
    goals_for,
    goals_against,
    goal_difference,
    form,
    toDate(season_start_date) as season_start_date,
    toDate(season_end_date)   as season_end_date,
    toDate(snapshot_date)     as snapshot_date
from source
