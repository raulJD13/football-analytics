"""train_classifier.py — XGBoost multi-class match outcome classifier.

Model
-----
XGBClassifier with objective='multi:softprob' predicting result ∈ {A, D, H}.
Target encoding: 0=A, 1=D, 2=H (alphabetical, matches XGBoost convention).

Features (from mart_match_features)
------------------------------------
home_form_5_ppg      — home form points / matches available (0-3 scale)
away_form_5_ppg      — away form points / matches available (0-3 scale)
home_attack_strength — home avg goals scored / league avg
away_defence_weakness — away avg goals conceded / league avg
h2h_home_win_rate    — historical H2H home win rate (default 0.45 when unknown)
home_rest_days       — days since last match (capped at MAX_REST_DAYS)
away_rest_days       — days since last match (capped at MAX_REST_DAYS)
rest_days_diff       — home_rest_days − away_rest_days
position_diff        — home_position − away_position (lower = worse rank)
h2h_matches_played   — H2H sample size (proxy for reliability of h2h_home_win_rate)

Validation
----------
TimeSeriesSplit(n_splits=3) on date-sorted data prevents future leakage.
With multiple seasons each fold ideally aligns with season boundaries.
With a single season the folds are intra-season expanding windows.

MLflow
------
Experiment  : football-match-prediction
Registered  : xgboost-match-classifier  (alias: Production after training)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

import clickhouse_connect
import mlflow
import mlflow.xgboost

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
LABEL_ENCODER = LabelEncoder()
LABEL_ENCODER.fit(["A", "D", "H"])            # 0=A, 1=D, 2=H (alphabetical)

FEATURES = [
    "home_form_5_ppg",
    "away_form_5_ppg",
    "home_attack_strength",
    "away_defence_weakness",
    "h2h_home_win_rate",
    "home_rest_days",
    "away_rest_days",
    "rest_days_diff",
    "position_diff",
    "h2h_matches_played",
]

# ClickHouse bug: lagInFrame returns epoch (day 0 ≈ 1970-01-01) instead of NULL
# for a team's very first match, producing ~20 000 day values.  Cap to a
# realistic upper bound so the model sees "long rest" not a numeric outlier.
MAX_REST_DAYS = 14

REGISTERED_MODEL = "xgboost-match-classifier"
EXPERIMENT_NAME = "football-match-prediction"

XGB_PARAMS: dict = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,      # conservative — small dataset
    "gamma": 1.0,
    "objective": "multi:softprob",
    "num_class": 3,
    "eval_metric": "mlogloss",
    "random_state": 42,
    "n_jobs": -1,
}


# ── data loading ─────────────────────────────────────────────────────────────

def load_features(client: clickhouse_connect.driver.Client) -> pd.DataFrame:
    """Load all finished matches with ML features, sorted oldest-first."""
    query = """
        SELECT
            match_id,
            match_date,
            matchday,
            home_team_id,
            away_team_id,
            result,
            home_form_5,
            away_form_5,
            home_form_matches_available,
            away_form_matches_available,
            home_attack_strength,
            away_defence_weakness,
            h2h_home_win_rate,
            h2h_matches_played,
            home_rest_days,
            away_rest_days,
            position_diff
        FROM football.mart_match_features
        WHERE result IN ('H', 'D', 'A')
        ORDER BY match_date, match_id
    """
    return client.query_df(query)


# ── feature engineering ───────────────────────────────────────────────────────

def build_feature_matrix(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, np.ndarray, pd.Series]:
    """Return (X, y, dates) ready for TimeSeriesSplit.

    Applies:
    - Form normalisation: points / max(matches_available, 1) → [0, 3] scale
    - Rest-day cap: clips outliers caused by ClickHouse epoch default
    - Derived feature: rest_days_diff = home − away rest
    - Label encoding: A→0, D→1, H→2
    """
    feat = pd.DataFrame(index=df.index)

    # Normalised form (points-per-game equivalent)
    feat["home_form_5_ppg"] = (
        df["home_form_5"] / df["home_form_matches_available"].clip(lower=1)
    ).astype(float)
    feat["away_form_5_ppg"] = (
        df["away_form_5"] / df["away_form_matches_available"].clip(lower=1)
    ).astype(float)

    # Strength / weakness ratios (already normalised by league avg in dbt)
    feat["home_attack_strength"] = df["home_attack_strength"].astype(float)
    feat["away_defence_weakness"] = df["away_defence_weakness"].astype(float)

    # H2H
    feat["h2h_home_win_rate"] = df["h2h_home_win_rate"].astype(float)
    feat["h2h_matches_played"] = df["h2h_matches_played"].astype(float)

    # Rest days — cap at MAX_REST_DAYS to suppress ClickHouse first-match outlier
    home_rest = df["home_rest_days"].clip(upper=MAX_REST_DAYS).astype(float)
    away_rest = df["away_rest_days"].clip(upper=MAX_REST_DAYS).astype(float)
    feat["home_rest_days"] = home_rest
    feat["away_rest_days"] = away_rest
    feat["rest_days_diff"] = home_rest - away_rest

    # Standings gap
    feat["position_diff"] = df["position_diff"].astype(float)

    y = LABEL_ENCODER.transform(df["result"].values)          # 0/1/2
    dates = pd.to_datetime(df["match_date"])

    return feat[FEATURES], y, dates


# ── season helpers (mirrors train_poisson.py) ─────────────────────────────────

def _season_year(date: pd.Timestamp) -> int:
    """August-anchored season year: Aug 2024 → 2024, May 2025 → 2024."""
    ts = pd.Timestamp(date)
    return ts.year if ts.month >= 8 else ts.year - 1


# ── evaluation helpers ────────────────────────────────────────────────────────

def _brier_score(probs: np.ndarray, y: np.ndarray) -> float:
    """Multi-class Brier score: mean of sum-of-squared errors over all classes."""
    n = len(y)
    one_hot = np.zeros_like(probs)
    one_hot[np.arange(n), y] = 1.0
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def evaluate_fold(
    model: XGBClassifier,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
) -> dict[str, float]:
    """Accuracy and Brier score for one validation fold."""
    probs = model.predict_proba(X_val)          # (n, 3)  — A / D / H columns
    preds = np.argmax(probs, axis=1)
    accuracy = float((preds == y_val).mean())
    brier = _brier_score(probs, y_val)

    # Baseline: always predict H (label 2)
    baseline_home_acc = float((y_val == 2).mean())

    return {
        "accuracy": accuracy,
        "brier_score": brier,
        "baseline_home_win": baseline_home_acc,
        "improvement_vs_baseline": accuracy - baseline_home_acc,
        "n_val": float(len(y_val)),
    }


# ── cross-validation ──────────────────────────────────────────────────────────

def temporal_cv(
    X: pd.DataFrame,
    y: np.ndarray,
    dates: pd.Series,
    n_splits: int = 3,
) -> list[dict[str, float]]:
    """Run TimeSeriesSplit and return per-fold metrics.

    Folds are expanding windows sorted by match date:
      fold 1: smallest train window → first validation window
      fold 3: largest train window → most recent validation window (most realistic)

    With 2+ seasons the natural boundaries align with season changeovers.
    With one season the folds are intra-season expanding windows.
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics: list[dict[str, float]] = []

    # Log season composition of each fold for interpretability
    season_series = dates.apply(_season_year)
    n_seasons = season_series.nunique()
    if n_seasons == 1:
        log.warning(
            "Only one season in the dataset — TimeSeriesSplit creates "
            "intra-season folds (not cross-season). Accuracy estimates will be "
            "optimistic until more seasons are available."
        )

    for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X), start=1):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        train_seasons = sorted(season_series.iloc[train_idx].unique())
        val_seasons   = sorted(season_series.iloc[val_idx].unique())
        train_date_range = f"{dates.iloc[train_idx].min().date()} → {dates.iloc[train_idx].max().date()}"
        val_date_range   = f"{dates.iloc[val_idx].min().date()} → {dates.iloc[val_idx].max().date()}"

        log.info(
            "Fold %d — train: %d matches [seasons %s] %s | "
            "val: %d matches [seasons %s] %s",
            fold_idx,
            len(train_idx), train_seasons, train_date_range,
            len(val_idx),   val_seasons,   val_date_range,
        )

        model = XGBClassifier(**XGB_PARAMS)
        model.fit(
            X_tr, y_tr,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        metrics = evaluate_fold(model, X_val, y_val)
        metrics["fold"] = float(fold_idx)
        fold_metrics.append(metrics)

        log.info(
            "  accuracy=%.3f | brier=%.4f | baseline_home=%.3f | "
            "improvement=%+.3f pp",
            metrics["accuracy"], metrics["brier_score"],
            metrics["baseline_home_win"], metrics["improvement_vs_baseline"],
        )

    return fold_metrics


# ── final model (all data) ────────────────────────────────────────────────────

def train_final(X: pd.DataFrame, y: np.ndarray) -> XGBClassifier:
    """Train on the full dataset for production deployment."""
    model = XGBClassifier(**XGB_PARAMS)
    model.fit(X, y)
    return model


# ── Poisson baseline retrieval ────────────────────────────────────────────────

def _fetch_poisson_accuracy(mlflow_uri: str) -> float | None:
    """Return the out-of-sample accuracy of the latest Poisson run, or None."""
    try:
        client = mlflow.tracking.MlflowClient(mlflow_uri)
        runs = client.search_runs(
            experiment_ids=["1"],
            filter_string="params.eval_strategy = 'last_season_holdout'",
            order_by=["start_time DESC"],
            max_results=1,
        )
        if runs:
            return runs[0].data.metrics.get("accuracy_out_of_sample")
    except Exception as exc:
        log.warning("Could not fetch Poisson baseline: %s", exc)
    return None


# ── training entry point ──────────────────────────────────────────────────────

def train(
    ch_host: str = "localhost",
    ch_port: int = 8124,
    ch_db: str = "football",
    mlflow_uri: str = "http://localhost:5000",
    n_splits: int = 3,
) -> str:
    """Run the full XGBoost training pipeline and return the MLflow run ID."""
    # ── connect ───────────────────────────────────────────────────────────────
    log.info("Connecting to ClickHouse at %s:%d/%s", ch_host, ch_port, ch_db)
    client = clickhouse_connect.get_client(host=ch_host, port=ch_port, database=ch_db)

    # ── load & engineer features ──────────────────────────────────────────────
    log.info("Loading features from mart_match_features …")
    raw = load_features(client)
    log.info("  %d finished matches loaded", len(raw))

    X, y, dates = build_feature_matrix(raw)

    # ── cross-validation ──────────────────────────────────────────────────────
    log.info("Running TimeSeriesSplit(n_splits=%d) …", n_splits)
    fold_metrics = temporal_cv(X, y, dates, n_splits=n_splits)

    accuracies    = [m["accuracy"]   for m in fold_metrics]
    briers        = [m["brier_score"] for m in fold_metrics]
    cv_acc_mean   = float(np.mean(accuracies))
    cv_acc_std    = float(np.std(accuracies))
    last_fold     = fold_metrics[-1]            # most recent = most realistic

    log.info(
        "CV summary — accuracy: %.3f ± %.3f | last fold: %.3f | "
        "brier last fold: %.4f",
        cv_acc_mean, cv_acc_std,
        last_fold["accuracy"], last_fold["brier_score"],
    )

    # ── final model on all data ───────────────────────────────────────────────
    log.info("Training final model on all %d matches …", len(X))
    final_model = train_final(X, y)

    # ── feature importance ────────────────────────────────────────────────────
    importance_gain = dict(zip(FEATURES, final_model.feature_importances_))
    # Sort descending for readability
    importance_sorted = dict(
        sorted(importance_gain.items(), key=lambda kv: kv[1], reverse=True)
    )
    # XGBoost returns float32 — convert to native float for JSON serialisation
    importance_sorted = {k: float(v) for k, v in importance_sorted.items()}
    log.info("Feature importance (gain):")
    for feat_name, score in importance_sorted.items():
        log.info("  %-30s %.4f", feat_name, score)

    # ── Poisson comparison ────────────────────────────────────────────────────
    poisson_acc = _fetch_poisson_accuracy(mlflow_uri)
    if poisson_acc is not None:
        improvement_vs_poisson = last_fold["accuracy"] - poisson_acc
        log.info(
            "vs Poisson (OOS) → XGBoost last fold=%.3f | Poisson=%.3f | "
            "diff=%+.3f pp",
            last_fold["accuracy"], poisson_acc, improvement_vs_poisson,
        )
    else:
        improvement_vs_poisson = None

    # ── MLflow ────────────────────────────────────────────────────────────────
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name="xgboost_classifier") as run:
        # Parameters
        mlflow.log_params({
            "model_type": "XGBClassifier",
            "n_splits_cv": n_splits,
            "features": ",".join(FEATURES),
            "n_features": len(FEATURES),
            "n_matches": len(X),
            "target_encoding": "0=A,1=D,2=H",
            **{f"xgb_{k}": v for k, v in XGB_PARAMS.items()},
        })

        # Per-fold accuracy for traceability
        for m in fold_metrics:
            fold = int(m["fold"])
            mlflow.log_metrics({
                f"fold_{fold}_accuracy":    m["accuracy"],
                f"fold_{fold}_brier":       m["brier_score"],
                f"fold_{fold}_n_val":       m["n_val"],
            })

        # Summary metrics
        summary: dict[str, float] = {
            "cv_accuracy_mean":        cv_acc_mean,
            "cv_accuracy_std":         cv_acc_std,
            "accuracy_last_fold":      last_fold["accuracy"],
            "brier_score_last_fold":   last_fold["brier_score"],
            "baseline_home_win":       last_fold["baseline_home_win"],
            "improvement_vs_baseline": last_fold["improvement_vs_baseline"],
        }
        if improvement_vs_poisson is not None:
            summary["poisson_accuracy_oos"]    = poisson_acc  # type: ignore[assignment]
            summary["improvement_vs_poisson"]  = improvement_vs_poisson
        mlflow.log_metrics(summary)

        # Artifact: feature importance JSON
        with tempfile.TemporaryDirectory() as tmpdir:
            fi_path = Path(tmpdir) / "feature_importance.json"
            fi_path.write_text(json.dumps(importance_sorted, indent=2))
            mlflow.log_artifact(str(fi_path), artifact_path="model")

            # Save XGBoost model as JSON for portability
            model_path = Path(tmpdir) / "xgb_model.json"
            final_model.save_model(str(model_path))
            mlflow.log_artifact(str(model_path), artifact_path="model")

        run_id = run.info.run_id
        log.info("MLflow run %s logged", run_id)

    # ── register as Production ────────────────────────────────────────────────
    model_uri = f"runs:/{run_id}/model"
    mlclient = mlflow.tracking.MlflowClient(mlflow_uri)
    try:
        mlclient.create_registered_model(REGISTERED_MODEL)
        log.info("Created registered model '%s'", REGISTERED_MODEL)
    except mlflow.exceptions.MlflowException:
        pass  # already exists

    mv = mlclient.create_model_version(
        name=REGISTERED_MODEL,
        source=model_uri,
        run_id=run_id,
    )
    mlclient.set_registered_model_alias(REGISTERED_MODEL, "Production", mv.version)
    log.info("Registered '%s' version %s as Production", REGISTERED_MODEL, mv.version)

    return run_id


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train the XGBoost match classifier.")
    p.add_argument("--ch-host",    default="localhost")
    p.add_argument("--ch-port",    type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8124")))
    p.add_argument("--ch-db",      default=os.getenv("CLICKHOUSE_DB", "football"))
    p.add_argument("--mlflow-uri", default="http://localhost:5001")
    p.add_argument("--n-splits",   type=int, default=3)
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
    run_id = train(
        ch_host=args.ch_host,
        ch_port=args.ch_port,
        ch_db=args.ch_db,
        mlflow_uri=args.mlflow_uri,
        n_splits=args.n_splits,
    )
    log.info("Done. Run ID: %s", run_id)
