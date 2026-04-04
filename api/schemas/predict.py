"""Pydantic schemas for the /predict endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PredictRequest(BaseModel):
    home_team_id: int = Field(..., gt=0, description="football-data.org home team ID")
    away_team_id: int = Field(..., gt=0, description="football-data.org away team ID")

    @model_validator(mode="after")
    def teams_must_differ(self) -> "PredictRequest":
        if self.home_team_id == self.away_team_id:
            raise ValueError("home_team_id and away_team_id must be different")
        return self


class PredictResponse(BaseModel):
    home_team_id: int
    away_team_id: int
    home_win: float = Field(..., ge=0.0, le=1.0, description="P(home wins)")
    draw: float = Field(..., ge=0.0, le=1.0, description="P(draw)")
    away_win: float = Field(..., ge=0.0, le=1.0, description="P(away wins)")
    expected_home_goals: float = Field(..., ge=0.0, description="λ for home goals (Poisson rate)")
    expected_away_goals: float = Field(..., ge=0.0, description="λ for away goals (Poisson rate)")
    model_version: str = Field(..., description="MLflow model version used")

    model_config = {"json_schema_extra": {
        "example": {
            "home_team_id": 86,
            "away_team_id": 81,
            "home_win": 0.4821,
            "draw": 0.2614,
            "away_win": 0.2565,
            "expected_home_goals": 1.842,
            "expected_away_goals": 1.193,
            "model_version": "1",
        }
    }}
