-- Staging: top scorers snapshots from football-data.org.
with source as (
    select * from {{ source('raw', 'scorers') }}
)

select
    league_code,
    toDate(snapshot_date)      as snapshot_date,
    toDate(season_start_date)  as season_start_date,
    toDate(season_end_date)    as season_end_date,
    rank,
    player_id,
    player_name,
    team_id,
    team_name,
    played_matches,
    goals,
    assists,
    penalties
from source
