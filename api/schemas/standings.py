"""Pydantic schemas for the /standings endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StandingEntry(BaseModel):
    position: int
    team_id: int
    team_name: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int | None
    goals_against: int | None
    goal_difference: int | None
    points: int
    form_last_5: str = Field(..., description="Last 5 results as W/D/L string, e.g. 'WWDLW'")
    projected_points: int = Field(..., description="Extrapolated to 38 matchdays")


class StandingsResponse(BaseModel):
    league: str
    season: int
    standings: list[StandingEntry]
