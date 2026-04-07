"""Competition configuration shared across Airflow, dbt bootstrap, and API."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Competition:
    code: str
    name: str
    api_football_league_id: int | None = None
    total_matchdays: int = 38


SUPPORTED_COMPETITIONS: dict[str, Competition] = {
    "PD": Competition(code="PD", name="LaLiga", api_football_league_id=140, total_matchdays=38),
    "PL": Competition(code="PL", name="Premier League", api_football_league_id=39, total_matchdays=38),
    "SA": Competition(code="SA", name="Serie A", api_football_league_id=135, total_matchdays=38),
    "BL1": Competition(code="BL1", name="Bundesliga", api_football_league_id=78, total_matchdays=34),
}

DEFAULT_COMPETITION_CODES = ("PD", "PL", "SA", "BL1")


def get_enabled_competitions(env_var: str = "SUPPORTED_LEAGUES") -> list[Competition]:
    """Return enabled competitions from env or the default set."""
    configured = os.getenv(env_var)
    codes = DEFAULT_COMPETITION_CODES if not configured else tuple(
        code.strip().upper() for code in configured.split(",") if code.strip()
    )
    competitions: list[Competition] = []
    for code in codes:
        competition = SUPPORTED_COMPETITIONS.get(code)
        if competition is not None:
            competitions.append(competition)
    return competitions
