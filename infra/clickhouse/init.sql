-- ClickHouse initialisation — runs automatically on first container start.
-- Creates the football database and the raw source tables that dbt reads from.
-- The Airflow ingestion DAGs INSERT into these tables after each API fetch.

CREATE DATABASE IF NOT EXISTS football;

-- raw_matches: one row per match, all statuses (FINISHED, SCHEDULED, etc.)
CREATE TABLE IF NOT EXISTS football.raw_matches
(
    match_id          UInt32,
    utc_date          String,
    status            String,
    matchday          Nullable(UInt8),
    stage             Nullable(String),
    home_team_id      UInt32,
    home_team_name    String,
    away_team_id      UInt32,
    away_team_name    String,
    home_score_full   Nullable(Int32),
    away_score_full   Nullable(Int32),
    home_score_half   Nullable(Int32),
    away_score_half   Nullable(Int32),
    winner            Nullable(String),
    season_start_date String,
    season_end_date   String
)
ENGINE = ReplacingMergeTree()
ORDER BY (match_id)
SETTINGS index_granularity = 8192;

-- raw_standings: daily snapshot of the league table (one row per team per load)
CREATE TABLE IF NOT EXISTS football.raw_standings
(
    position         UInt8,
    team_id          UInt32,
    team_name        String,
    team_short_name  Nullable(String),
    played_games     UInt8,
    won              UInt8,
    draw             UInt8,
    lost             UInt8,
    points           UInt16,
    goals_for        Int32,
    goals_against    Int32,
    goal_difference  Int32,
    form             Nullable(String),
    season_start_date Date,
    season_end_date   Date,
    snapshot_date     Date
)
ENGINE = ReplacingMergeTree(snapshot_date)
ORDER BY (season_start_date, team_id, snapshot_date)
SETTINGS index_granularity = 8192;

-- raw_advanced_stats: API-Football fixture statistics matched to football-data match IDs
CREATE TABLE IF NOT EXISTS football.raw_advanced_stats
(
    match_id               UInt32,
    api_football_fixture_id UInt32,
    match_date             Date,
    season_start_date      Date,
    home_team_id           UInt32,
    away_team_id           UInt32,
    home_team_name         String,
    away_team_name         String,
    home_shots_on_target   Nullable(UInt16),
    away_shots_on_target   Nullable(UInt16),
    home_total_shots       Nullable(UInt16),
    away_total_shots       Nullable(UInt16),
    home_possession_pct    Nullable(Float64),
    away_possession_pct    Nullable(Float64),
    home_expected_goals    Nullable(Float64),
    away_expected_goals    Nullable(Float64),
    fetched_at             DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(fetched_at)
ORDER BY (match_id)
SETTINGS index_granularity = 8192;

-- raw_scorers: top scorers snapshot from football-data.org
CREATE TABLE IF NOT EXISTS football.raw_scorers
(
    snapshot_date      Date,
    season_start_date  Date,
    season_end_date    Date,
    rank               UInt16,
    player_id          UInt32,
    player_name        String,
    team_id            UInt32,
    team_name          String,
    played_matches     Nullable(UInt16),
    goals              UInt16,
    assists            Nullable(UInt16),
    penalties          Nullable(UInt16)
)
ENGINE = ReplacingMergeTree(snapshot_date)
ORDER BY (season_start_date, rank, player_id)
SETTINGS index_granularity = 8192;
