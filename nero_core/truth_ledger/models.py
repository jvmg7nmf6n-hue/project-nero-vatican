from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "truth_ledger.db"

Direction = Literal["LONG", "SHORT", "NO_TRADE"]
TradeResult = Literal["WIN", "LOSS", "BREAKEVEN", "PENDING"]


class TruthLabel(str, Enum):
    TRUE_POSITIVE = "TRUE_POSITIVE"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    TRUE_NEGATIVE = "TRUE_NEGATIVE"
    FALSE_NEGATIVE = "FALSE_NEGATIVE"
    INCONCLUSIVE = "INCONCLUSIVE"


class DuplicatePredictionError(Exception):
    """Raised when a prediction with the same (asset, strategy_id, strategy_version, timestamp) already exists."""


class PredictionNotFoundError(Exception):
    """Raised when a prediction id does not exist in the ledger."""


class PredictionRecord(BaseModel):
    """One row of the Truth Ledger: a signal/prediction and, once known, its realized outcome.

    `direction` follows the ledger's own convention (LONG/SHORT/NO_TRADE), not schema.py's
    bullish/bearish/neutral narrative bias — this field records what the strategy actually
    did (or explicitly declined to do), which is what truth-labeling needs.
    """

    id: int | None = None
    timestamp: datetime
    asset: str
    strategy_id: str
    strategy_version: str
    direction: Direction
    confidence: float = Field(ge=0, le=1)
    entry_condition_values: dict[str, Any] = Field(default_factory=dict)
    reason: str
    result: TradeResult = "PENDING"
    exit_reason: str | None = None
    r_multiple: float | None = None
    fees_slippage_estimate: float | None = None
    truth_label: TruthLabel | None = None
    created_at: datetime | None = None


def compute_truth_label(direction: Direction, result: TradeResult) -> TruthLabel:
    """Score a prediction against its realized (or simulated) outcome.

    LONG/SHORT entries are trades the strategy actually took: a WIN confirms the call
    (TRUE_POSITIVE), a LOSS refutes it (FALSE_POSITIVE). NO_TRADE entries record a
    deliberate pass — `result` there holds the counterfactual outcome the trade would
    have had if taken: a would-be LOSS means the pass was correct (TRUE_NEGATIVE), a
    would-be WIN means a real opportunity was missed (FALSE_NEGATIVE). BREAKEVEN and
    PENDING outcomes are not evaluated as correct/incorrect calls, so they stay
    INCONCLUSIVE rather than being forced into a misleading label.
    """
    if result == "PENDING":
        return TruthLabel.INCONCLUSIVE

    took_trade = direction in ("LONG", "SHORT")
    if took_trade:
        if result == "WIN":
            return TruthLabel.TRUE_POSITIVE
        if result == "LOSS":
            return TruthLabel.FALSE_POSITIVE
        return TruthLabel.INCONCLUSIVE

    # direction == "NO_TRADE"
    if result == "LOSS":
        return TruthLabel.TRUE_NEGATIVE
    if result == "WIN":
        return TruthLabel.FALSE_NEGATIVE
    return TruthLabel.INCONCLUSIVE


