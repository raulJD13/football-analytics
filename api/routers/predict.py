"""Router: POST /predict

Loads the Poisson match predictor from MLflow (Production alias) at startup
and serves probability predictions for a given home vs away fixture.

If MLflow is unreachable the router refuses to start — predictions without a
registered model would be silently wrong.  Set MLFLOW_TRACKING_URI in the
environment (default: http://localhost:5001).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status

import mlflow.artifacts
import mlflow.tracking

from api.schemas.predict import PredictRequest, PredictResponse

# Import the predictor class from the training script.
# Resolve the project root so this works regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.scripts.train_poisson import PoissonPredictor  # noqa: E402

log = logging.getLogger(__name__)

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")
REGISTERED_MODEL = "poisson-match-predictor"
MODEL_ALIAS = "Production"


# ── model loader ──────────────────────────────────────────────────────────────

class _ModelState:
    """Holds the loaded PoissonPredictor and its MLflow version string."""

    def __init__(self) -> None:
        self._predictor: PoissonPredictor | None = None
        self._version: str = "unknown"

    def load(self) -> None:
        """Download the team_params JSON from MLflow and initialise the predictor."""
        mlflow.set_tracking_uri(MLFLOW_URI)
        client = mlflow.tracking.MlflowClient(MLFLOW_URI)

        # Resolve version from alias
        mv = client.get_model_version_by_alias(REGISTERED_MODEL, MODEL_ALIAS)
        self._version = mv.version
        run_id = mv.run_id
        log.info("Loading model version %s (run %s) …", self._version, run_id)

        # Download the JSON artifact that was logged under model/team_params.json
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = mlflow.artifacts.download_artifacts(
                run_id=run_id,
                artifact_path="model/team_params.json",
                tracking_uri=MLFLOW_URI,
                dst_path=tmpdir,
            )
            with open(artifact_path) as f:
                params = json.load(f)

        predictor = PoissonPredictor()
        predictor._init_from_params(params)
        self._predictor = predictor
        log.info("Model version %s loaded.", self._version)

    @property
    def predictor(self) -> PoissonPredictor:
        if self._predictor is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        return self._predictor

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
        result = state.predictor.predict(None, input_df)
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
