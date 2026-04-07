"""Router: GET /standings

Returns the current league table from mart_standings, enriched with
form strings (last 5 results) and projected final-day points.

The `league` query param defaults to `PD`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from api.db.clickhouse import get_client
from api.db.standings import fetch_form_strings, fetch_standings
from api.schemas.standings import StandingEntry, StandingsResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/standings", tags=["standings"])


@router.get(
    "",
    response_model=StandingsResponse,
    summary="Get current league standings",
)
def standings(
    league: str = Query("PD", description="Competition code, e.g. PD, PL, SA, BL1"),
    season: int = Query(2024, description="Season start year"),
) -> StandingsResponse:
    """Return the current league table ordered by position.

    Enriched with:
    - **form_last_5**: last 5 results as a W/D/L string (e.g. ``WWDLW``)
    - **projected_points**: linear extrapolation to 38 matchdays
    """
    try:
        client = get_client()
        rows = fetch_standings(client, league_code=league, season=season)
        form_map = fetch_form_strings(client, league_code=league, n=5)
    except Exception as exc:
        log.exception("Failed to fetch standings")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {exc}",
        ) from exc

    entries = [
        StandingEntry(
            **row,
            form_last_5=form_map.get(row["team_id"], ""),
        )
        for row in rows
    ]
    return StandingsResponse(league=league, season=season, standings=entries)
