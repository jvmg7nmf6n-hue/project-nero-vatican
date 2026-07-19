"""Binance order-book depth snapshot fetcher + cache — Comprehensive Asset Expansion,
Part C: Crypto, Task C1 (ORDERFLOW_IMBALANCE v1.0.0).

INFRASTRUCTURE NOTE: GitHub Actions runners are US-based; api.binance.com returns HTTP
451 ("Service unavailable from a restricted location") to US IPs for public market
data. data-api.binance.vision is a Binance-operated, US-accessible mirror for exactly
this kind of public SPOT market data and is used here as the PRIMARY endpoint, with
api.binance.com as a secondary fallback (works fine outside GitHub Actions, e.g. local
development or a non-US runner).

v1.0 is REST-POLLING, not a WebSocket collector: the live scheduler is a 30-minute
GitHub Actions cron, and a persistent WebSocket connection is not something that
infrastructure can host. Each scheduler run takes exactly ONE depth snapshot per
symbol (GET /api/v3/depth?limit=20) and appends it to `orderbook_snapshots` (same
SQLite file as the Truth Ledger) — over many runs this accumulates a proprietary
orderbook-history dataset, not just a live signal input for this one strategy.

On total failure (both endpoints unreachable/erroring), this module raises
OrderbookDataUnavailableError — callers (the live scheduler) must log DATA_UNAVAILABLE
and continue, never crash the run and never fabricate a snapshot.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from nero_core.truth_ledger.models import DEFAULT_DB_PATH

BINANCE_VISION_DEPTH_URL = "https://data-api.binance.vision/api/v3/depth"
BINANCE_COM_DEPTH_URL = "https://api.binance.com/api/v3/depth"
DEPTH_LIMIT = 20

ORDERFLOW_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    best_bid REAL NOT NULL,
    best_ask REAL NOT NULL,
    bid_vol_20 REAL NOT NULL,
    ask_vol_20 REAL NOT NULL,
    imbalance_ratio REAL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_symbol_ts ON orderbook_snapshots (symbol, timestamp);
"""


class OrderbookDataUnavailableError(Exception):
    """Raised when neither Binance endpoint returns usable depth data — never
    fabricated; the caller must log DATA_UNAVAILABLE and continue."""


@dataclass(frozen=True)
class OrderbookSnapshot:
    timestamp: datetime
    symbol: str
    best_bid: float
    best_ask: float
    bid_vol_20: float
    ask_vol_20: float
    # None (not 0.0 or inf) when ask_vol_20 is zero — a genuinely undefined ratio,
    # never silently mapped to an arbitrary number.
    imbalance_ratio: float | None
    source: str


def _parse_depth_payload(payload: dict, symbol: str, source: str, timestamp: datetime) -> OrderbookSnapshot:
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    if not bids or not asks:
        raise OrderbookDataUnavailableError(f"{symbol}: empty bids/asks in depth payload from {source}")

    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    bid_vol_20 = sum(float(level[1]) for level in bids[:DEPTH_LIMIT])
    ask_vol_20 = sum(float(level[1]) for level in asks[:DEPTH_LIMIT])
    imbalance_ratio = (bid_vol_20 / ask_vol_20) if ask_vol_20 > 0 else None

    return OrderbookSnapshot(
        timestamp=timestamp, symbol=symbol, best_bid=best_bid, best_ask=best_ask,
        bid_vol_20=bid_vol_20, ask_vol_20=ask_vol_20, imbalance_ratio=imbalance_ratio, source=source,
    )


def fetch_orderbook_snapshot(
    symbol: str, timeout_seconds: float = 10.0, now: datetime | None = None
) -> OrderbookSnapshot:
    """Fetches ONE depth snapshot for `symbol` (e.g. "BTCUSDT"), trying
    data-api.binance.vision first (US-accessible), then api.binance.com. A failure at
    either stage (network error, corrupt JSON, empty book) falls through to the next
    source; raises OrderbookDataUnavailableError with both attempts' errors only if
    every source fails — never fabricates a snapshot."""
    now = now or datetime.now(timezone.utc)
    errors: list[str] = []
    for url, source in ((BINANCE_VISION_DEPTH_URL, "data-api.binance.vision"), (BINANCE_COM_DEPTH_URL, "api.binance.com")):
        try:
            response = requests.get(url, params={"symbol": symbol, "limit": DEPTH_LIMIT}, timeout=timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            return _parse_depth_payload(payload, symbol, source, now)
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, OrderbookDataUnavailableError) as exc:
            errors.append(f"{source}: {exc.__class__.__name__}: {exc}")

    raise OrderbookDataUnavailableError(f"{symbol}: both endpoints failed — {'; '.join(errors)}")


def init_orderbook_tables(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def insert_orderbook_snapshot(snapshot: OrderbookSnapshot, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Append-only — no update/delete, matching every other table sharing this Truth
    Ledger database (see nero_core.truth_ledger.execution_log's module docstring)."""
    init_orderbook_tables(db_path)
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute(
            """INSERT INTO orderbook_snapshots
               (timestamp, symbol, best_bid, best_ask, bid_vol_20, ask_vol_20, imbalance_ratio, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot.timestamp.isoformat(), snapshot.symbol, snapshot.best_bid, snapshot.best_ask,
                snapshot.bid_vol_20, snapshot.ask_vol_20, snapshot.imbalance_ratio, snapshot.source,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def latest_orderbook_snapshot(symbol: str, db_path: Path = DEFAULT_DB_PATH) -> OrderbookSnapshot | None:
    """The most recently cached snapshot for `symbol`, or None if nothing cached yet."""
    init_orderbook_tables(db_path)
    with closing(sqlite3.connect(str(db_path))) as conn:
        row = conn.execute(
            """SELECT timestamp, symbol, best_bid, best_ask, bid_vol_20, ask_vol_20, imbalance_ratio, source
               FROM orderbook_snapshots WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    return OrderbookSnapshot(
        timestamp=datetime.fromisoformat(row[0]), symbol=row[1], best_bid=row[2], best_ask=row[3],
        bid_vol_20=row[4], ask_vol_20=row[5], imbalance_ratio=row[6], source=row[7],
    )


def fetch_and_cache_snapshot(
    symbol: str, timeout_seconds: float = 10.0, now: datetime | None = None, db_path: Path = DEFAULT_DB_PATH
) -> OrderbookSnapshot:
    """Fetches a live snapshot and appends it to the cache table in one call — the
    convenience entrypoint the live scheduler uses each run. Raises
    OrderbookDataUnavailableError (not caught here) if the fetch itself fails; nothing
    is cached in that case."""
    snapshot = fetch_orderbook_snapshot(symbol, timeout_seconds=timeout_seconds, now=now)
    insert_orderbook_snapshot(snapshot, db_path=db_path)
    return snapshot
