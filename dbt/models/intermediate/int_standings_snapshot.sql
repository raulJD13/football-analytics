-- Intermediate: standings snapshot by matchday, shifted so snapshot_matchday N
-- represents the table BEFORE matchday N starts (i.e. after N-1 has finished).
with results as (
    select * from {{ ref('int_team_match_results') }}
),

teams_by_season as (
    select distinct
        season_start_date,
        team_id
    from results
),

matchdays as (
    select distinct
        season_start_date,
        matchday
    from results
),

initial_snapshot as (
    select
        t.season_start_date,
        m.matchday                                               as snapshot_matchday,
        t.team_id,
        cast(null as Nullable(UInt8))                            as position,
        toUInt16(0)                                              as played_games,
        toUInt16(0)                                              as points,
        toInt16(0)                                               as goals_for,
        toInt16(0)                                               as goals_against,
        toInt16(0)                                               as goal_difference
    from teams_by_season t
    inner join matchdays m
        on m.season_start_date = t.season_start_date
    where m.matchday = 1
),

team_matchday_totals as (
    select
        season_start_date,
        team_id,
        matchday,
        count()                                                  as played_games_in_matchday,
        sum(points)                                              as points_in_matchday,
        sum(goals_scored)                                        as goals_for_in_matchday,
        sum(goals_conceded)                                      as goals_against_in_matchday
    from results
    group by season_start_date, team_id, matchday
),

cumulative as (
    select
        season_start_date,
        team_id,
        matchday,
        sum(played_games_in_matchday) over (
            partition by season_start_date, team_id
            order by matchday
            rows between unbounded preceding and current row
        )                                                        as played_games,
        sum(points_in_matchday) over (
            partition by season_start_date, team_id
            order by matchday
            rows between unbounded preceding and current row
        )                                                        as points,
        sum(goals_for_in_matchday) over (
            partition by season_start_date, team_id
            order by matchday
            rows between unbounded preceding and current row
        )                                                        as goals_for,
        sum(goals_against_in_matchday) over (
            partition by season_start_date, team_id
            order by matchday
            rows between unbounded preceding and current row
        )                                                        as goals_against
    from team_matchday_totals
),

ranked as (
    select
        season_start_date,
        matchday + 1                                             as snapshot_matchday,
        team_id,
        toUInt8(
            row_number() over (
                partition by season_start_date, matchday
                order by
                    points desc,
                    (goals_for - goals_against) desc,
                    goals_for desc,
                    team_id
            )
        )                                                        as position,
        played_games,
        points,
        goals_for,
        goals_against,
        goals_for - goals_against                                as goal_difference
    from cumulative
)

select * from initial_snapshot
union all
select * from ranked
