"""Truth Ledger -> static JSON export for the future public website (WEBSITE PHASE
Step 1). Runs as its own GitHub Actions step (deliberately separate from
live_scheduler.py and notify_ntfy.py, same reasoning as notify_ntfy.py's own
docstring — an export failure must never affect whether a signal gets logged or a
notification sent, and vice versa), positioned in the workflow AFTER the scheduler run
and BEFORE the "Save Truth Ledger" auto-commit step, so the exported JSON files land in
the same commit as the ledger update that produced them.

STRICTLY READ-ONLY over the ledger: every function here only ever calls
nero_core.truth_ledger.execution_log's list_* functions, never an insert/update/delete.

Output: docs/site_data/{ledger_full,ledger_recent,stats,strategies}.json — every file
carries schema_version: 1 and last_updated (UTC ISO8601) at the top level, deterministic
ordering, and a fixed, lean field set (no debug fields, no internal bookkeeping columns
like run_id/created_at). `candle_timestamp` (stored internally as epoch ms) and
`timestamp` are both exported as ISO8601 strings — a public JSON API shouldn't require
consumers to know this system's internal epoch-ms storage convention.

ROUND-TRIP PAIRING (stats.json): within one (strategy, strategy_version, asset) group,
sorted chronologically, each ENTRY is paired with the next EXIT that follows it. This
is unambiguous because the live scheduler only ever holds one open position per config
at a time (see nero_core.execution.live_scheduler), so ENTRY/EXIT rows already
alternate — no heuristic matching is needed. A trailing, unpaired ENTRY is the
config's current open position, reported separately, never counted as a "resolved"
trade. `expectancy_r` is parsed from the EXIT row's `reasoning` text (the same
r_multiple=... convention nero_core.execution.notify_ntfy already parses) and is
`null` whenever ANY round-trip in the group doesn't carry a parseable value (e.g.
COINTEGRATION_PAIRS' reasoning never includes an r_multiple — see
nero_core.execution.replay) — never averaged over a partial subset. `win_rate` and
`avg_return_pct` are instead computed directly from the always-structured
entry_price/exit_price columns, so real per-trade-quality signal is still reported
even when a true R-multiple isn't recoverable from this strategy family's ledger text.
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.execution.live_scheduler import (
    COINTEGRATION_PAIRS_ID,
    COINTEGRATION_PAIRS_VERSION,
    NEWS_SENTIMENT_ASSETS,
    NEWS_SENTIMENT_ID,
    PAIRS_ASSETS,
    PAIRS_TIMEFRAME,
    SINGLE_ASSET_CONFIGS,
)
from nero_core.execution.verification_status import verification_status_for
from nero_core.strategies.news_sentiment import STRATEGY_VERSION as NEWS_SENTIMENT_VERSION
from nero_core.truth_ledger.execution_log import DEFAULT_DB_PATH, ExecutionLogRow, list_execution_log

SCHEMA_VERSION = 1
RECENT_LEDGER_LIMIT = 200
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "site_data"

_R_MULTIPLE_PATTERN = re.compile(r"r_multiple=([-+]?\d*\.?\d+)")


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _candle_iso(candle_timestamp_ms: int) -> str:
    return datetime.fromtimestamp(candle_timestamp_ms / 1000.0, tz=timezone.utc).isoformat()


def _row_to_ledger_dict(row: ExecutionLogRow) -> dict[str, object]:
    return {
        "timestamp": row.timestamp.isoformat(),
        "strategy": row.strategy,
        "asset": row.asset,
        "signal_type": row.signal_type,
        "entry_price": row.entry_price,
        "exit_price": row.exit_price,
        "reasoning": row.reasoning,
        "candle_timestamp": _candle_iso(row.candle_timestamp),
    }


def _sorted_newest_first(rows: list[ExecutionLogRow]) -> list[ExecutionLogRow]:
    return sorted(rows, key=lambda r: (r.candle_timestamp, r.id or 0), reverse=True)


def build_ledger_export(
    rows: list[ExecutionLogRow], limit: int | None = None, now: datetime | None = None
) -> dict[str, object]:
    ordered = _sorted_newest_first(rows)
    if limit is not None:
        ordered = ordered[:limit]
    return {
        "schema_version": SCHEMA_VERSION,
        "last_updated": _now_iso(now),
        "rows": [_row_to_ledger_dict(r) for r in ordered],
    }


@dataclass(frozen=True)
class _RoundTrip:
    entry_row: ExecutionLogRow
    exit_row: ExecutionLogRow


def _pair_round_trips(rows_chronological: list[ExecutionLogRow]) -> tuple[list[_RoundTrip], ExecutionLogRow | None]:
    """`rows_chronological` must already be sorted ascending (oldest first) for ONE
    (strategy, strategy_version, asset) group. Returns (completed round-trips, the
    trailing open ENTRY if the group currently has an unresolved position, else None).
    An EXIT with no preceding open ENTRY (shouldn't happen given the scheduler's
    one-trade-at-a-time invariant) is skipped rather than fabricating a pairing."""
    round_trips: list[_RoundTrip] = []
    open_entry: ExecutionLogRow | None = None
    for row in rows_chronological:
        if row.signal_type == "ENTRY":
            open_entry = row
        elif row.signal_type == "EXIT":
            if open_entry is not None:
                round_trips.append(_RoundTrip(entry_row=open_entry, exit_row=row))
                open_entry = None
    return round_trips, open_entry


def _extract_r_multiple(reasoning: str) -> float | None:
    match = _R_MULTIPLE_PATTERN.search(reasoning)
    return float(match.group(1)) if match else None


def _round_trip_return_pct(round_trip: _RoundTrip) -> float | None:
    entry_price = round_trip.entry_row.entry_price
    exit_price = round_trip.exit_row.exit_price
    if entry_price is None or exit_price is None or entry_price == 0:
        return None
    return (exit_price - entry_price) / entry_price * 100.0


SIGNAL_TYPES = ("ENTRY", "EXIT", "WATCH", "NO_TRADE")


def _strategy_stats(strategy_id: str, strategy_version: str, asset: str, group_rows: list[ExecutionLogRow]) -> dict[str, object]:
    chronological = sorted(group_rows, key=lambda r: (r.candle_timestamp, r.id or 0))
    round_trips, open_entry = _pair_round_trips(chronological)

    signal_counts = {signal_type: 0 for signal_type in SIGNAL_TYPES}
    for row in group_rows:
        signal_counts[row.signal_type] = signal_counts.get(row.signal_type, 0) + 1

    resolved_trades = len(round_trips)
    win_rate: float | None = None
    avg_return_pct: float | None = None
    expectancy_r: float | None = None

    if resolved_trades > 0:
        returns = [_round_trip_return_pct(rt) for rt in round_trips]
        valid_returns = [r for r in returns if r is not None]
        if valid_returns:
            win_rate = sum(1 for r in valid_returns if r > 0) / len(valid_returns)
            avg_return_pct = sum(valid_returns) / len(valid_returns)

        r_multiples = [_extract_r_multiple(rt.exit_row.reasoning) for rt in round_trips]
        if r_multiples and all(r is not None for r in r_multiples):
            expectancy_r = sum(r_multiples) / len(r_multiples)

    open_position = None
    if open_entry is not None:
        open_position = {
            "entry_price": open_entry.entry_price,
            "entry_timestamp": open_entry.timestamp.isoformat(),
            "candle_timestamp": _candle_iso(open_entry.candle_timestamp),
        }

    return {
        "strategy": strategy_id,
        "strategy_version": strategy_version,
        "asset": asset,
        "resolved_trades": resolved_trades,
        "win_rate": win_rate,
        "expectancy_r": expectancy_r,
        "avg_return_pct": avg_return_pct,
        "signal_counts": signal_counts,
        "open_position": open_position,
    }


def _trading_roster_keys() -> list[tuple[str, str, str]]:
    """(strategy_id, strategy_version, asset) for every TRADING config in the live
    roster — i.e. every config with a genuine ENTRY/EXIT concept in execution_log.
    Excludes NEWS_SENTIMENT (a forward-only sentiment signal with no positions, logged
    to a separate table with its own BUY_BIAS/SELL_BIAS/NEUTRAL vocabulary —
    round-trip pairing has no meaning for it; it still appears in strategies.json)."""
    keys = [(c.strategy_id, c.strategy_version, c.asset) for c in SINGLE_ASSET_CONFIGS]
    keys.append((COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, "-".join(PAIRS_ASSETS)))
    return keys


def build_stats_export(rows: list[ExecutionLogRow], now: datetime | None = None) -> dict[str, object]:
    """Always lists exactly the current trading roster (see _trading_roster_keys), in
    that fixed order, regardless of what's actually in the ledger — a freshly-deployed
    config with zero logged rows still appears, with resolved_trades: 0 and every
    aggregate null, rather than being silently absent."""
    groups: dict[tuple[str, str, str], list[ExecutionLogRow]] = {}
    for row in rows:
        groups.setdefault((row.strategy, row.strategy_version, row.asset), []).append(row)

    strategies = [
        _strategy_stats(strategy_id, strategy_version, asset, groups.get((strategy_id, strategy_version, asset), []))
        for strategy_id, strategy_version, asset in _trading_roster_keys()
    ]
    return {"schema_version": SCHEMA_VERSION, "last_updated": _now_iso(now), "strategies": strategies}


def _roster_entries() -> list[dict[str, object]]:
    entries = [
        {
            "name": config.strategy_id,
            "version": config.strategy_version,
            "asset": config.asset,
            "timeframe": config.timeframe,
            "verification_status": verification_status_for(config.strategy_id, config.asset),
        }
        for config in SINGLE_ASSET_CONFIGS
    ]
    pairs_label = "-".join(PAIRS_ASSETS)
    entries.append(
        {
            "name": COINTEGRATION_PAIRS_ID,
            "version": COINTEGRATION_PAIRS_VERSION,
            "asset": pairs_label,
            "timeframe": PAIRS_TIMEFRAME,
            "verification_status": verification_status_for(COINTEGRATION_PAIRS_ID, pairs_label),
        }
    )
    for asset in NEWS_SENTIMENT_ASSETS:
        entries.append(
            {
                "name": NEWS_SENTIMENT_ID,
                "version": NEWS_SENTIMENT_VERSION,
                "asset": asset,
                "timeframe": "daily",
                "verification_status": verification_status_for(NEWS_SENTIMENT_ID, asset),
            }
        )
    return entries


def build_strategies_export(now: datetime | None = None) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "last_updated": _now_iso(now), "strategies": _roster_entries()}


def write_site_data(db_path: Path = DEFAULT_DB_PATH, output_dir: Path = DEFAULT_OUTPUT_DIR, now: datetime | None = None) -> None:
    """Reads the full Truth Ledger (read-only) and writes all four JSON files. Raises
    on failure — main() is responsible for catching and logging so an export problem
    never fails the scheduler, the same non-fatal pattern
    nero_core.execution.notify_ntfy already uses."""
    rows = list_execution_log(db_path=db_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    exports = {
        "ledger_full.json": build_ledger_export(rows, limit=None, now=now),
        "ledger_recent.json": build_ledger_export(rows, limit=RECENT_LEDGER_LIMIT, now=now),
        "stats.json": build_stats_export(rows, now=now),
        "strategies.json": build_strategies_export(now=now),
    }
    for filename, payload in exports.items():
        # ensure_ascii=False: this is UTF-8 text meant to be human-browsable (verification
        # status strings use an em dash) - escaping every non-ASCII character to \uXXXX
        # would still be valid JSON but needlessly unreadable for a public data file.
        (output_dir / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    """Never raises — an export failure must show up in the GitHub Actions log but
    must not fail the workflow step itself."""
    try:
        write_site_data()
        print(f"Exported site data to {DEFAULT_OUTPUT_DIR}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
