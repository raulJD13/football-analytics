"""Football Analytics — FastAPI application.

Endpoints
---------
POST /predict   → match outcome probabilities (Poisson model)

Future routers (Phase 5):
  GET /standings  → current + projected table
  GET /teams/{id} → team stats and form
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.fixtures import router as fixtures_router
from api.routers.model import router as model_router
from api.routers.predict import lifespan, router as predict_router
from api.routers.standings import router as standings_router
from api.routers.teams import router as teams_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

app = FastAPI(
    title="Football Analytics API",
    description="LaLiga match prediction and stats platform.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(predict_router)
app.include_router(model_router)
app.include_router(fixtures_router)
app.include_router(standings_router)
app.include_router(teams_router)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
