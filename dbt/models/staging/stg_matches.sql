-- Staging: rename, cast, and filter raw match rows.
-- One row per finished match. No business logic.
with source as (
    select * from {{ source('raw', 'matches') }}
),

renamed as (
    select
        match_id,
        league_code,
        -- utc_date arrives as ISO 8601 e.g. "2025-08-16T19:30:00Z"; toDate()
        -- alone fails on the time component, so parse first then extract date.
        toDate(parseDateTimeBestEffort(utc_date))   as match_date,
        utc_date                                    as match_datetime,
        status,
        matchday,
        home_team_id,
        home_team_name,
        away_team_id,
        away_team_name,
        home_score_full                     as home_goals,
        away_score_full                     as away_goals,
        home_score_half                     as home_goals_ht,
        away_score_half                     as away_goals_ht,
        winner,
        toDate(season_start_date)           as season_start_date,
        toDate(season_end_date)             as season_end_date
    from source
    where status = 'FINISHED'
)

select * from renamed
