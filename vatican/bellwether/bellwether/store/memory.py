"""Lightweight prediction store for the learning loop.

Persists each prediction and, later, its realized outcome so the Learning Engine
can compute rolling directional accuracy and Brier-style calibration. JSON file
by default — swap for Postgres in a live build without touching the agents.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


class PredictionStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._data: dict[str, list[dict[str, Any]]] = {"predictions": []}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._data = {"predictions": []}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, default=str)
        except OSError:
            pass

    def record_prediction(self, asset: str, bias: str, probability_up: float,
                          confidence: float, ref: str | None = None) -> str:
        pid = f"{asset}-{datetime.now(timezone.utc).timestamp():.0f}"
        self._data["predictions"].append({
            "id": pid,
            "asset": asset,
            "bias": bias,
            "probability_up": probability_up,
            "confidence": confidence,
            "ref": ref,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "realized_return": None,
            "correct": None,
        })
        self._save()
        return pid

    def record_outcome(self, prediction_id: str, realized_return: float) -> bool:
        for p in self._data["predictions"]:
            if p["id"] == prediction_id:
                p["realized_return"] = realized_return
                # Directional hit: did probability_up>0.5 align with realized sign?
                predicted_up = p["probability_up"] >= 0.5
                actual_up = realized_return >= 0
                p["correct"] = (predicted_up == actual_up)
                self._save()
                return True
        return False

    def scored(self) -> list[dict[str, Any]]:
        return [p for p in self._data["predictions"] if p.get("correct") is not None]

    def rolling_accuracy(self, asset: str | None = None, window: int = 50) -> float:
        scored = self.scored()
        if asset:
            scored = [p for p in scored if p["asset"] == asset]
        scored = scored[-window:]
        if not scored:
            return 0.5
        return sum(1 for p in scored if p["correct"]) / len(scored)

    def brier(self, asset: str | None = None, window: int = 50) -> float:
        scored = self.scored()
        if asset:
            scored = [p for p in scored if p["asset"] == asset]
        scored = scored[-window:]
        if not scored:
            return 0.25
        return sum((p["probability_up"] - (1.0 if p["realized_return"] >= 0 else 0.0)) ** 2
                   for p in scored) / len(scored)
