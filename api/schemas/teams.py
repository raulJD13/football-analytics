"""Pydantic schemas for the /teams endpoints."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class HomeAwayStats(BaseModel):
    played: int
    won: int
    drawn: int
    lost: int
    points: int
    goals_for: int | None
    goals_against: int | None
    avg_goals_scored: float | None
    avg_goals_conceded: float | None
    points_per_game: float
    clean_sheets: int
    defensive_variance: float | None = Field(
        None, description="Population variance of goals conceded per match"
    )


class TeamStatsResponse(BaseModel):
    team_id: int
    team_name: str
    home: HomeAwayStats
    away: HomeAwayStats
    home_attack_strength: float | None = Field(
        None, description="Home avg scored / league avg"
    )
    away_defence_weakness: float | None = Field(
        None, description="Away avg conceded / league avg"
    )


class FormMatch(BaseModel):
    match_id: int
    match_date: datetime.date
    is_home: bool
    opponent_team_id: int
    team_goals: int | None
    opponent_goals: int | None
    outcome: str = Field(..., description="'W', 'D', or 'L'")
    points: int = Field(..., description="Points earned: 3/1/0")


class TeamFormResponse(BaseModel):
    team_id: int
    matches: list[FormMatch]
