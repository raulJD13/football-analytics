{{
    config(
        order_by = 'tuple()'
    )
}}
-- ORDER BY tuple() because ClickHouse 24.3 raises UNKNOWN_IDENTIFIER for any
-- named column ORDER BY when the AS-SELECT contains window functions that use
-- the same column names (match_date, match_id, etc.) in their own ORDER BY
-- clauses inside referenced views.  This is a DDL-planning resolution bug; the
-- SELECT itself executes correctly.  tuple() is valid for append-only ML tables.
-- Mart: one row per finished match with all ML features pre-joined.
-- Consumed by ml/scripts/train_classifier.py and train_poisson.py.
-- form_* columns use data from BEFORE each match to prevent leakage.
with matches as (
    select * from {{ ref('stg_matches') }}
),

standings as (
    select team_id, position from {{ ref('mart_standings') }}
),

team_stats as (
    select * from {{ ref('mart_team_stats') }}
),

form as (
    select team_id, match_id, form_points_last_5, form_matches_available
    from {{ ref('int_form_last_5') }}
),

-- Days of rest since each team's previous match
rest as (
    select
        team_id,
        match_id,
        match_date,
        lagInFrame(match_date) over (
            partition by team_id
            order by match_date, match_id
        )                                                           as prev_match_date
    from {{ ref('int_team_match_results') }}
),

rest_days as (
    select
        team_id,
        match_id,
        if(
            isNull(prev_match_date),
            7,
            toInt32(dateDiff('day', prev_match_date, match_date))
        )                                                           as rest_days
    from rest
),

-- H2H home win rate for each (home_team, away_team) pair
h2h as (
    select
        home_team_id,
        away_team_id,
        toFloat64(countIf(winner = 'HOME_TEAM')) / count()          as h2h_home_win_rate,
        count()                                                     as h2h_matches_played
    from matches
    group by home_team_id, away_team_id
)

select
    -- Explicit aliases so ClickHouse stores unqualified names even when the
    -- same column (match_id, etc.) exists in other CTEs (form, rest_days).
    m.match_id                                                          as match_id,
    m.match_date                                                        as match_date,
    m.matchday                                                          as matchday,
    m.home_team_id                                                      as home_team_id,
    m.away_team_id                                                      as away_team_id,
    m.home_goals                                                        as home_goals,
    m.away_goals                                                        as away_goals,
    m.winner                                                            as winner,

    -- Target variable for the classifier
    case m.winner
        when 'HOME_TEAM' then 'H'
        when 'DRAW'      then 'D'
        when 'AWAY_TEAM' then 'A'
    end                                                             as result,

    -- Form (points in last 5 matches before this one)
    coalesce(hf.form_points_last_5, 0)                             as home_form_5,
    coalesce(af.form_points_last_5, 0)                             as away_form_5,
    coalesce(hf.form_matches_available, 0)                         as home_form_matches_available,
    coalesce(af.form_matches_available, 0)                         as away_form_matches_available,

    -- Attack / defence strength (from mart_team_stats)
    coalesce(toFloat64(hts.home_attack_strength), 1.0)             as home_attack_strength,
    coalesce(toFloat64(hts.home_avg_goals_conceded), 1.0)
        / nullIf(toFloat64(ats.away_avg_goals_scored), 0)          as home_defence_vs_away_attack,
    coalesce(toFloat64(ats.away_defence_weakness), 1.0)            as away_defence_weakness,
    coalesce(toFloat64(ats.away_avg_goals_scored), 1.0)            as away_attack_rate,

    -- Head-to-head
    coalesce(h2h.h2h_home_win_rate, 0.45)                          as h2h_home_win_rate,
    coalesce(h2h.h2h_matches_played, 0)                            as h2h_matches_played,

    -- Rest days
    coalesce(hr.rest_days, 7)                                      as home_rest_days,
    coalesce(ar.rest_days, 7)                                      as away_rest_days,

    -- Standings gap: positive = home team is ranked lower (worse)
    coalesce(
        toInt32(hs.position) - toInt32(as_.position),
        0
    )                                                              as position_diff

from matches m
left join form           hf   on hf.team_id  = m.home_team_id and hf.match_id = m.match_id
left join form           af   on af.team_id  = m.away_team_id and af.match_id = m.match_id
left join team_stats     hts  on hts.team_id = m.home_team_id
left join team_stats     ats  on ats.team_id = m.away_team_id
left join standings      hs   on hs.team_id  = m.home_team_id
left join standings      as_  on as_.team_id = m.away_team_id
left join h2h                 on h2h.home_team_id = m.home_team_id
                              and h2h.away_team_id = m.away_team_id
left join rest_days      hr   on hr.team_id  = m.home_team_id and hr.match_id = m.match_id
left join rest_days      ar   on ar.team_id  = m.away_team_id and ar.match_id = m.match_id
