"""Schemas for team xG series."""

from __future__ import annotations

import datetime

from pydantic import BaseModel


class TeamXgPoint(BaseModel):
    match_id: int
    match_date: datetime.date
    opponent_team_id: int
    is_home: bool
    expected_goals_for: float
    expected_goals_against: float
    cumulative_expected_goals_for: float
    cumulative_expected_goals_against: float


class TeamXgResponse(BaseModel):
    team_id: int
    points: list[TeamXgPoint]
