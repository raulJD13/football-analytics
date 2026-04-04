-- Intermediate: unpivot matches into one row per team per match.
-- Adds points (3/1/0), result (W/D/L), and is_home flag.
with matches as (
    select * from {{ ref('stg_matches') }}
),

home_results as (
    select
        match_id,
        match_date,
        home_team_id                            as team_id,
        away_team_id                            as opponent_id,
        1                                       as is_home,
        home_goals                              as goals_scored,
        away_goals                              as goals_conceded,
        case winner
            when 'HOME_TEAM' then 3
            when 'DRAW'      then 1
            else                  0
        end                                     as points,
        case winner
            when 'HOME_TEAM' then 'W'
            when 'DRAW'      then 'D'
            else                  'L'
        end                                     as result
    from matches
),

away_results as (
    select
        match_id,
        match_date,
        away_team_id                            as team_id,
        home_team_id                            as opponent_id,
        0                                       as is_home,
        away_goals                              as goals_scored,
        home_goals                              as goals_conceded,
        case winner
            when 'AWAY_TEAM' then 3
            when 'DRAW'      then 1
            else                  0
        end                                     as points,
        case winner
            when 'AWAY_TEAM' then 'W'
            when 'DRAW'      then 'D'
            else                  'L'
        end                                     as result
    from matches
)

select * from home_results
union all
select * from away_results
