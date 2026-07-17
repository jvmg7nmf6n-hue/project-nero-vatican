"""Append-only execution log + run metadata + news sentiment log tables, sharing the
same SQLite file as the prediction Truth Ledger (nero_core.truth_ledger.models).

IMMUTABLE BY DESIGN: this module deliberately provides no update/delete functions for
any of its three tables. A live-execution audit trail is only trustworthy if a run can
never rewrite its own (or a prior run's) history — corrections happen by inserting a new
row, never by mutating an old one.

`candle_timestamp` is stored as an INTEGER epoch-millisecond value (matching `close_time`
everywhere else in this codebase — e.g. `OpenTrade.open_close_time`, `ExitEvent.
exit_close_time`), not as an ISO8601 string. This keeps replay's "is this candle newer
than the last one we logged" comparison an exact integer comparison, with no
datetime-roundtrip precision question. Wall-clock fields (`timestamp`, `created_at`,
`fetch_timestamp`, `news_timestamp`) are ISO8601 TEXT, matching
nero_core.truth_ledger.models.PredictionRecord's existing convention.
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

SignalType = Literal["ENTRY", "EXIT", "WATCH", "NO_TRADE"]
NewsSignalType = Literal["BUY_BIAS", "SELL_BIAS", "NEUTRAL"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    strategy TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    asset TEXT NOT NULL,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('ENTRY', 'EXIT', 'WATCH', 'NO_TRADE')),
    entry_price REAL,
    exit_price REAL,
    reasoning TEXT NOT NULL,
    candle_timestamp INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (asset, strategy, strategy_version, candle_timestamp, signal_type)
);
CREATE INDEX IF NOT EXISTS idx_execution_log_lookup ON execution_log (asset, strategy, strategy_version);
CREATE INDEX IF NOT EXISTS idx_execution_log_run ON execution_log (run_id);

CREATE TABLE IF NOT EXISTS execution_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    assets_evaluated TEXT NOT NULL,
    assets_skipped TEXT NOT NULL,
    errors_encountered TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_sentiment_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    news_timestamp TEXT,
    fetch_timestamp TEXT NOT NULL,
    sentiment_score INTEGER,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('BUY_BIAS', 'SELL_BIAS', 'NEUTRAL')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasoning TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (asset, fetch_timestamp)
);
"""


