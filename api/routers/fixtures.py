"""Router: fixtures, match detail, and team xG."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query, status

from api.db.clickhouse import get_client
from api.db.fixtures import (
    fetch_fixture_detail,
    fetch_fixtures,
    fetch_head_to_head,
    fetch_team_xg_series,
)
from api.db.predict_features import fetch_prediction_features
from api.db.teams import fetch_team_form
from api.routers.predict import get_model
from api.schemas.fixtures import FixtureEntry, FixturesResponse, MatchDetailResponse, HeadToHeadMatch
from api.schemas.predict import FeatureContribution
from api.schemas.xg import TeamXgPoint, TeamXgResponse

log = logging.getLogger(__name__)

router = APIRouter(tags=["fixtures"])


@router.get("/fixtures", response_model=FixturesResponse, summary="Get current fixtures and predictions")
def fixtures(
    limit: int = Query(12, ge=1, le=30),
    season: int | None = Query(None),
    league: str = Query("PD"),
) -> FixturesResponse:
    client = get_client()
    rows = fetch_fixtures(client, league_code=league, season_start_year=season, limit=limit)
    state = get_model()
    entries: list[FixtureEntry] = []
    current_season = season or (rows[0]["match_date"].year if rows else 2024)

    for row in rows:
        prediction = {"home_win": None, "draw": None, "away_win": None, "expected_home_goals": None, "expected_away_goals": None}
        try:
            xgb_features = None
            if state.is_ensemble:
                xgb_features = fetch_prediction_features(
                    client,
                    row["home_team_id"],
                    row["away_team_id"],
                    league_code=league,
                    season=current_season,
                )
            p_home, p_draw, p_away = state.predict(row["home_team_id"], row["away_team_id"], xgb_features)
            poisson_row = state.poisson_predictor.predict(None, __import__("pandas").DataFrame([{
                "home_team_id": row["home_team_id"],
                "away_team_id": row["away_team_id"],
            }])).iloc[0]
            prediction = {
                "home_win": p_home,
                "draw": p_draw,
                "away_win": p_away,
                "expected_home_goals": float(poisson_row["expected_home_goals"]),
                "expected_away_goals": float(poisson_row["expected_away_goals"]),
            }
        except Exception as exc:
            log.warning("Failed to compute fixture prediction for match %s: %s", row["match_id"], exc)

        entries.append(FixtureEntry(**row, **prediction))

    return FixturesResponse(season=current_season, fixtures=entries)


@router.get("/fixtures/{match_id}", response_model=MatchDetailResponse, summary="Get match detail")
def fixture_detail(match_id: int = Path(..., gt=0)) -> MatchDetailResponse:
    client = get_client()
    fixture = fetch_fixture_detail(client, match_id)
    if fixture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Match {match_id} not found")

    state = get_model()
    xgb_features = None
    top_contributions: list[FeatureContribution] = []
    explanation_label: str | None = None
    home_win = draw = away_win = expected_home_goals = expected_away_goals = None

    try:
        if state.is_ensemble:
            xgb_features = fetch_prediction_features(client, fixture["home_team_id"], fixture["away_team_id"])
        home_win, draw, away_win = state.predict(fixture["home_team_id"], fixture["away_team_id"], xgb_features)
        poisson_row = state.poisson_predictor.predict(None, __import__("pandas").DataFrame([{
            "home_team_id": fixture["home_team_id"],
            "away_team_id": fixture["away_team_id"],
        }])).iloc[0]
        expected_home_goals = float(poisson_row["expected_home_goals"])
        expected_away_goals = float(poisson_row["expected_away_goals"])
        if xgb_features is not None:
            top_contributions, explanation_label = state.explain_prediction(xgb_features)
    except Exception as exc:
        log.warning("Failed to build explanation for match %s: %s", match_id, exc)

    fixture_payload = FixtureEntry(
        **fixture,
        home_win=home_win,
        draw=draw,
        away_win=away_win,
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
    )
    return MatchDetailResponse(
        fixture=fixture_payload,
        home_form=fetch_team_form(client, fixture["home_team_id"], n=5),
        away_form=fetch_team_form(client, fixture["away_team_id"], n=5),
        head_to_head=[HeadToHeadMatch(**row) for row in fetch_head_to_head(client, fixture["home_team_id"], fixture["away_team_id"])],
        top_contributions=top_contributions,
        explanation_label=explanation_label,
    )


@router.get("/teams/{team_id}/xg", response_model=TeamXgResponse, summary="Get cumulative xG series for a team")
def team_xg(team_id: int = Path(..., gt=0)) -> TeamXgResponse:
    client = get_client()
    points = fetch_team_xg_series(client, team_id)
    return TeamXgResponse(team_id=team_id, points=[TeamXgPoint(**point) for point in points])
