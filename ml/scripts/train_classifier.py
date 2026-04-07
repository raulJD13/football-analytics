"""train_classifier.py — calibrated XGBoost multi-class match outcome model.

Model
-----
XGBoost predicts result ∈ {A, D, H}. The training pipeline now includes:
  - Optuna tuning over max_depth / learning_rate / min_child_weight
  - draw-focused SMOTE oversampling on training windows only
  - post-hoc probability calibration (Platt scaling / sigmoid)

Target encoding: 0=A, 1=D, 2=H (alphabetical, matches XGBoost convention).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import optuna
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

import clickhouse_connect
import mlflow

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ── constants ────────────────────────────────────────────────────────────────
LABEL_ENCODER = LabelEncoder()
LABEL_ENCODER.fit(["A", "D", "H"])  # 0=A, 1=D, 2=H

FEATURES = [
    "home_form_5_ppg",
    "away_form_5_ppg",
    "home_attack_strength",
    "away_defence_weakness",
    "home_elo_diff",
    "h2h_home_win_rate",
    "home_rest_days",
    "away_rest_days",
    "rest_days_diff",
    "position_diff",
    "h2h_matches_played",
]

MAX_REST_DAYS = 14
ELO_BASE_RATING = 1500.0
ELO_K_FACTOR = 24.0
ELO_HOME_ADVANTAGE = 60.0
ELO_SEASON_CARRYOVER = 0.75
CALIBRATION_METHOD = "sigmoid"
CALIBRATION_FRACTION = 0.18
MIN_CALIBRATION_ROWS = 60
MIN_TRAIN_ROWS_AFTER_SPLIT = 120
MIN_ROWS_PER_CLASS_FOR_SMOTE = 6
SMOTE_RANDOM_STATE = 42
DRAW_LABEL = 1
OPTUNA_N_TRIALS = 20

REGISTERED_MODEL = "xgboost-match-classifier"
EXPERIMENT_NAME = "football-match-prediction"

XGB_DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
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
    """Return (X, y, dates) ready for time-aware training."""
    feat = pd.DataFrame(index=df.index)

    feat["home_form_5_ppg"] = (
        df["home_form_5"] / df["home_form_matches_available"].clip(lower=1)
    ).astype(float)
    feat["away_form_5_ppg"] = (
        df["away_form_5"] / df["away_form_matches_available"].clip(lower=1)
    ).astype(float)

    feat["home_attack_strength"] = df["home_attack_strength"].astype(float)
    feat["away_defence_weakness"] = df["away_defence_weakness"].astype(float)
    feat["home_elo_diff"] = compute_pre_match_elo_diff(df)

    feat["h2h_home_win_rate"] = df["h2h_home_win_rate"].astype(float)
    feat["h2h_matches_played"] = df["h2h_matches_played"].astype(float)

    home_rest = df["home_rest_days"].clip(upper=MAX_REST_DAYS).astype(float)
    away_rest = df["away_rest_days"].clip(upper=MAX_REST_DAYS).astype(float)
    feat["home_rest_days"] = home_rest
    feat["away_rest_days"] = away_rest
    feat["rest_days_diff"] = home_rest - away_rest

    feat["position_diff"] = df["position_diff"].astype(float)

    y = LABEL_ENCODER.transform(df["result"].values)
    dates = pd.to_datetime(df["match_date"])
    return feat[FEATURES], y, dates


# ── season helpers ────────────────────────────────────────────────────────────

def _season_year(date: pd.Timestamp) -> int:
    """August-anchored season year: Aug 2024 → 2024, May 2025 → 2024."""
    ts = pd.Timestamp(date)
    return ts.year if ts.month >= 8 else ts.year - 1


def _regress_elo_ratings(ratings: dict[int, float]) -> dict[int, float]:
    """Pull Elo ratings partway back to the mean at season rollover."""
    return {
        team_id: ELO_BASE_RATING + (rating - ELO_BASE_RATING) * ELO_SEASON_CARRYOVER
        for team_id, rating in ratings.items()
    }


def compute_pre_match_elo_diff(df: pd.DataFrame) -> pd.Series:
    """Return pre-match home Elo minus away Elo for each fixture in order."""
    ratings: dict[int, float] = {}
    current_season: int | None = None
    diffs: list[float] = []

    for row in df.itertuples(index=False):
        season = _season_year(pd.Timestamp(row.match_date))
        if current_season is None:
            current_season = season
        elif season != current_season:
            ratings = _regress_elo_ratings(ratings)
            current_season = season

        home_team_id = int(row.home_team_id)
        away_team_id = int(row.away_team_id)
        home_rating = ratings.get(home_team_id, ELO_BASE_RATING)
        away_rating = ratings.get(away_team_id, ELO_BASE_RATING)
        diffs.append(home_rating - away_rating)

        expected_home = 1.0 / (
            1.0 + 10.0 ** ((away_rating - (home_rating + ELO_HOME_ADVANTAGE)) / 400.0)
        )
        actual_home = {"H": 1.0, "D": 0.5, "A": 0.0}[str(row.result)]
        delta = ELO_K_FACTOR * (actual_home - expected_home)

        ratings[home_team_id] = home_rating + delta
        ratings[away_team_id] = away_rating - delta

    return pd.Series(diffs, index=df.index, dtype=float)


def compute_current_elo_ratings(df: pd.DataFrame) -> dict[int, float]:
    """Return current Elo ratings after processing historical matches in order."""
    ratings: dict[int, float] = {}
    current_season: int | None = None

    for row in df.itertuples(index=False):
        season = _season_year(pd.Timestamp(row.match_date))
        if current_season is None:
            current_season = season
        elif season != current_season:
            ratings = _regress_elo_ratings(ratings)
            current_season = season

        home_team_id = int(row.home_team_id)
        away_team_id = int(row.away_team_id)
        home_rating = ratings.get(home_team_id, ELO_BASE_RATING)
        away_rating = ratings.get(away_team_id, ELO_BASE_RATING)

        expected_home = 1.0 / (
            1.0 + 10.0 ** ((away_rating - (home_rating + ELO_HOME_ADVANTAGE)) / 400.0)
        )
        actual_home = {"H": 1.0, "D": 0.5, "A": 0.0}[str(row.result)]
        delta = ELO_K_FACTOR * (actual_home - expected_home)

        ratings[home_team_id] = home_rating + delta
        ratings[away_team_id] = away_rating - delta

    return ratings


# ── metrics ──────────────────────────────────────────────────────────────────

def _brier_score(probs: np.ndarray, y: np.ndarray) -> float:
    """Multi-class Brier score: lower is better."""
    one_hot = np.zeros_like(probs)
    one_hot[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def _multiclass_log_loss(probs: np.ndarray, y: np.ndarray) -> float:
    """Stable multi-class log-loss."""
    chosen = probs[np.arange(len(y)), y]
    return float(-np.mean(np.log(np.clip(chosen, 1e-7, 1.0))))


def _draw_metrics(probs: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Return metrics focused on the draw class."""
    preds = np.argmax(probs, axis=1)
    actual_draw = y == DRAW_LABEL
    predicted_draw = preds == DRAW_LABEL

    true_positive = int(np.sum(actual_draw & predicted_draw))
    actual_count = int(np.sum(actual_draw))
    predicted_count = int(np.sum(predicted_draw))

    recall = true_positive / actual_count if actual_count else 0.0
    precision = true_positive / predicted_count if predicted_count else 0.0
    predicted_rate = predicted_count / len(y)
    actual_rate = actual_count / len(y)

    return {
        "draw_recall": float(recall),
        "draw_precision": float(precision),
        "draw_rate_actual": float(actual_rate),
        "draw_rate_predicted": float(predicted_rate),
        "draw_rate_gap": float(predicted_rate - actual_rate),
    }


