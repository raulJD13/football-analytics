"""Router: GET /model/metrics."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from api.db.model import fetch_model_metrics
from api.schemas.model import ModelMetricsResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/metrics", response_model=ModelMetricsResponse, summary="Get production model metrics")
def model_metrics() -> ModelMetricsResponse:
    try:
        return ModelMetricsResponse(**fetch_model_metrics())
    except Exception as exc:
        log.exception("Failed to fetch model metrics")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model metrics unavailable: {exc}",
        ) from exc
