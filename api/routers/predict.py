"""Router: POST /predict

Loads the Poisson match predictor from MLflow (Production alias) at startup
and serves probability predictions for a given home vs away fixture.

If MLflow is unreachable the router refuses to start — predictions without a
registered model would be silently wrong.  Set MLFLOW_TRACKING_URI in the
environment (default: http://localhost:5000).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status

import mlflow.pyfunc

from api.schemas.predict import PredictRequest, PredictResponse

log = logging.getLogger(__name__)

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")
REGISTERED_MODEL = "poisson-match-predictor"
MODEL_ALIAS = "Production"


# ── model loader ──────────────────────────────────────────────────────────────

class _ModelState:
    """Holds the loaded pyfunc model and its version string."""

    def __init__(self) -> None:
        self._model: mlflow.pyfunc.PyFuncModel | None = None
        self._version: str = "unknown"

    def load(self) -> None:
        """Load (or reload) the Production model from MLflow."""
        mlflow.set_tracking_uri(MLFLOW_URI)
        uri = f"models:/{REGISTERED_MODEL}@{MODEL_ALIAS}"
        log.info("Loading model from %s …", uri)
        self._model = mlflow.pyfunc.load_model(uri)

        # Extract the version for the response payload
        client = mlflow.tracking.MlflowClient(MLFLOW_URI)
        versions = client.get_model_version_by_alias(REGISTERED_MODEL, MODEL_ALIAS)
        self._version = versions.version
        log.info("Model version %s loaded.", self._version)

    @property
    def model(self) -> mlflow.pyfunc.PyFuncModel:
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        return self._model

    @property
    def version(self) -> str:
        return self._version


_state = _ModelState()


def get_model() -> _ModelState:
    """FastAPI dependency: returns the shared model state."""
    return _state


# ── lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app) -> AsyncGenerator[None, None]:  # type: ignore[type-arg]
    """Load model on startup; nothing to clean up on shutdown."""
    try:
        _state.load()
    except Exception as exc:
        log.error("Failed to load model from MLflow: %s", exc)
        log.error(
            "Ensure the training script has been run and MLflow is reachable at %s",
            MLFLOW_URI,
        )
        raise
    yield


# ── router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/predict", tags=["predict"])


@router.post(
    "",
    response_model=PredictResponse,
    summary="Predict LaLiga match outcome probabilities",
)
def predict(
    body: PredictRequest,
    state: _ModelState = Depends(get_model),
) -> PredictResponse:
    """Return P(home win), P(draw), P(away win) for a fixture.

    Uses the Poisson model registered in MLflow (Production alias).
    Both team IDs must be valid football-data.org identifiers.

    Unknown team IDs (not in training data) fall back to league-average
    strength — the model degrades gracefully rather than returning an error.
    """
    input_df = pd.DataFrame([{
        "home_team_id": body.home_team_id,
        "away_team_id": body.away_team_id,
    }])

    try:
        result = state.model.predict(input_df)
    except Exception as exc:
        log.exception("Prediction failed for %s vs %s", body.home_team_id, body.away_team_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction error: {exc}",
        ) from exc

    row = result.iloc[0]
    return PredictResponse(
        home_team_id=body.home_team_id,
        away_team_id=body.away_team_id,
        home_win=float(row["home_win"]),
        draw=float(row["draw"]),
        away_win=float(row["away_win"]),
        expected_home_goals=float(row["expected_home_goals"]),
        expected_away_goals=float(row["expected_away_goals"]),
        model_version=state.version,
    )
