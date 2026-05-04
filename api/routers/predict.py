"""Router: POST /predict

Loads models from MLflow (Production alias) at startup and serves
probability predictions for a given home vs away fixture.

Model priority
--------------
1. Ensemble (Poisson + XGBoost blend) — if 'ensemble-match-predictor' is
   registered in MLflow Production alias.
2. Poisson only — fallback when ensemble is unavailable.

The ensemble uses XGBoost features fetched live from ClickHouse on each
request; the Poisson model only needs the two team IDs.

Probability vector convention: [H, D, A] throughout.
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

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from xgboost import DMatrix, XGBClassifier

import mlflow.artifacts
import mlflow.tracking

from api.db.clickhouse import get_client
from api.db.predict_features import fetch_prediction_features
from api.schemas.predict import (
    FeatureContribution,
    PredictExplainResponse,
    PredictRequest,
    PredictResponse,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.scripts.train_poisson import PoissonPredictor  # noqa: E402

log = logging.getLogger(__name__)

MLFLOW_URI       = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")
POISSON_MODEL    = "poisson-match-predictor"
ENSEMBLE_MODEL   = "ensemble-match-predictor"
MODEL_ALIAS      = "Production"


# ── model state ───────────────────────────────────────────────────────────────

class _ModelState:
    """Holds loaded models and ensemble config.

    Tries to load the ensemble at startup; falls back to Poisson-only if
    the ensemble model is not yet registered or MLflow is unreachable.
    """

    def __init__(self) -> None:
        self._poisson: PoissonPredictor | None = None
        self._xgb: object | None = None
        self._xgb_base: XGBClassifier | None = None
        self._ensemble_config: dict | None = None   # {w_poisson, w_xgb, ...}
        self._poisson_version: str = "unknown"
        self._ensemble_version: str = "unknown"
        self._fallback_mode: bool = False

    # ── loaders ───────────────────────────────────────────────────────────────

    def _load_poisson(self, client: mlflow.tracking.MlflowClient) -> None:
        mv = client.get_model_version_by_alias(POISSON_MODEL, MODEL_ALIAS)
        self._poisson_version = mv.version
        with tempfile.TemporaryDirectory() as tmpdir:
            path = mlflow.artifacts.download_artifacts(
                run_id=mv.run_id,
                artifact_path="model/team_params.json",
                tracking_uri=MLFLOW_URI,
                dst_path=tmpdir,
            )
            params = json.loads(Path(path).read_text())
        predictor = PoissonPredictor()
        predictor._init_from_params(params)
        self._poisson = predictor
        log.info("Poisson model v%s loaded.", self._poisson_version)

    def _try_load_ensemble(self, client: mlflow.tracking.MlflowClient) -> None:
        """Attempt to load the ensemble config + XGBoost model.

        Silently skips if the ensemble has not been registered yet — the
        endpoint will fall back to Poisson-only mode.
        """
        try:
            mv = client.get_model_version_by_alias(ENSEMBLE_MODEL, MODEL_ALIAS)
        except mlflow.exceptions.MlflowException:
            log.info(
                "Ensemble model '%s' not found in MLflow — using Poisson only.",
                ENSEMBLE_MODEL,
            )
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            # Ensemble config (weights + component model names)
            cfg_path = mlflow.artifacts.download_artifacts(
                run_id=mv.run_id,
                artifact_path="model/ensemble_config.json",
                tracking_uri=MLFLOW_URI,
                dst_path=tmpdir,
            )
            self._ensemble_config = json.loads(Path(cfg_path).read_text())

            xgb_mv = client.get_model_version_by_alias(
                self._ensemble_config["xgb_model"], MODEL_ALIAS
            )
            xgb_path = mlflow.artifacts.download_artifacts(
                run_id=xgb_mv.run_id,
                artifact_path="model/xgb_model.json",
                tracking_uri=MLFLOW_URI,
                dst_path=tmpdir,
            )
            xgb = XGBClassifier()
            xgb.load_model(xgb_path)
            self._xgb_base = xgb
            self._xgb = xgb

        self._ensemble_version = mv.version
        w_p = self._ensemble_config["w_poisson"]
        w_x = self._ensemble_config["w_xgb"]
        log.info(
            "Ensemble v%s loaded: w_poisson=%.2f  w_xgb=%.2f  "
            "(brier_ensemble=%.4f vs brier_poisson=%.4f)",
            self._ensemble_version, w_p, w_x,
            self._ensemble_config["brier_ensemble"],
            self._ensemble_config["brier_poisson"],
        )

    def load(self) -> None:
        """Load all models at startup."""
        mlflow.set_tracking_uri(MLFLOW_URI)
        client = mlflow.tracking.MlflowClient(MLFLOW_URI)
        self._load_poisson(client)
        self._try_load_ensemble(client)

    # ── prediction ────────────────────────────────────────────────────────────

    @property
    def is_ensemble(self) -> bool:
        return self._ensemble_config is not None and self._xgb is not None

    def predict(
        self,
        home_team_id: int,
        away_team_id: int,
        xgb_features: pd.DataFrame | None,
    ) -> tuple[float, float, float]:
        """Return (p_home_win, p_draw, p_away_win).

        In ensemble mode ``xgb_features`` must be a one-row DataFrame.
        In Poisson-only mode it is ignored.
        """
        if self._poisson is None:
            self._fallback_mode = True
            return 0.45, 0.27, 0.28

        # ── Poisson probabilities: [H, D, A] ──────────────────────────────────
        input_df = pd.DataFrame([{
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
        }])
        poisson_out = self._poisson.predict(None, input_df).iloc[0]
        p_hda = np.array([
            float(poisson_out["home_win"]),
            float(poisson_out["draw"]),
            float(poisson_out["away_win"]),
        ])

        if not self.is_ensemble or xgb_features is None:
            return float(p_hda[0]), float(p_hda[1]), float(p_hda[2])

        # ── XGBoost probabilities: reorder from [A,D,H] → [H,D,A] ───────────
        aligned_xgb_features = self._align_xgb_features(xgb_features)
        xgb_probs_adh = self._xgb.predict_proba(aligned_xgb_features)[0]   # (3,)
        x_hda = np.array([xgb_probs_adh[2], xgb_probs_adh[1], xgb_probs_adh[0]])

        # ── blend ─────────────────────────────────────────────────────────────
        w_p = self._ensemble_config["w_poisson"]  # type: ignore[index]
        w_x = self._ensemble_config["w_xgb"]      # type: ignore[index]
        blended = w_p * p_hda + w_x * x_hda
        # Renormalise to guard against floating-point drift
        blended /= blended.sum()

        return float(blended[0]), float(blended[1]), float(blended[2])

    @property
    def poisson_predictor(self) -> PoissonPredictor:
        """Expose Poisson predictor for expected-goals calculation."""
        if self._poisson is None:
            raise RuntimeError("Model not loaded.")
        return self._poisson

    def explain_prediction(
        self,
        xgb_features: pd.DataFrame,
    ) -> tuple[list[FeatureContribution], str | None]:
        """Return top SHAP contributions for the predicted class."""
        if self._xgb_base is None:
            return [], None

        classifier = self._xgb if self._xgb is not None else self._xgb_base
        aligned_xgb_features = self._align_xgb_features(xgb_features)
        probs_adh = classifier.predict_proba(aligned_xgb_features)[0]  # type: ignore[attr-defined]
        predicted_idx_adh = int(np.argmax(probs_adh))
        label_by_idx = {0: "away_win", 1: "draw", 2: "home_win"}

        booster = self._xgb_base.get_booster()
        contribs = booster.predict(
            DMatrix(aligned_xgb_features, feature_names=list(aligned_xgb_features.columns)),
            pred_contribs=True,
            strict_shape=True,
        )
        predicted_contribs = contribs[0, predicted_idx_adh]
        feature_contribs = predicted_contribs[:-1]
        pairs = [
            FeatureContribution(
                feature=feature,
                value=float(aligned_xgb_features.iloc[0][feature]),
                contribution=float(contribution),
            )
            for feature, contribution in zip(aligned_xgb_features.columns, feature_contribs, strict=False)
        ]
        pairs.sort(key=lambda item: abs(item.contribution), reverse=True)
        return pairs[:6], label_by_idx[predicted_idx_adh]

    def _align_xgb_features(self, xgb_features: pd.DataFrame) -> pd.DataFrame:
        """Match inference features to the exact schema expected by the loaded booster."""
        if self._xgb_base is None:
            return xgb_features

        expected_features = self._xgb_base.get_booster().feature_names
        if not expected_features:
            return xgb_features

        aligned = xgb_features.copy()
        for feature in expected_features:
            if feature not in aligned.columns:
                aligned[feature] = 0.0
        return aligned.loc[:, expected_features]

    @property
    def model_version(self) -> str:
        if self._fallback_mode:
            return "fallback-demo"
        if self.is_ensemble:
            return f"ensemble-v{self._ensemble_version}"
        return f"poisson-v{self._poisson_version}"


_state = _ModelState()


def get_model() -> _ModelState:
    return _state


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app) -> AsyncGenerator[None, None]:  # type: ignore[type-arg]
    try:
        _state.load()
    except Exception as exc:
        _state._fallback_mode = True
        log.warning("Failed to load model from MLflow: %s", exc)
        log.warning("Starting API in fallback demo mode without registered models.")
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

    Uses the ensemble (Poisson + XGBoost) when available, otherwise the
    Poisson model alone.  Both team IDs must be football-data.org identifiers.
    Unknown teams degrade gracefully to league-average strength.
    """
    # ── XGBoost features (only fetched in ensemble mode) ─────────────────────
    xgb_features: pd.DataFrame | None = None
    if state.is_ensemble:
        try:
            ch_client = get_client()
            xgb_features = fetch_prediction_features(
                ch_client, body.home_team_id, body.away_team_id
            )
        except Exception as exc:
            log.warning(
                "Failed to fetch XGBoost features (%s) — falling back to Poisson only.",
                exc,
            )

    # ── blend (or Poisson-only) ───────────────────────────────────────────────
    try:
        p_home, p_draw, p_away = state.predict(
            body.home_team_id, body.away_team_id, xgb_features
        )
    except Exception as exc:
        log.exception("Prediction failed for %s vs %s", body.home_team_id, body.away_team_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction error: {exc}",
        ) from exc

    # ── expected goals always from Poisson ───────────────────────────────────
    if state._poisson is None:
        expected_home_goals = 1.4
        expected_away_goals = 1.1
    else:
        input_df = pd.DataFrame([{
            "home_team_id": body.home_team_id,
            "away_team_id": body.away_team_id,
        }])
        poisson_row = state.poisson_predictor.predict(None, input_df).iloc[0]
        expected_home_goals = float(poisson_row["expected_home_goals"])
        expected_away_goals = float(poisson_row["expected_away_goals"])

    return PredictResponse(
        home_team_id=body.home_team_id,
        away_team_id=body.away_team_id,
        home_win=p_home,
        draw=p_draw,
        away_win=p_away,
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
        model_version=state.model_version,
    )