def init_execution_tables(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


@dataclass(frozen=True)
class ExecutionLogRow:
    id: int | None
    run_id: str
    timestamp: datetime
    strategy: str
    strategy_version: str
    asset: str
    signal_type: str
    entry_price: float | None
    exit_price: float | None
    reasoning: str
    candle_timestamp: int
    created_at: datetime


def insert_execution_log_row(
    run_id: str,
    strategy: str,
    strategy_version: str,
    asset: str,
    signal_type: SignalType,
    reasoning: str,
    candle_timestamp: int,
    entry_price: float | None = None,
    exit_price: float | None = None,
    timestamp: datetime | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> ExecutionLogRow | None:
    """Insert one execution_log row. Returns None (not an error) if this exact signal
    for this exact candle was already logged by a previous run — the caller should treat
    that as "already processed," never retry or overwrite it."""
    init_execution_tables(db_path)
    ts = timestamp or datetime.now(timezone.utc)
    created_at = datetime.now(timezone.utc)
    with closing(sqlite3.connect(str(db_path))) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO execution_log (
                    run_id, timestamp, strategy, strategy_version, asset, signal_type,
                    entry_price, exit_price, reasoning, candle_timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, ts.isoformat(), strategy, strategy_version, asset, signal_type,
                    entry_price, exit_price, reasoning, candle_timestamp, created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError:
            return None
        conn.commit()
        row_id = cursor.lastrowid
    return ExecutionLogRow(
        id=row_id, run_id=run_id, timestamp=ts, strategy=strategy, strategy_version=strategy_version,
        asset=asset, signal_type=signal_type, entry_price=entry_price, exit_price=exit_price,
        reasoning=reasoning, candle_timestamp=candle_timestamp, created_at=created_at,
    )


def latest_logged_candle_timestamp(
    strategy: str, strategy_version: str, asset: str, db_path: Path = DEFAULT_DB_PATH
) -> int | None:
    """The most recent candle_timestamp already logged for this (asset, strategy,
    strategy_version) — the authoritative "already processed up to here" cursor the
    scheduler replays forward from. None if nothing has ever been logged."""
    init_execution_tables(db_path)
    with closing(sqlite3.connect(str(db_path))) as conn:
        row = conn.execute(
            "SELECT MAX(candle_timestamp) FROM execution_log WHERE asset = ? AND strategy = ? AND strategy_version = ?",
            (asset, strategy, strategy_version),
        ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def earliest_logged_candle_timestamp(
    strategy: str, strategy_version: str, asset: str, db_path: Path = DEFAULT_DB_PATH
) -> int | None:
    """The account's inception candle — the first candle_timestamp ever logged for this
    (asset, strategy, strategy_version). None if nothing has ever been logged (a fresh
    account, which live_scheduler starts from "now," never backfilled)."""
    init_execution_tables(db_path)
    with closing(sqlite3.connect(str(db_path))) as conn:
        row = conn.execute(
            "SELECT MIN(candle_timestamp) FROM execution_log WHERE asset = ? AND strategy = ? AND strategy_version = ?",
            (asset, strategy, strategy_version),
        ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def list_execution_log(
    db_path: Path = DEFAULT_DB_PATH, asset: str | None = None, strategy: str | None = None
) -> list[ExecutionLogRow]:
    init_execution_tables(db_path)
    query = """
        SELECT id, run_id, timestamp, strategy, strategy_version, asset, signal_type,
               entry_price, exit_price, reasoning, candle_timestamp, created_at
        FROM execution_log
    """
    conditions: list[str] = []
    params: list[Any] = []
    if asset is not None:
        conditions.append("asset = ?")
        params.append(asset)
    if strategy is not None:
        conditions.append("strategy = ?")
        params.append(strategy)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY candle_timestamp ASC, id ASC"
    with closing(sqlite3.connect(str(db_path))) as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        ExecutionLogRow(
            id=r[0], run_id=r[1], timestamp=datetime.fromisoformat(r[2]), strategy=r[3], strategy_version=r[4],
            asset=r[5], signal_type=r[6], entry_price=r[7], exit_price=r[8], reasoning=r[9],
            candle_timestamp=r[10], created_at=datetime.fromisoformat(r[11]),
        )
        for r in rows
    ]


@dataclass(frozen=True)
class ExecutionMetadataRow:
    run_id: str
    start_time: datetime
    end_time: datetime
    assets_evaluated: list[str]
    assets_skipped: list[dict[str, Any]]
    errors_encountered: list[dict[str, Any]]


def insert_execution_metadata(
    run_id: str,
    start_time: datetime,
    end_time: datetime,
    assets_evaluated: list[str],
    assets_skipped: list[dict[str, Any]],
    errors_encountered: list[dict[str, Any]],
    db_path: Path = DEFAULT_DB_PATH,
) -> ExecutionMetadataRow:
    init_execution_tables(db_path)
    created_at = datetime.now(timezone.utc)
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute(
            """
            INSERT INTO execution_metadata (
                run_id, start_time, end_time, assets_evaluated, assets_skipped,
                errors_encountered, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, start_time.isoformat(), end_time.isoformat(), json.dumps(assets_evaluated),
                json.dumps(assets_skipped), json.dumps(errors_encountered), created_at.isoformat(),
            ),
        )
        conn.commit()
    return ExecutionMetadataRow(
        run_id=run_id, start_time=start_time, end_time=end_time, assets_evaluated=assets_evaluated,
        assets_skipped=assets_skipped, errors_encountered=errors_encountered,
    )


def list_execution_metadata(db_path: Path = DEFAULT_DB_PATH) -> list[ExecutionMetadataRow]:
    init_execution_tables(db_path)
    with closing(sqlite3.connect(str(db_path))) as conn:
        rows = conn.execute(
            "SELECT run_id, start_time, end_time, assets_evaluated, assets_skipped, errors_encountered "
            "FROM execution_metadata ORDER BY start_time ASC"
        ).fetchall()
    return [
        ExecutionMetadataRow(
            run_id=r[0], start_time=datetime.fromisoformat(r[1]), end_time=datetime.fromisoformat(r[2]),
            assets_evaluated=json.loads(r[3]), assets_skipped=json.loads(r[4]), errors_encountered=json.loads(r[5]),
        )
        for r in rows
    ]


def insert_news_sentiment_log(
    run_id: str,
    asset: str,
    fetch_timestamp: datetime,
    signal_type: NewsSignalType,
    confidence: float,
    reasoning: str,
    source: str,
    news_timestamp: datetime | None = None,
    sentiment_score: int | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Returns False (not an error) if this asset already has a logged row for this
    exact fetch_timestamp — a dedupe-on-insert safety net behind the daily cadence gate
    (see has_news_sentiment_logged_today)."""
    init_execution_tables(db_path)
    created_at = datetime.now(timezone.utc)
    with closing(sqlite3.connect(str(db_path))) as conn:
        try:
            conn.execute(
                """
                INSERT INTO news_sentiment_log (
                    run_id, asset, news_timestamp, fetch_timestamp, sentiment_score,
                    signal_type, confidence, reasoning, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, asset, news_timestamp.isoformat() if news_timestamp else None,
                    fetch_timestamp.isoformat(), sentiment_score, signal_type, confidence, reasoning, source,
                    created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError:
            return False
        conn.commit()
    return True


def has_news_sentiment_logged_today(asset: str, day: datetime, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """True if a news_sentiment_log row already exists for `asset` on `day`'s UTC
    calendar date — the daily-cadence gate that keeps a delayed/retried run within the
    same day's window from double-logging."""
    init_execution_tables(db_path)
    date_str = day.astimezone(timezone.utc).date().isoformat()
    with closing(sqlite3.connect(str(db_path))) as conn:
        row = conn.execute(
            "SELECT 1 FROM news_sentiment_log WHERE asset = ? AND substr(fetch_timestamp, 1, 10) = ? LIMIT 1",
            (asset, date_str),
        ).fetchone()
    return row is not None
