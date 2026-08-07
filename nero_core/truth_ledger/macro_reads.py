"""Bellwether macro-read ledger + conflict-annotation tables (CC-1 Part C).

TWO structurally separate, append-only tables, sharing the same SQLite file as
execution_log/PredictionRecord (same convention execution_log.py itself already
established: multiple structurally-separate tables can share one file without being
"the same table"):

`macro_reads` — one row per (run_id, asset) every time the overlay job runs Bellwether.
Never written to by anything price-action-related; only nero_core.execution.
bellwether_overlay writes here. This is NOT Bellwether's own PredictionStore
(bellwether/store/memory.py, used for ITS OWN learning-loop accuracy tracking) -- this
is Vatican's own record of what Bellwether said and when, kept for the conflict
annotation's audit trail and (later) Part E's website history view.

`macro_conflict_flags` — one row per ORDERFLOW_IMBALANCE/BTC ENTRY row EVER EVALUATED
(not just the ones that conflicted) -- `status`/`conflicted` together give a full,
honest audit trail: was this entry evaluated at all, and if so, what did the
macro read say. UNIQUE(execution_log_id): an entry is evaluated exactly once, ever
(idempotent job re-runs never re-flag or re-decide the same entry).

IMMUTABLE BY DESIGN, same as execution_log.py: no update/delete functions for either
table. A wrong evaluation would need a new row (there is no correction mechanism here
yet, matching execution_log's own "corrections happen by inserting a new row" -- not
needed in practice since evaluation is deterministic given its own read, but the
append-only shape is kept consistent regardless).

NO LOOKAHEAD: get_latest_macro_read_before always looks strictly at reads with
timestamp <= the entry's own timestamp -- an entry is never evaluated against a macro
read that didn't exist yet at the moment it fired.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from nero_core.truth_ledger.models import DEFAULT_DB_PATH

FlagStatus = Literal["evaluated", "insufficient_data", "circuit_breaker_open"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS macro_reads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    asset TEXT NOT NULL CHECK (asset IN ('GOLD', 'BITCOIN')),
    bias TEXT NOT NULL,
    confidence REAL NOT NULL,
    agreement REAL NOT NULL,
    coverage REAL NOT NULL,
    probability_up REAL NOT NULL,
    provenance_breakdown TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    risks TEXT NOT NULL,
    alternative_scenarios TEXT NOT NULL,
    data_mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, asset)
);
CREATE INDEX IF NOT EXISTS idx_macro_reads_asset_ts ON macro_reads (asset, timestamp);

CREATE TABLE IF NOT EXISTS macro_conflict_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_log_id INTEGER NOT NULL UNIQUE,
    macro_read_id INTEGER,
    strategy TEXT NOT NULL,
    asset TEXT NOT NULL,
    entry_direction TEXT,
    conflicted INTEGER NOT NULL CHECK (conflicted IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('evaluated', 'insufficient_data', 'circuit_breaker_open')),
    reason TEXT NOT NULL,
    evaluated_at TEXT NOT NULL
);
"""