def evaluate_fold(model: Any, X_val: pd.DataFrame, y_val: np.ndarray) -> dict[str, float]:
    """Accuracy, Brier, log-loss, and draw metrics for one validation fold."""
    probs = model.predict_proba(X_val)
    preds = np.argmax(probs, axis=1)
    accuracy = float((preds == y_val).mean())
    brier = _brier_score(probs, y_val)
    log_loss = _multiclass_log_loss(probs, y_val)
    baseline_home_acc = float((y_val == 2).mean())

    metrics = {
        "accuracy": accuracy,
        "brier_score": brier,
        "log_loss": log_loss,
        "baseline_home_win": baseline_home_acc,
        "improvement_vs_baseline": accuracy - baseline_home_acc,
        "n_val": float(len(y_val)),
    }
    metrics.update(_draw_metrics(probs, y_val))
    return metrics


# ── training helpers ─────────────────────────────────────────────────────────

def _make_xgb_params(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(XGB_DEFAULT_PARAMS)
    if overrides:
        params.update(overrides)
    params["max_depth"] = int(params["max_depth"])
    params["min_child_weight"] = int(params["min_child_weight"])
    return params


def _maybe_apply_smote(X: pd.DataFrame, y: np.ndarray) -> tuple[pd.DataFrame, np.ndarray, bool]:
    """Oversample the draw class only when it is underrepresented."""
    class_counts = pd.Series(y).value_counts().sort_index()
    draw_count = int(class_counts.get(DRAW_LABEL, 0))
    if draw_count < MIN_ROWS_PER_CLASS_FOR_SMOTE:
        return X, y, False

    other_counts = [int(class_counts.get(label, 0)) for label in [0, 2]]
    target_draw = int(min(max(other_counts), round(np.mean(other_counts))))
    if target_draw <= draw_count:
        return X, y, False

    smote = SMOTE(
        sampling_strategy={DRAW_LABEL: target_draw},
        random_state=SMOTE_RANDOM_STATE,
        k_neighbors=min(5, draw_count - 1),
    )
    X_resampled, y_resampled = smote.fit_resample(X, y)
    return (
        pd.DataFrame(X_resampled, columns=X.columns),
        np.asarray(y_resampled),
        True,
    )


def _split_for_calibration(
    X: pd.DataFrame,
    y: np.ndarray,
    min_calibration_rows: int = MIN_CALIBRATION_ROWS,
    calibration_fraction: float = CALIBRATION_FRACTION,
) -> tuple[pd.DataFrame, np.ndarray, pd.DataFrame, np.ndarray] | None:
    """Split the latest part of the training window for calibration."""
    n_rows = len(X)
    desired_cal = max(min_calibration_rows, int(n_rows * calibration_fraction))
    max_cal = n_rows - MIN_TRAIN_ROWS_AFTER_SPLIT
    if max_cal < min_calibration_rows:
        return None

    cal_size = min(desired_cal, max_cal)
    for size in range(cal_size, max_cal + 1):
        split_at = n_rows - size
        y_fit = y[:split_at]
        y_cal = y[split_at:]
        if len(np.unique(y_fit)) == 3 and len(np.unique(y_cal)) == 3:
            return X.iloc[:split_at], y_fit, X.iloc[split_at:], y_cal
    return None


def train_predictive_model(
    X: pd.DataFrame,
    y: np.ndarray,
    params: dict[str, Any],
) -> tuple[Any, XGBClassifier, dict[str, Any]]:
    """Train XGBoost with draw oversampling and optional Platt calibration."""
    split = _split_for_calibration(X, y)
    fit_info: dict[str, Any] = {
        "calibration_method": "none",
        "calibration_rows": 0,
        "train_rows": int(len(X)),
        "used_smote": False,
    }

    if split is None:
        X_fit, y_fit, used_smote = _maybe_apply_smote(X, y)
        base_model = XGBClassifier(**_make_xgb_params(params))
        base_model.fit(X_fit, y_fit)
        fit_info["used_smote"] = used_smote
        return base_model, base_model, fit_info

    X_train_raw, y_train_raw, X_cal, y_cal = split
    X_train_fit, y_train_fit, used_smote = _maybe_apply_smote(X_train_raw, y_train_raw)

    base_model = XGBClassifier(**_make_xgb_params(params))
    base_model.fit(X_train_fit, y_train_fit)

    calibrator = CalibratedClassifierCV(
        estimator=FrozenEstimator(base_model),
        method=CALIBRATION_METHOD,
    )
    calibrator.fit(X_cal, y_cal)

    fit_info.update({
        "calibration_method": CALIBRATION_METHOD,
        "calibration_rows": int(len(X_cal)),
        "train_rows": int(len(X_train_raw)),
        "used_smote": used_smote,
    })
    return calibrator, base_model, fit_info


def tune_hyperparameters(
    X: pd.DataFrame,
    y: np.ndarray,
    dates: pd.Series,
    n_splits: int = 3,
    n_trials: int = OPTUNA_N_TRIALS,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Tune core XGBoost hyperparameters with Optuna over temporal folds."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    season_series = dates.apply(_season_year)

    def objective(trial: optuna.Trial) -> float:
        trial_params = _make_xgb_params({
            "max_depth": trial.suggest_int("max_depth", 3, 7),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.18, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        })

        fold_losses: list[float] = []
        draw_penalties: list[float] = []

        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]
            if len(np.unique(y_tr)) < 3 or len(np.unique(y_val)) < 3:
                continue

            model, _, _ = train_predictive_model(X_tr, y_tr, trial_params)
            metrics = evaluate_fold(model, X_val, y_val)
            fold_losses.append(metrics["brier_score"])
            draw_penalties.append(abs(metrics["draw_rate_gap"]))

        if not fold_losses:
            return float("inf")

        trial.set_user_attr("season_coverage", sorted(season_series.unique().tolist()))
        return float(np.mean(fold_losses) + 0.05 * np.mean(draw_penalties))

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    rows = [
        {
            "number": trial.number,
            "value": trial.value,
            **trial.params,
        }
        for trial in study.trials
        if trial.value is not None
    ]
    trials_df = pd.DataFrame(rows).sort_values("value").reset_index(drop=True)

    best_params = _make_xgb_params(study.best_trial.params if study.best_trial else {})
    return best_params, trials_df


# ── cross-validation ──────────────────────────────────────────────────────────

def temporal_cv(
    X: pd.DataFrame,
    y: np.ndarray,
    dates: pd.Series,
    params: dict[str, Any],
    n_splits: int = 3,
) -> list[dict[str, float]]:
    """Run time-aware CV with draw oversampling and calibration."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics: list[dict[str, float]] = []

    season_series = dates.apply(_season_year)
    if season_series.nunique() == 1:
        log.warning(
            "Only one season in the dataset — TimeSeriesSplit creates intra-season folds."
        )

    for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X), start=1):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        train_seasons = sorted(season_series.iloc[train_idx].unique())
        val_seasons = sorted(season_series.iloc[val_idx].unique())
        log.info(
            "Fold %d — train: %d matches [seasons %s] %s → %s | val: %d matches [seasons %s] %s → %s",
            fold_idx,
            len(train_idx),
            train_seasons,
            dates.iloc[train_idx].min().date(),
            dates.iloc[train_idx].max().date(),
            len(val_idx),
            val_seasons,
            dates.iloc[val_idx].min().date(),
            dates.iloc[val_idx].max().date(),
        )

        model, _, fit_info = train_predictive_model(X_tr, y_tr, params)
        metrics = evaluate_fold(model, X_val, y_val)
        metrics["fold"] = float(fold_idx)
        metrics["used_smote"] = float(1 if fit_info["used_smote"] else 0)
        metrics["calibrated"] = float(1 if fit_info["calibration_rows"] else 0)
        fold_metrics.append(metrics)

        log.info(
            "  accuracy=%.3f | brier=%.4f | logloss=%.4f | draw_recall=%.3f | draw_gap=%+.3f",
            metrics["accuracy"],
            metrics["brier_score"],
            metrics["log_loss"],
            metrics["draw_recall"],
            metrics["draw_rate_gap"],
        )

    return fold_metrics


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
    mlflow_uri: str = "http://localhost:5001",
    n_splits: int = 3,
    n_trials: int = OPTUNA_N_TRIALS,
) -> str:
    """Run tuning, calibrated CV, and final training. Return MLflow run ID."""
    log.info("Connecting to ClickHouse at %s:%d/%s", ch_host, ch_port, ch_db)
    client = clickhouse_connect.get_client(host=ch_host, port=ch_port, database=ch_db)

    log.info("Loading features from mart_match_features …")
    raw = load_features(client)
    log.info("  %d finished matches loaded", len(raw))

    X, y, dates = build_feature_matrix(raw)

    log.info("Running Optuna tuning (%d trials) …", n_trials)
    best_params, trials_df = tune_hyperparameters(X, y, dates, n_splits=n_splits, n_trials=n_trials)
    log.info(
        "Best tuned params: max_depth=%s learning_rate=%.4f min_child_weight=%s",
        best_params["max_depth"],
        best_params["learning_rate"],
        best_params["min_child_weight"],
    )

    log.info("Running TimeSeriesSplit(n_splits=%d) with calibrated pipeline …", n_splits)
    fold_metrics = temporal_cv(X, y, dates, best_params, n_splits=n_splits)

    accuracies = [m["accuracy"] for m in fold_metrics]
    briers = [m["brier_score"] for m in fold_metrics]
    log_losses = [m["log_loss"] for m in fold_metrics]
    draw_recalls = [m["draw_recall"] for m in fold_metrics]
    draw_gaps = [m["draw_rate_gap"] for m in fold_metrics]
    cv_acc_mean = float(np.mean(accuracies))
    cv_acc_std = float(np.std(accuracies))
    cv_brier_mean = float(np.mean(briers))
    cv_log_loss_mean = float(np.mean(log_losses))
    cv_draw_recall_mean = float(np.mean(draw_recalls))
    cv_draw_gap_mean = float(np.mean(draw_gaps))
    last_fold = fold_metrics[-1]

    log.info(
        "CV summary — accuracy %.3f ± %.3f | brier %.4f | logloss %.4f | draw_recall %.3f",
        cv_acc_mean,
        cv_acc_std,
        cv_brier_mean,
        cv_log_loss_mean,
        cv_draw_recall_mean,
    )

    log.info("Training final calibrated model on all %d matches …", len(X))
    final_model, _, final_fit_info = train_predictive_model(X, y, best_params)
    full_base_X, full_base_y, _ = _maybe_apply_smote(X, y)
    final_base_model = XGBClassifier(**_make_xgb_params(best_params))
    final_base_model.fit(full_base_X, full_base_y)

    importance_gain = dict(zip(FEATURES, final_base_model.feature_importances_))
    importance_sorted = {
        k: float(v)
        for k, v in sorted(importance_gain.items(), key=lambda kv: kv[1], reverse=True)
    }
    log.info("Feature importance (gain):")
    for feat_name, score in importance_sorted.items():
        log.info("  %-30s %.4f", feat_name, score)

    poisson_acc = _fetch_poisson_accuracy(mlflow_uri)
    improvement_vs_poisson = None
    if poisson_acc is not None:
        improvement_vs_poisson = last_fold["accuracy"] - poisson_acc
        log.info(
            "vs Poisson (OOS) → XGBoost last fold=%.3f | Poisson=%.3f | diff=%+.3f pp",
            last_fold["accuracy"],
            poisson_acc,
            improvement_vs_poisson,
        )

    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name="xgboost_classifier") as run:
        mlflow.log_params({
            "model_type": "XGBClassifier",
            "n_splits_cv": n_splits,
            "optuna_trials": n_trials,
            "features": ",".join(FEATURES),
            "n_features": len(FEATURES),
            "n_matches": len(X),
            "target_encoding": "0=A,1=D,2=H",
            "calibration_method": CALIBRATION_METHOD,
            "draw_oversampling": "SMOTE",
            **{f"xgb_{k}": v for k, v in best_params.items()},
        })

        for m in fold_metrics:
            fold = int(m["fold"])
            mlflow.log_metrics({
                f"fold_{fold}_accuracy": m["accuracy"],
                f"fold_{fold}_brier": m["brier_score"],
                f"fold_{fold}_log_loss": m["log_loss"],
                f"fold_{fold}_draw_recall": m["draw_recall"],
                f"fold_{fold}_draw_rate_gap": m["draw_rate_gap"],
            })

        summary: dict[str, float] = {
            "cv_accuracy_mean": cv_acc_mean,
            "cv_accuracy_std": cv_acc_std,
            "cv_brier_mean": cv_brier_mean,
            "cv_log_loss_mean": cv_log_loss_mean,
            "cv_draw_recall_mean": cv_draw_recall_mean,
            "cv_draw_rate_gap_mean": cv_draw_gap_mean,
            "accuracy_last_fold": last_fold["accuracy"],
            "brier_score_last_fold": last_fold["brier_score"],
            "log_loss_last_fold": last_fold["log_loss"],
            "draw_recall_last_fold": last_fold["draw_recall"],
            "draw_rate_gap_last_fold": last_fold["draw_rate_gap"],
            "baseline_home_win": last_fold["baseline_home_win"],
            "improvement_vs_baseline": last_fold["improvement_vs_baseline"],
        }
        if improvement_vs_poisson is not None:
            summary["poisson_accuracy_oos"] = poisson_acc  # type: ignore[assignment]
            summary["improvement_vs_poisson"] = improvement_vs_poisson
        mlflow.log_metrics(summary)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            (tmpdir_path / "feature_importance.json").write_text(
                json.dumps(importance_sorted, indent=2)
            )
            mlflow.log_artifact(str(tmpdir_path / "feature_importance.json"), artifact_path="model")

            (tmpdir_path / "best_params.json").write_text(json.dumps(best_params, indent=2))
            mlflow.log_artifact(str(tmpdir_path / "best_params.json"), artifact_path="model")

            if not trials_df.empty:
                trials_df.to_csv(tmpdir_path / "optuna_trials.csv", index=False)
                mlflow.log_artifact(str(tmpdir_path / "optuna_trials.csv"), artifact_path="model")

            final_base_model.save_model(str(tmpdir_path / "xgb_model.json"))
            mlflow.log_artifact(str(tmpdir_path / "xgb_model.json"), artifact_path="model")

            classifier_path = tmpdir_path / "classifier.joblib"
            joblib.dump(final_model, classifier_path)
            mlflow.log_artifact(str(classifier_path), artifact_path="model")

            calibration_meta = {
                "method": final_fit_info["calibration_method"],
                "calibration_rows": final_fit_info["calibration_rows"],
                "train_rows": final_fit_info["train_rows"],
                "used_smote": final_fit_info["used_smote"],
            }
            (tmpdir_path / "calibration.json").write_text(json.dumps(calibration_meta, indent=2))
            mlflow.log_artifact(str(tmpdir_path / "calibration.json"), artifact_path="model")

        run_id = run.info.run_id
        log.info("MLflow run %s logged", run_id)

    model_uri = f"runs:/{run_id}/model"
    mlclient = mlflow.tracking.MlflowClient(mlflow_uri)
    try:
        mlclient.create_registered_model(REGISTERED_MODEL)
        log.info("Created registered model '%s'", REGISTERED_MODEL)
    except mlflow.exceptions.MlflowException:
        pass

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
    p = argparse.ArgumentParser(description="Train the calibrated XGBoost classifier.")
    p.add_argument("--ch-host", default="localhost")
    p.add_argument("--ch-port", type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8124")))
    p.add_argument("--ch-db", default=os.getenv("CLICKHOUSE_DB", "football"))
    p.add_argument("--mlflow-uri", default="http://localhost:5001")
    p.add_argument("--n-splits", type=int, default=3)
    p.add_argument("--n-trials", type=int, default=OPTUNA_N_TRIALS)
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
        n_trials=args.n_trials,
    )
    log.info("Done. Run ID: %s", run_id)
