"""MLflow-backed model metrics queries."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import mlflow.artifacts
import mlflow.tracking


MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")
MODEL_ALIAS = "Production"
XGB_MODEL = "xgboost-match-classifier"


def fetch_model_metrics() -> dict:
    """Return current production XGBoost metrics + feature importance."""
    client = mlflow.tracking.MlflowClient(MLFLOW_URI)
    mv = client.get_model_version_by_alias(XGB_MODEL, MODEL_ALIAS)
    run = client.get_run(mv.run_id)
    metrics = run.data.metrics

    with tempfile.TemporaryDirectory() as tmpdir:
        fi_path = mlflow.artifacts.download_artifacts(
            run_id=mv.run_id,
            artifact_path="model/feature_importance.json",
            tracking_uri=MLFLOW_URI,
            dst_path=tmpdir,
        )
        feature_importance_raw = json.loads(Path(fi_path).read_text())

    return {
        "model_name": XGB_MODEL,
        "model_version": str(mv.version),
        "accuracy": float(
            metrics.get("accuracy_last_fold", metrics.get("cv_accuracy_mean", 0.0))
        ),
        "brier_score": float(
            metrics.get("brier_score_last_fold", metrics.get("cv_brier_mean", 0.0))
        ),
        "log_loss": (
            float(metrics["log_loss_last_fold"])
            if "log_loss_last_fold" in metrics
            else None
        ),
        "baseline_accuracy": float(metrics.get("baseline_home_win", 0.0)),
        "feature_importance": [
            {"name": name, "importance": float(importance)}
            for name, importance in feature_importance_raw.items()
        ],
    }
