-- Staging: derive unique teams from match participants.
-- Both home and away appearances are considered to ensure completeness.
with home_teams as (
    select
        home_team_id    as team_id,
        home_team_name  as team_name
    from {{ ref('stg_matches') }}
),

away_teams as (
    select
        away_team_id    as team_id,
        away_team_name  as team_name
    from {{ ref('stg_matches') }}
),

all_teams as (
    select * from home_teams
    union all
    select * from away_teams
)

select distinct
    team_id,
    team_name
from all_teams
