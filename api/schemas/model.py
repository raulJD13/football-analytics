"""Schemas for model metrics and feature importance endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class FeatureImportanceEntry(BaseModel):
    name: str
    importance: float


class ModelMetricsResponse(BaseModel):
    model_name: str
    model_version: str
    accuracy: float
    brier_score: float
    log_loss: float | None
    baseline_accuracy: float
    feature_importance: list[FeatureImportanceEntry]
