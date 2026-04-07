"""ensemble.py — Weighted ensemble of Poisson + XGBoost models.

Strategy
--------
1. Load both Production models from MLflow (already trained).
2. Evaluate each independently on the holdout split.
3. Grid-search over (w_poisson, w_xgb) weight pairs and pick the combo
   with the lowest Brier score.
4. Guard: only activate the ensemble if the best XGBoost Brier score is
   *lower* (better) than Poisson's Brier score on the same holdout.
   A worse XGBoost would drag the ensemble down.
5. Log the chosen config to a dedicated MLflow experiment and register
   as 'ensemble-match-predictor' (Production alias).

Probability vector convention: [H, D, A] throughout.
  - Poisson predictor.predict() → columns: home_win, draw, away_win  (H, D, A) ✓
  - XGBClassifier.predict_proba() → columns 0=A, 1=D, 2=H → reorder to (H, D, A)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import clickhouse_connect
import mlflow
import mlflow.tracking
import mlflow.artifacts

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── resolve project root so relative imports work regardless of cwd ───────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.scripts.train_poisson import PoissonPredictor, split_train_holdout  # noqa: E402
from ml.scripts.train_classifier import (  # noqa: E402
    FEATURES,
    MAX_REST_DAYS,
    build_feature_matrix,
    load_features,
)

# ── constants ─────────────────────────────────────────────────────────────────
POISSON_MODEL    = "poisson-match-predictor"
XGB_MODEL        = "xgboost-match-classifier"
ENSEMBLE_MODEL   = "ensemble-match-predictor"
MODEL_ALIAS      = "Production"
EXPERIMENT_NAME  = "football-ensemble-prediction"

# (w_poisson, w_xgb) pairs to test
WEIGHT_GRID: list[tuple[float, float]] = [
    (0.20, 0.80),
    (0.30, 0.70),
    (0.35, 0.65),
    (0.40, 0.60),
]


# ── model loaders ─────────────────────────────────────────────────────────────

def _load_poisson(mlflow_uri: str) -> tuple[PoissonPredictor, str]:
    """Return (PoissonPredictor, version_string) from MLflow Production alias."""
    client = mlflow.tracking.MlflowClient(mlflow_uri)
    mv = client.get_model_version_by_alias(POISSON_MODEL, MODEL_ALIAS)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = mlflow.artifacts.download_artifacts(
            run_id=mv.run_id,
            artifact_path="model/team_params.json",
            tracking_uri=mlflow_uri,
            dst_path=tmpdir,
        )
        params = json.loads(Path(path).read_text())
    predictor = PoissonPredictor()
    predictor._init_from_params(params)
    log.info("Loaded Poisson model version %s (run %s)", mv.version, mv.run_id)
    return predictor, mv.version


def _load_xgb(mlflow_uri: str) -> tuple[object, str]:
    """Return classifier object with predict_proba from MLflow Production alias."""
    client = mlflow.tracking.MlflowClient(mlflow_uri)
    mv = client.get_model_version_by_alias(XGB_MODEL, MODEL_ALIAS)
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            path = mlflow.artifacts.download_artifacts(
                run_id=mv.run_id,
                artifact_path="model/classifier.joblib",
                tracking_uri=mlflow_uri,
                dst_path=tmpdir,
            )
            model = joblib.load(path)
        except mlflow.exceptions.MlflowException:
            from xgboost import XGBClassifier

            path = mlflow.artifacts.download_artifacts(
                run_id=mv.run_id,
                artifact_path="model/xgb_model.json",
                tracking_uri=mlflow_uri,
                dst_path=tmpdir,
            )
            model = XGBClassifier()
            model.load_model(path)
    log.info("Loaded XGBoost model version %s (run %s)", mv.version, mv.run_id)
    return model, mv.version


# ── probability extraction ────────────────────────────────────────────────────

def _poisson_probs_hda(predictor: PoissonPredictor, df: pd.DataFrame) -> np.ndarray:
    """Return (n, 3) array in [H, D, A] order from PoissonPredictor."""
    input_df = df[["home_team_id", "away_team_id"]].copy()
    out = predictor.predict(None, input_df)
    # predict() returns columns: home_win, draw, away_win  →  already [H, D, A]
    return out[["home_win", "draw", "away_win"]].to_numpy(dtype=float)


def _xgb_probs_hda(model: object, X: pd.DataFrame) -> np.ndarray:
    """Return (n, 3) array in [H, D, A] order from classifier.

    XGBoost predict_proba columns are ordered by label index:
        col 0 = A (label 0), col 1 = D (label 1), col 2 = H (label 2)
    Reorder to [H, D, A] = columns [2, 1, 0].
    """
    probs_adh = model.predict_proba(X)     # type: ignore[attr-defined]
    return probs_adh[:, [2, 1, 0]]         # → H D A


# ── Brier score ───────────────────────────────────────────────────────────────

def _brier(probs_hda: np.ndarray, results: pd.Series) -> float:
    """Multi-class Brier score with [H, D, A] probability vector.

    Lower is better (perfect model = 0, random uniform = 0.667).
    """
    idx_map = {"H": 0, "D": 1, "A": 2}
    y_idx = np.array([idx_map[r] for r in results], dtype=int)
    one_hot = np.zeros_like(probs_hda)
    one_hot[np.arange(len(y_idx)), y_idx] = 1.0
    return float(np.mean(np.sum((probs_hda - one_hot) ** 2, axis=1)))


def _accuracy(probs_hda: np.ndarray, results: pd.Series) -> float:
    labels = ["H", "D", "A"]
    preds = [labels[i] for i in np.argmax(probs_hda, axis=1)]
    return float(np.mean([p == a for p, a in zip(preds, results)]))


# ── grid search ───────────────────────────────────────────────────────────────

def _grid_search(
    poisson_hda: np.ndarray,
    xgb_hda: np.ndarray,
    results: pd.Series,
) -> pd.DataFrame:
    """Evaluate all weight combinations plus pure-model baselines.

    Returns a DataFrame sorted by brier_score ascending.
    """
    rows = []
    for label, p, x in [
        ("poisson_only",  1.0, 0.0),
        ("xgb_only",      0.0, 1.0),
        *[(f"w{int(wp*100)}_p_{int(wx*100)}_x", wp, wx) for wp, wx in WEIGHT_GRID],
    ]:
        blend = p * poisson_hda + x * xgb_hda
        rows.append({
            "label":        label,
            "w_poisson":    p,
            "w_xgb":        x,
            "brier_score":  _brier(blend, results),
            "accuracy":     _accuracy(blend, results),
        })

    df = pd.DataFrame(rows).sort_values("brier_score").reset_index(drop=True)
    return df


# ── main training routine ─────────────────────────────────────────────────────

def run(
    ch_host: str  = "localhost",
    ch_port: int  = 8124,
    ch_db:   str  = "football",
    mlflow_uri: str = "http://localhost:5000",
) -> str:
    """Evaluate ensemble, pick best weights, register in MLflow.

    Returns the MLflow run ID of the ensemble experiment.
    """
    mlflow.set_tracking_uri(mlflow_uri)

    # ── load data (features + result + date) ──────────────────────────────────
    log.info("Connecting to ClickHouse at %s:%d/%s", ch_host, ch_port, ch_db)
    ch_client = clickhouse_connect.get_client(host=ch_host, port=ch_port, database=ch_db)
    raw = load_features(ch_client)
    log.info("  %d finished matches loaded", len(raw))

    _, holdout = split_train_holdout(raw)
    if len(holdout) == 0:
        log.warning(
            "Only one season available — holdout is empty. "
            "Falling back to in-sample evaluation for the ensemble."
        )
        holdout = raw

    log.info("Holdout: %d matches", len(holdout))

    # ── build XGBoost feature matrix ──────────────────────────────────────────
    X_holdout, _, _ = build_feature_matrix(holdout)

    # ── load models from MLflow ───────────────────────────────────────────────
    poisson, poisson_ver = _load_poisson(mlflow_uri)
    xgb, xgb_ver        = _load_xgb(mlflow_uri)

    # ── get probability vectors — both in [H, D, A] order ────────────────────
    p_hda  = _poisson_probs_hda(poisson, holdout)
    x_hda  = _xgb_probs_hda(xgb, X_holdout)

    # ── grid search ───────────────────────────────────────────────────────────
    grid = _grid_search(p_hda, x_hda, holdout["result"])

    log.info("Grid search results (sorted by Brier score):")
    for _, row in grid.iterrows():
        log.info(
            "  %-30s  brier=%.4f  accuracy=%.3f  (w_p=%.2f  w_x=%.2f)",
            row["label"], row["brier_score"], row["accuracy"],
            row["w_poisson"], row["w_xgb"],
        )

    brier_poisson = float(grid.loc[grid["label"] == "poisson_only", "brier_score"].iloc[0])
    brier_xgb     = float(grid.loc[grid["label"] == "xgb_only",     "brier_score"].iloc[0])
    best_row      = grid.iloc[0]  # lowest brier

    # ── guard: only use ensemble/xgb if xgb beats poisson ───────────────────
    if brier_xgb >= brier_poisson:
        log.warning(
            "XGBoost Brier (%.4f) ≥ Poisson Brier (%.4f). "
            "XGBoost does NOT improve over Poisson — keeping Poisson only. "
            "No ensemble model will be registered.",
            brier_xgb, brier_poisson,
        )
        return ""

    log.info(
        "XGBoost improves over Poisson: Brier %.4f → %.4f (-%0.4f). "
        "Best combo: %s (brier=%.4f)",
        brier_poisson, brier_xgb, brier_poisson - brier_xgb,
        best_row["label"], best_row["brier_score"],
    )

    # Best combo may be xgb_only or a blend — use it
    w_p = float(best_row["w_poisson"])
    w_x = float(best_row["w_xgb"])

    # ── log to MLflow ─────────────────────────────────────────────────────────
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name="ensemble") as run:
        mlflow.log_params({
            "w_poisson":           w_p,
            "w_xgb":               w_x,
            "best_label":          str(best_row["label"]),
            "poisson_model":       POISSON_MODEL,
            "poisson_version":     poisson_ver,
            "xgb_model":           XGB_MODEL,
            "xgb_version":         xgb_ver,
            "weight_grid":         str(WEIGHT_GRID),
            "n_holdout_matches":   len(holdout),
            "eval_strategy":       "last_season_holdout",
        })

        mlflow.log_metrics({
            "brier_poisson":               brier_poisson,
            "brier_xgb":                   brier_xgb,
            "brier_ensemble":              float(best_row["brier_score"]),
            "improvement_over_poisson":    brier_poisson - float(best_row["brier_score"]),
            "accuracy_ensemble":           float(best_row["accuracy"]),
            "accuracy_poisson":            float(grid.loc[grid["label"] == "poisson_only", "accuracy"].iloc[0]),
            "accuracy_xgb":                float(grid.loc[grid["label"] == "xgb_only", "accuracy"].iloc[0]),
        })

        # Save all grid results + chosen config as artifacts
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            grid.to_csv(tmpdir_path / "weight_grid_results.csv", index=False)
            mlflow.log_artifact(str(tmpdir_path / "weight_grid_results.csv"), artifact_path="model")

            config = {
                "w_poisson":       w_p,
                "w_xgb":           w_x,
                "poisson_model":   POISSON_MODEL,
                "xgb_model":       XGB_MODEL,
                "brier_ensemble":  float(best_row["brier_score"]),
                "brier_poisson":   brier_poisson,
                "brier_xgb":       brier_xgb,
            }
            config_path = tmpdir_path / "ensemble_config.json"
            config_path.write_text(json.dumps(config, indent=2))
            mlflow.log_artifact(str(config_path), artifact_path="model")

        run_id = run.info.run_id
        log.info("Ensemble run %s logged to experiment '%s'", run_id, EXPERIMENT_NAME)

    # ── register as Production ────────────────────────────────────────────────
    model_uri = f"runs:/{run_id}/model"
    ml_client = mlflow.tracking.MlflowClient(mlflow_uri)

    try:
        ml_client.create_registered_model(ENSEMBLE_MODEL)
        log.info("Created registered model '%s'", ENSEMBLE_MODEL)
    except mlflow.exceptions.MlflowException:
        pass  # already exists

    mv = ml_client.create_model_version(
        name=ENSEMBLE_MODEL,
        source=model_uri,
        run_id=run_id,
    )
    ml_client.set_registered_model_alias(ENSEMBLE_MODEL, MODEL_ALIAS, mv.version)
    log.info("Registered '%s' version %s as Production", ENSEMBLE_MODEL, mv.version)

    return run_id


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build and evaluate the ensemble model.")
    p.add_argument("--ch-host",    default="localhost")
    p.add_argument("--ch-port",    type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8124")))
    p.add_argument("--ch-db",      default=os.getenv("CLICKHOUSE_DB", "football"))
    p.add_argument("--mlflow-uri", default="http://localhost:5001")
    return p.parse_args()


if __name__ == "__main__":
    try:
        import os as _os
        from dotenv import load_dotenv
        load_dotenv()
        _os.environ.pop("MLFLOW_TRACKING_URI", None)
    except ImportError:
        pass

    args = _parse_args()
    run_id = run(
        ch_host=args.ch_host,
        ch_port=args.ch_port,
        ch_db=args.ch_db,
        mlflow_uri=args.mlflow_uri,
    )
    if run_id:
        log.info("Done. Run ID: %s", run_id)
    else:
        log.info("No ensemble registered — Poisson remains the Production model.")