@router.post(
    "/explain",
    response_model=PredictExplainResponse,
    summary="Predict LaLiga match outcome probabilities with SHAP explanation",
)
def explain(
    body: PredictRequest,
    state: _ModelState = Depends(get_model),
) -> PredictExplainResponse:
    xgb_features: pd.DataFrame | None = None
    top_contributions: list[FeatureContribution] = []
    explanation_label = "poisson_only"

    if state.is_ensemble:
        try:
            ch_client = get_client()
            xgb_features = fetch_prediction_features(
                ch_client, body.home_team_id, body.away_team_id
            )
            top_contributions, label = state.explain_prediction(xgb_features)
            if label is not None:
                explanation_label = label
        except Exception as exc:
            log.warning("Failed to build SHAP explanation (%s).", exc)

    try:
        p_home, p_draw, p_away = state.predict(
            body.home_team_id, body.away_team_id, xgb_features
        )
    except Exception as exc:
        log.exception("Prediction failed for %s vs %s", body.home_team_id, body.away_team_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction error: {exc}",
        ) from exc

    if state._poisson is None:
        expected_home_goals = 1.4
        expected_away_goals = 1.1
    else:
        input_df = pd.DataFrame([{
            "home_team_id": body.home_team_id,
            "away_team_id": body.away_team_id,
        }])
        poisson_row = state.poisson_predictor.predict(None, input_df).iloc[0]
        expected_home_goals = float(poisson_row["expected_home_goals"])
        expected_away_goals = float(poisson_row["expected_away_goals"])

    return PredictExplainResponse(
        home_team_id=body.home_team_id,
        away_team_id=body.away_team_id,
        home_win=p_home,
        draw=p_draw,
        away_win=p_away,
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
        model_version=state.model_version,
        top_contributions=top_contributions,
        explanation_label=explanation_label,
    )
