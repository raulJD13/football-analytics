"""Benchmark tabular classifiers on the football outcome dataset.

Compares the current calibrated XGBoost pipeline against CatBoost and TabPFN
using the same engineered features and the same temporal CV protocol.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import clickhouse_connect
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.model_selection import TimeSeriesSplit
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from xgboost import XGBClassifier

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.scripts.train_classifier import (
    CALIBRATION_METHOD,
    FEATURES,
    build_feature_matrix,
    evaluate_fold,
    load_features,
    tune_hyperparameters,
    _make_xgb_params,
    _maybe_apply_smote,
    _season_year,
    _split_for_calibration,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    model_name: str
    fold_metrics: list[dict[str, float]]
    notes: str


def _train_xgboost(
    X: pd.DataFrame,
    y: np.ndarray,
    params: dict[str, Any],
) -> Any:
    split = _split_for_calibration(X, y)
    if split is None:
        X_fit, y_fit, _ = _maybe_apply_smote(X, y)
        model = XGBClassifier(**_make_xgb_params(params))
        model.fit(X_fit, y_fit)
        return model

    X_train_raw, y_train_raw, X_cal, y_cal = split
    X_train_fit, y_train_fit, _ = _maybe_apply_smote(X_train_raw, y_train_raw)
    model = XGBClassifier(**_make_xgb_params(params))
    model.fit(X_train_fit, y_train_fit)
    calibrator = CalibratedClassifierCV(
        estimator=FrozenEstimator(model),
        method=CALIBRATION_METHOD,
    )
    calibrator.fit(X_cal, y_cal)
    return calibrator


def _train_catboost(
    X: pd.DataFrame,
    y: np.ndarray,
    params: dict[str, Any],
    calibrate: bool = True,
) -> Any:
    split = _split_for_calibration(X, y) if calibrate else None
    if split is None:
        X_fit, y_fit, _ = _maybe_apply_smote(X, y)
        model = CatBoostClassifier(**params)
        model.fit(X_fit, y_fit, verbose=False)
        return model

    X_train_raw, y_train_raw, X_cal, y_cal = split
    X_train_fit, y_train_fit, _ = _maybe_apply_smote(X_train_raw, y_train_raw)
    model = CatBoostClassifier(**params)
    model.fit(X_train_fit, y_train_fit, verbose=False)
    calibrator = CalibratedClassifierCV(
        estimator=FrozenEstimator(model),
        method=CALIBRATION_METHOD,
    )
    calibrator.fit(X_cal, y_cal)
    return calibrator


class FTTransformerClassifier(nn.Module):
    def __init__(
        self,
        n_features: int,
        n_classes: int,
        d_token: int = 32,
        n_heads: int = 4,
        n_layers: int = 2,
        ff_mult: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.feature_weight = nn.Parameter(torch.randn(n_features, d_token) * 0.02)
        self.feature_bias = nn.Parameter(torch.zeros(n_features, d_token))
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_token))
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_token,
            nhead=n_heads,
            dim_feedforward=d_token * ff_mult,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(d_token)
        self.head = nn.Linear(d_token, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        tokens = x.unsqueeze(-1) * self.feature_weight.unsqueeze(0) + self.feature_bias.unsqueeze(0)
        cls = self.cls_token.expand(x.size(0), -1, -1)
        hidden = torch.cat([cls, tokens], dim=1)
        encoded = self.encoder(hidden)
        return self.head(self.norm(encoded[:, 0]))


class FTTransformerWrapper:
    def __init__(
        self,
        n_features: int,
        n_classes: int,
        epochs: int = 25,
        batch_size: int = 128,
        learning_rate: float = 1e-3,
        patience: int = 4,
    ) -> None:
        self.device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        self.model = FTTransformerClassifier(n_features=n_features, n_classes=n_classes).to(self.device)
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.patience = patience

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "FTTransformerWrapper":
        X_np = X.to_numpy(dtype=np.float32)
        y_np = y.astype(np.int64)
        split_at = max(int(len(X_np) * 0.85), len(np.unique(y_np)) * 10)
        split_at = min(split_at, len(X_np) - max(48, len(np.unique(y_np)) * 6))
        if split_at <= 0:
            split_at = len(X_np)

        X_train = X_np[:split_at]
        y_train = y_np[:split_at]
        X_val = X_np[split_at:] if split_at < len(X_np) else X_np[-64:]
        y_val = y_np[split_at:] if split_at < len(y_np) else y_np[-64:]

        train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
        val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))
        train_loader = DataLoader(train_ds, batch_size=min(self.batch_size, len(train_ds)), shuffle=False)
        val_loader = DataLoader(val_ds, batch_size=min(self.batch_size, len(val_ds)), shuffle=False)

        optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.learning_rate, weight_decay=1e-4)
        criterion = nn.CrossEntropyLoss()
        best_state: dict[str, torch.Tensor] | None = None
        best_loss = float("inf")
        epochs_without_improvement = 0

        for _epoch in range(self.epochs):
            self.model.train()
            for xb, yb in train_loader:
                xb = xb.to(self.device)
                yb = yb.to(self.device)
                optimizer.zero_grad()
                loss = criterion(self.model(xb), yb)
                loss.backward()
                optimizer.step()

            self.model.eval()
            losses: list[float] = []
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb = xb.to(self.device)
                    yb = yb.to(self.device)
                    losses.append(float(criterion(self.model(xb), yb).item()))
            val_loss = float(np.mean(losses))
            if val_loss + 1e-4 < best_loss:
                best_loss = val_loss
                best_state = {k: v.detach().cpu().clone() for k, v in self.model.state_dict().items()}
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1
                if epochs_without_improvement >= self.patience:
                    break

        if best_state is not None:
            self.model.load_state_dict(best_state)
        self.model.eval()
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_tensor = torch.from_numpy(X.to_numpy(dtype=np.float32)).to(self.device)
        with torch.no_grad():
            logits = self.model(X_tensor)
            probs = torch.softmax(logits, dim=1)
        return probs.cpu().numpy()


def _train_ft_transformer(
    X: pd.DataFrame,
    y: np.ndarray,
    epochs: int = 25,
) -> FTTransformerWrapper:
    model = FTTransformerWrapper(n_features=X.shape[1], n_classes=len(np.unique(y)), epochs=epochs)
    model.fit(X, y)
    return model


def _temporal_cv(
    X: pd.DataFrame,
    y: np.ndarray,
    dates: pd.Series,
    trainer: Any,
    trainer_name: str,
    trainer_params: dict[str, Any] | None = None,
    n_splits: int = 3,
) -> list[dict[str, float]]:
    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics: list[dict[str, float]] = []
    season_series = dates.apply(_season_year)

    for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X), start=1):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]
        train_seasons = sorted(season_series.iloc[train_idx].unique())
        val_seasons = sorted(season_series.iloc[val_idx].unique())
        log.info(
            "%s fold %d — train %d [seasons %s] | val %d [seasons %s]",
            trainer_name,
            fold_idx,
            len(train_idx),
            train_seasons,
            len(val_idx),
            val_seasons,
        )

        params = trainer_params or {}
        model = trainer(X_tr, y_tr, **params)

        metrics = evaluate_fold(model, X_val, y_val)

        metrics["fold"] = float(fold_idx)
        fold_metrics.append(metrics)
        log.info(
            "%s fold %d — accuracy=%.3f | brier=%.4f | logloss=%.4f | draw_recall=%.3f",
            trainer_name,
            fold_idx,
            metrics["accuracy"],
            metrics["brier_score"],
            metrics["log_loss"],
            metrics["draw_recall"],
        )

    return fold_metrics


def _summarise(model_name: str, fold_metrics: list[dict[str, float]], notes: str) -> BenchmarkResult:
    return BenchmarkResult(model_name=model_name, fold_metrics=fold_metrics, notes=notes)


def _result_rows(results: list[BenchmarkResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        accuracies = [m["accuracy"] for m in result.fold_metrics]
        briers = [m["brier_score"] for m in result.fold_metrics]
        log_losses = [m["log_loss"] for m in result.fold_metrics]
        draw_recalls = [m["draw_recall"] for m in result.fold_metrics]
        draw_gaps = [m["draw_rate_gap"] for m in result.fold_metrics]
        last_fold = result.fold_metrics[-1]
        rows.append({
            "model": result.model_name,
            "cv_accuracy_mean": float(np.mean(accuracies)),
            "cv_accuracy_std": float(np.std(accuracies)),
            "cv_brier_mean": float(np.mean(briers)),
            "cv_log_loss_mean": float(np.mean(log_losses)),
            "cv_draw_recall_mean": float(np.mean(draw_recalls)),
            "cv_draw_gap_mean": float(np.mean(draw_gaps)),
            "accuracy_last_fold": last_fold["accuracy"],
            "brier_last_fold": last_fold["brier_score"],
            "log_loss_last_fold": last_fold["log_loss"],
            "draw_recall_last_fold": last_fold["draw_recall"],
            "draw_gap_last_fold": last_fold["draw_rate_gap"],
            "baseline_last_fold": last_fold["baseline_home_win"],
            "notes": result.notes,
        })
    return pd.DataFrame(rows).sort_values(
        ["accuracy_last_fold", "cv_brier_mean"],
        ascending=[False, True],
    ).reset_index(drop=True)


def run_benchmark(
    ch_host: str,
    ch_port: int,
    ch_db: str,
    n_splits: int,
    n_trials_xgb: int,
) -> pd.DataFrame:
    client = clickhouse_connect.get_client(host=ch_host, port=ch_port, database=ch_db)
    raw = load_features(client)
    X, y, dates = build_feature_matrix(raw)
    log.info("Loaded %d matches with %d features", len(X), len(FEATURES))

    xgb_params, _ = tune_hyperparameters(X, y, dates, n_splits=n_splits, n_trials=n_trials_xgb)
    xgb_metrics = _temporal_cv(
        X,
        y,
        dates,
        trainer=_train_xgboost,
        trainer_name="XGBoost",
        trainer_params={"params": xgb_params},
        n_splits=n_splits,
    )

    cat_params = {
        "loss_function": "MultiClass",
        "eval_metric": "MultiClass",
        "iterations": 500,
        "depth": 6,
        "learning_rate": 0.05,
        "l2_leaf_reg": 5.0,
        "random_seed": 42,
        "allow_writing_files": False,
        "thread_count": -1,
    }
    cat_metrics = _temporal_cv(
        X,
        y,
        dates,
        trainer=_train_catboost,
        trainer_name="CatBoost",
        trainer_params={"params": cat_params, "calibrate": True},
        n_splits=n_splits,
    )

    ft_transformer_metrics = _temporal_cv(
        X,
        y,
        dates,
        trainer=_train_ft_transformer,
        trainer_name="FT-Transformer",
        trainer_params={"epochs": 25},
        n_splits=n_splits,
    )

    return _result_rows([
        _summarise("XGBoost", xgb_metrics, "Optuna + SMOTE + Platt scaling"),
        _summarise("CatBoost", cat_metrics, "500 trees + SMOTE + Platt scaling"),
        _summarise("FT-Transformer", ft_transformer_metrics, "Lightweight PyTorch FT-Transformer on continuous features"),
    ])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark XGBoost, CatBoost, and FT-Transformer.")
    parser.add_argument("--ch-host", default="localhost")
    parser.add_argument("--ch-port", type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8124")))
    parser.add_argument("--ch-db", default=os.getenv("CLICKHOUSE_DB", "football"))
    parser.add_argument("--n-splits", type=int, default=3)
    parser.add_argument("--n-trials-xgb", type=int, default=10)
    parser.add_argument("--output-json", default="")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    args = _parse_args()
    results = run_benchmark(
        ch_host=args.ch_host,
        ch_port=args.ch_port,
        ch_db=args.ch_db,
        n_splits=args.n_splits,
        n_trials_xgb=args.n_trials_xgb,
    )
    print(results.to_string(index=False))
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results.to_dict(orient="records"), f, indent=2)