_SCHEMA = """
CREATE TABLE IF NOT EXISTS truth_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    asset TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT', 'NO_TRADE')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    entry_condition_values TEXT NOT NULL,
    reason TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT 'PENDING' CHECK (result IN ('WIN', 'LOSS', 'BREAKEVEN', 'PENDING')),
    exit_reason TEXT,
    r_multiple REAL,
    fees_slippage_estimate REAL,
    truth_label TEXT CHECK (
        truth_label IS NULL OR truth_label IN (
            'TRUE_POSITIVE', 'FALSE_POSITIVE', 'TRUE_NEGATIVE', 'FALSE_NEGATIVE', 'INCONCLUSIVE'
        )
    ),
    created_at TEXT NOT NULL,
    UNIQUE (asset, strategy_id, strategy_version, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_truth_ledger_asset ON truth_ledger (asset);
CREATE INDEX IF NOT EXISTS idx_truth_ledger_strategy ON truth_ledger (strategy_id, strategy_version);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with closing(_connect(db_path)) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def _row_to_record(row: tuple[Any, ...]) -> PredictionRecord:
    (
        row_id,
        timestamp,
        asset,
        strategy_id,
        strategy_version,
        direction,
        confidence,
        entry_condition_values,
        reason,
        result,
        exit_reason,
        r_multiple,
        fees_slippage_estimate,
        truth_label,
        created_at,
    ) = row
    return PredictionRecord(
        id=row_id,
        timestamp=datetime.fromisoformat(timestamp),
        asset=asset,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        direction=direction,
        confidence=confidence,
        entry_condition_values=json.loads(entry_condition_values),
        reason=reason,
        result=result,
        exit_reason=exit_reason,
        r_multiple=r_multiple,
        fees_slippage_estimate=fees_slippage_estimate,
        truth_label=TruthLabel(truth_label) if truth_label else None,
        created_at=datetime.fromisoformat(created_at),
    )


def insert_prediction(record: PredictionRecord, db_path: Path = DEFAULT_DB_PATH) -> PredictionRecord:
    """Insert a new prediction. Raises DuplicatePredictionError if the same
    (asset, strategy_id, strategy_version, timestamp) combination already exists."""
    init_db(db_path)
    created_at = datetime.now(timezone.utc)
    truth_label = compute_truth_label(record.direction, record.result)
    with closing(_connect(db_path)) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO truth_ledger (
                    timestamp, asset, strategy_id, strategy_version, direction, confidence,
                    entry_condition_values, reason, result, exit_reason, r_multiple,
                    fees_slippage_estimate, truth_label, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp.isoformat(),
                    record.asset,
                    record.strategy_id,
                    record.strategy_version,
                    record.direction,
                    record.confidence,
                    json.dumps(record.entry_condition_values),
                    record.reason,
                    record.result,
                    record.exit_reason,
                    record.r_multiple,
                    record.fees_slippage_estimate,
                    truth_label.value,
                    created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicatePredictionError(
                f"A prediction already exists for asset={record.asset!r}, "
                f"strategy_id={record.strategy_id!r}, strategy_version={record.strategy_version!r}, "
                f"timestamp={record.timestamp.isoformat()!r}."
            ) from exc
        conn.commit()
        new_id = cursor.lastrowid

    return get_prediction(new_id, db_path)  # type: ignore[return-value]


def get_prediction(prediction_id: int, db_path: Path = DEFAULT_DB_PATH) -> PredictionRecord | None:
    init_db(db_path)
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT id, timestamp, asset, strategy_id, strategy_version, direction, confidence,
                   entry_condition_values, reason, result, exit_reason, r_multiple,
                   fees_slippage_estimate, truth_label, created_at
            FROM truth_ledger WHERE id = ?
            """,
            (prediction_id,),
        ).fetchone()
    return _row_to_record(row) if row else None


def list_predictions(
    db_path: Path = DEFAULT_DB_PATH,
    asset: str | None = None,
    strategy_id: str | None = None,
    strategy_version: str | None = None,
) -> list[PredictionRecord]:
    init_db(db_path)
    query = """
        SELECT id, timestamp, asset, strategy_id, strategy_version, direction, confidence,
               entry_condition_values, reason, result, exit_reason, r_multiple,
               fees_slippage_estimate, truth_label, created_at
        FROM truth_ledger
    """
    conditions: list[str] = []
    params: list[Any] = []
    if asset is not None:
        conditions.append("asset = ?")
        params.append(asset)
    if strategy_id is not None:
        conditions.append("strategy_id = ?")
        params.append(strategy_id)
    if strategy_version is not None:
        conditions.append("strategy_version = ?")
        params.append(strategy_version)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY timestamp ASC"

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_record(row) for row in rows]


def update_prediction_result(
    prediction_id: int,
    result: TradeResult,
    exit_reason: str | None = None,
    r_multiple: float | None = None,
    fees_slippage_estimate: float | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> PredictionRecord:
    """Record a prediction's realized outcome and recompute its truth label.
    Raises PredictionNotFoundError if the id does not exist."""
    existing = get_prediction(prediction_id, db_path)
    if existing is None:
        raise PredictionNotFoundError(f"No prediction with id={prediction_id}.")

    truth_label = compute_truth_label(existing.direction, result)
    with closing(_connect(db_path)) as conn:
        conn.execute(
            """
            UPDATE truth_ledger
            SET result = ?, exit_reason = ?, r_multiple = ?, fees_slippage_estimate = ?, truth_label = ?
            WHERE id = ?
            """,
            (result, exit_reason, r_multiple, fees_slippage_estimate, truth_label.value, prediction_id),
        )
        conn.commit()

    return get_prediction(prediction_id, db_path)  # type: ignore[return-value]


def delete_prediction(prediction_id: int, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Delete a prediction row. Returns True if a row was deleted, False if it did not exist."""
    init_db(db_path)
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute("DELETE FROM truth_ledger WHERE id = ?", (prediction_id,))
        conn.commit()
    return cursor.rowcount > 0
