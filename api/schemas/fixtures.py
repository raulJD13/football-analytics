"""Schemas for fixtures and match detail endpoints."""

from __future__ import annotations

import datetime

from pydantic import BaseModel

from api.schemas.predict import FeatureContribution
from api.schemas.teams import FormMatch


class FixtureEntry(BaseModel):
    match_id: int
    match_date: datetime.date
    status: str
    matchday: int | None
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str
    home_goals: int | None
    away_goals: int | None
    home_win: float | None = None
    draw: float | None = None
    away_win: float | None = None
    expected_home_goals: float | None = None
    expected_away_goals: float | None = None


class FixturesResponse(BaseModel):
    season: int
    fixtures: list[FixtureEntry]


class HeadToHeadMatch(BaseModel):
    match_id: int
    match_date: datetime.date
    home_team_name: str
    away_team_name: str
    home_goals: int | None
    away_goals: int | None
    result: str


class MatchDetailResponse(BaseModel):
    fixture: FixtureEntry
    home_form: list[FormMatch]
    away_form: list[FormMatch]
    head_to_head: list[HeadToHeadMatch]
    top_contributions: list[FeatureContribution]
    explanation_label: str | None = None
