"""Router: GET /teams/{team_id}/stats  and  GET /teams/{team_id}/form

Reads from mart_team_stats and mart_match_features in ClickHouse.
Team IDs are football-data.org identifiers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query, status

from api.db.clickhouse import get_client
from api.db.teams import fetch_team_form, fetch_team_stats
from api.schemas.teams import FormMatch, TeamFormResponse, TeamStatsResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get(
    "/{team_id}/stats",
    response_model=TeamStatsResponse,
    summary="Home/away stats for a team",
)
def team_stats(
    team_id: int = Path(..., gt=0, description="football-data.org team ID"),
) -> TeamStatsResponse:
    """Return home and away split statistics, clean sheets, defensive variance,
    and Poisson model strength metrics for the given team.
    """
    try:
        client = get_client()
        data = fetch_team_stats(client, team_id)
    except Exception as exc:
        log.exception("Failed to fetch stats for team %d", team_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {exc}",
        ) from exc

    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found",
        )

    return TeamStatsResponse(**data)


@router.get(
    "/{team_id}/form",
    response_model=TeamFormResponse,
    summary="Recent match results for a team",
)
def team_form(
    team_id: int = Path(..., gt=0, description="football-data.org team ID"),
    n: int = Query(10, ge=1, le=38, description="Number of recent matches to return"),
) -> TeamFormResponse:
    """Return the last *n* finished matches for the team, most recent first.

    Each entry includes: opponent, score, home/away flag, W/D/L outcome,
    and points earned.
    """
    try:
        client = get_client()
        matches = fetch_team_form(client, team_id, n=n)
    except Exception as exc:
        log.exception("Failed to fetch form for team %d", team_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error: {exc}",
        ) from exc

    if not matches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No matches found for team {team_id}",
        )

    return TeamFormResponse(
        team_id=team_id,
        matches=[FormMatch(**m) for m in matches],
    )