def init_macro_tables(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


@dataclass(frozen=True)
class MacroReadRow:
    id: int | None
    run_id: str
    timestamp: datetime
    asset: str
    bias: str
    confidence: float
    agreement: float
    coverage: float
    probability_up: float
    provenance_breakdown: dict[str, str]
    reasoning: str
    risks: list[str]
    alternative_scenarios: list[dict[str, Any]]
    data_mode: str
    created_at: datetime


def insert_macro_read(
    run_id: str,
    asset: str,
    bias: str,
    confidence: float,
    agreement: float,
    coverage: float,
    probability_up: float,
    provenance_breakdown: dict[str, str],
    reasoning: str,
    risks: list[str],
    alternative_scenarios: list[dict[str, Any]],
    data_mode: str,
    timestamp: datetime | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> MacroReadRow | None:
    """Returns None (not an error) if this exact (run_id, asset) pair was already
    inserted -- caller should treat that as already-recorded."""
    init_macro_tables(db_path)
    ts = timestamp or datetime.now(timezone.utc)
    created_at = datetime.now(timezone.utc)
    with closing(sqlite3.connect(str(db_path))) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO macro_reads (
                    run_id, timestamp, asset, bias, confidence, agreement, coverage,
                    probability_up, provenance_breakdown, reasoning, risks,
                    alternative_scenarios, data_mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, ts.isoformat(), asset, bias, confidence, agreement, coverage,
                    probability_up, json.dumps(provenance_breakdown), reasoning,
                    json.dumps(risks), json.dumps(alternative_scenarios), data_mode,
                    created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError:
            return None
        conn.commit()
        row_id = cursor.lastrowid
    return MacroReadRow(
        id=row_id, run_id=run_id, timestamp=ts, asset=asset, bias=bias, confidence=confidence,
        agreement=agreement, coverage=coverage, probability_up=probability_up,
        provenance_breakdown=provenance_breakdown, reasoning=reasoning, risks=risks,
        alternative_scenarios=alternative_scenarios, data_mode=data_mode, created_at=created_at,
    )


def _row_to_macro_read(r: tuple) -> MacroReadRow:
    return MacroReadRow(
        id=r[0], run_id=r[1], timestamp=datetime.fromisoformat(r[2]), asset=r[3], bias=r[4],
        confidence=r[5], agreement=r[6], coverage=r[7], probability_up=r[8],
        provenance_breakdown=json.loads(r[9]), reasoning=r[10], risks=json.loads(r[11]),
        alternative_scenarios=json.loads(r[12]), data_mode=r[13], created_at=datetime.fromisoformat(r[14]),
    )


_MACRO_READ_COLUMNS = """
    id, run_id, timestamp, asset, bias, confidence, agreement, coverage,
    probability_up, provenance_breakdown, reasoning, risks, alternative_scenarios,
    data_mode, created_at
"""


def get_latest_macro_read_before(
    asset: str, before: datetime, db_path: Path = DEFAULT_DB_PATH
) -> MacroReadRow | None:
    """The most recent macro_reads row for `asset` with timestamp <= `before` --
    NEVER a read computed after `before`. Use this to evaluate an execution_log
    ENTRY against "what Bellwether had already said" at that entry's own timestamp,
    not a read from later in time (no lookahead)."""
    init_macro_tables(db_path)
    with closing(sqlite3.connect(str(db_path))) as conn:
        row = conn.execute(
            f"SELECT {_MACRO_READ_COLUMNS} FROM macro_reads "
            "WHERE asset = ? AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1",
            (asset, before.isoformat()),
        ).fetchone()
    return _row_to_macro_read(row) if row else None


def list_macro_reads(asset: str | None = None, db_path: Path = DEFAULT_DB_PATH) -> list[MacroReadRow]:
    init_macro_tables(db_path)
    query = f"SELECT {_MACRO_READ_COLUMNS} FROM macro_reads"
    params: list[Any] = []
    if asset is not None:
        query += " WHERE asset = ?"
        params.append(asset)
    query += " ORDER BY timestamp ASC, id ASC"
    with closing(sqlite3.connect(str(db_path))) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_macro_read(r) for r in rows]


@dataclass(frozen=True)
class MacroConflictFlagRow:
    id: int | None
    execution_log_id: int
    macro_read_id: int | None
    strategy: str
    asset: str
    entry_direction: str | None
    conflicted: bool
    status: FlagStatus
    reason: str
    evaluated_at: datetime


def insert_macro_conflict_flag(
    execution_log_id: int,
    strategy: str,
    asset: str,
    conflicted: bool,
    status: FlagStatus,
    reason: str,
    macro_read_id: int | None = None,
    entry_direction: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> MacroConflictFlagRow | None:
    """Returns None (not an error) if this execution_log_id was already evaluated --
    caller should treat that as already-processed, never re-decide it."""
    init_macro_tables(db_path)
    evaluated_at = datetime.now(timezone.utc)
    with closing(sqlite3.connect(str(db_path))) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO macro_conflict_flags (
                    execution_log_id, macro_read_id, strategy, asset, entry_direction,
                    conflicted, status, reason, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_log_id, macro_read_id, strategy, asset, entry_direction,
                    1 if conflicted else 0, status, reason, evaluated_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError:
            return None
        conn.commit()
        row_id = cursor.lastrowid
    return MacroConflictFlagRow(
        id=row_id, execution_log_id=execution_log_id, macro_read_id=macro_read_id,
        strategy=strategy, asset=asset, entry_direction=entry_direction, conflicted=conflicted,
        status=status, reason=reason, evaluated_at=evaluated_at,
    )


def has_flag_for_entry(execution_log_id: int, db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_macro_tables(db_path)
    with closing(sqlite3.connect(str(db_path))) as conn:
        row = conn.execute(
            "SELECT 1 FROM macro_conflict_flags WHERE execution_log_id = ?", (execution_log_id,)
        ).fetchone()
    return row is not None


def list_macro_conflict_flags(
    asset: str | None = None, conflicted_only: bool = False, db_path: Path = DEFAULT_DB_PATH
) -> list[MacroConflictFlagRow]:
    init_macro_tables(db_path)
    query = (
        "SELECT id, execution_log_id, macro_read_id, strategy, asset, entry_direction, "
        "conflicted, status, reason, evaluated_at FROM macro_conflict_flags"
    )
    conditions: list[str] = []
    params: list[Any] = []
    if asset is not None:
        conditions.append("asset = ?")
        params.append(asset)
    if conflicted_only:
        conditions.append("conflicted = 1")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY evaluated_at ASC, id ASC"
    with closing(sqlite3.connect(str(db_path))) as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        MacroConflictFlagRow(
            id=r[0], execution_log_id=r[1], macro_read_id=r[2], strategy=r[3], asset=r[4],
            entry_direction=r[5], conflicted=bool(r[6]), status=r[7], reason=r[8],
            evaluated_at=datetime.fromisoformat(r[9]),
        )
        for r in rows
    ]
