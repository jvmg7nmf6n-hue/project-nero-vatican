"""FastAPI surface for the engine.

Endpoints
  GET  /health           liveness + mode flags
  POST /analyze          run a full multi-agent cycle over optional events
  GET  /analysis/latest  last computed output (in-memory)
  POST /feedback         record a realized outcome to train the learning loop
  GET  /stats            learning-loop accuracy / calibration
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..orchestrator import Orchestrator
from ..schemas import AnalysisOutput, Category, MacroEvent, Region


class EventIn(BaseModel):
    headline: str
    summary: str = ""
    source: str = "api"
    region: Region = Region.GLOBAL
    category: Category = Category.OTHER
    url: str | None = None


class AnalyzeRequest(BaseModel):
    events: list[EventIn] = []


class FeedbackRequest(BaseModel):
    prediction_id: str
    realized_return: float


def create_app() -> FastAPI:
    settings = get_settings()
    orch = Orchestrator(settings)
    app = FastAPI(title="Bellwether Engine", version="0.1.0")
    state: dict[str, Any] = {"latest": None}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "data_mode": settings.data_mode,
            "llm_available": settings.llm_available,
            "model": settings.llm_model,
        }

    @app.post("/analyze", response_model=AnalysisOutput)
    async def analyze(req: AnalyzeRequest) -> AnalysisOutput:
        events = [MacroEvent(**e.model_dump()) for e in req.events]
        output = await orch.analyze(events)
        state["latest"] = output
        return output

    @app.get("/analysis/latest", response_model=AnalysisOutput)
    async def latest() -> AnalysisOutput:
        if state["latest"] is None:
            raise HTTPException(404, "No analysis computed yet. POST /analyze first.")
        return state["latest"]

    @app.post("/feedback")
    async def feedback(req: FeedbackRequest) -> dict[str, Any]:
        ok = orch.record_outcome(req.prediction_id, req.realized_return)
        if not ok:
            raise HTTPException(404, f"Unknown prediction_id {req.prediction_id}")
        return {"recorded": True, "prediction_id": req.prediction_id}

    @app.get("/stats")
    async def stats() -> dict[str, Any]:
        s = orch.store
        return {
            "scored_count": len(s.scored()),
            "rolling_accuracy": s.rolling_accuracy(),
            "gold_accuracy": s.rolling_accuracy("GOLD"),
            "bitcoin_accuracy": s.rolling_accuracy("BITCOIN"),
            "brier": s.brier(),
        }

    return app


app = create_app()
