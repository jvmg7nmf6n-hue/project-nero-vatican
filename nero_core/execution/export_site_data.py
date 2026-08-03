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

QUARANTINE (2026-07-30, fixing the gap the ORDERFLOW_IMBALANCE incident exposed):
every ENTRY/EXIT round trip feeding stats.json's resolved_trades/win_rate/
avg_return_pct/expectancy_r/open_position, and every ENTRY/EXIT row included in
ledger_full.json/ledger_recent.json, must first survive nero_core.execution.
quarantine's full clean-trade filter chain (exclude_quarantined ->
exclude_mismatched_sources -> exclude_unrecorded_source -- see _clean_trade_rows).
This module previously read straight from list_execution_log with no quarantine
awareness at all, which let a 32-trade, entirely-NULL-data_source ORDERFLOW_IMBALANCE
sample display on the public site as if it were 32 verified round trips (48% win
rate, -0.16% avg return) — the true clean sample at the time was 4. The fix is
structural (inside _strategy_stats and write_site_data), not an ORDERFLOW-specific
patch: it runs identically for every roster entry, so any strategy's first
unverified-source trade is caught automatically rather than requiring a name check.
WATCH/NO_TRADE rows are never trade legs and are exempt — they carry no performance
claim, so quarantine.py's incident has nothing to say about them; they stay in
signal_counts and the ledger export unfiltered. `unverified_trades` on each
stats.json entry is the count of raw resolved round trips that did NOT survive this
filter, so the website can render an honest "N trades pending source verification"
state (see website/lib/statLine.ts) instead of either silently showing a
contaminated stat or silently collapsing to "no trades yet."
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
    DONCHIAN_FOREX_CONFIGS,
    DONCHIAN_FOREX_TIMEFRAME,
    DONCHIAN_TREND_ID,
    GOLD_SILVER_RATIO_ID,
    GOLD_SILVER_RATIO_LABEL,
    GOLD_SILVER_RATIO_TIMEFRAME,
    GOLD_SILVER_RATIO_VERSION,
    NEWS_SENTIMENT_ASSETS,
    NEWS_SENTIMENT_ID,
    ORDERFLOW_BINANCE_SYMBOLS,
    ORDERFLOW_ID,
    ORDERFLOW_VERSION,
    PAIRS_ASSETS,
    PAIRS_TIMEFRAME,
    PEAD_CONFIGS,
    PEAD_ID,
    SINGLE_ASSET_CONFIGS,
)
# Reused, not re-derived (this module's own established convention) --
# the SAME regex live_scheduler.py's own _reconstruct_open_position uses to
# recover ORDERFLOW_IMBALANCE's direction/stop_loss from ENTRY reasoning
# text, needed here for the R-multiple reconstruction fallback below (see
# _extract_or_reconstruct_r_multiple's own docstring).
from nero_core.execution.live_scheduler import (
    _ORDERFLOW_DIRECTION_PATTERN,
    _ORDERFLOW_STOP_LOSS_PATTERN,
)
from nero_core.execution.quarantine import (
    exclude_mismatched_sources,
    exclude_quarantined,
    exclude_unrecorded_source,
    is_quarantined,
)
from nero_core.execution.backtest_evaluation import backtest_evaluation_for
from nero_core.execution.source_reports import source_report_for, source_report_written_at
from nero_core.execution.verification_status import verification_status_for
from nero_core.strategies.news_sentiment import STRATEGY_VERSION as NEWS_SENTIMENT_VERSION
from nero_core.strategies.news_sentiment_llm import STRATEGY_VERSION as NEWS_SENTIMENT_LLM_VERSION
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
        "strategy_version": row.strategy_version,
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


def _reconstruct_r_multiple(round_trip: "_RoundTrip") -> float | None:
    """Fallback for a strategy whose own EXIT reasoning never embeds
    r_multiple= at all (found this session: ORDERFLOW_IMBALANCE -- its
    reasoning is `f"{exit_reason} exit, imbalance_ratio={...}"`, a real
    pipeline gap, not a property of the strategy -- win rate alone was
    already shown to be misleading by omission for it: 61.5% wins at
    +0.012R). Reconstructs R the same way live_scheduler.py's own
    _reconstruct_open_position recovers direction/stop_loss for exit
    evaluation -- entry_price is already a native ExecutionLogRow column
    (never text-embedded), so only direction/stop_loss need parsing from
    the ENTRY row's reasoning text.

    Deliberately generic (not name-checked to ORDERFLOW_IMBALANCE): applies
    to ANY strategy whose ENTRY reasoning happens to embed direction=/
    stop_loss= but whose EXIT reasoning has no r_multiple= -- scopes itself
    to exactly the right rows by construction, not by a strategy-id branch
    that could drift out of sync with which strategies actually need this.

    Returns None (never a fabricated number) if entry_price/exit_price is
    missing, the ENTRY reasoning doesn't match the expected shape, or the
    implied risk (|entry_price - stop_loss|) is zero -- exactly the same
    "fail toward no number" discipline _extract_r_multiple already has."""
    entry_price = round_trip.entry_row.entry_price
    exit_price = round_trip.exit_row.exit_price
    if entry_price is None or exit_price is None:
        return None

    direction_match = _ORDERFLOW_DIRECTION_PATTERN.search(round_trip.entry_row.reasoning)
    stop_match = _ORDERFLOW_STOP_LOSS_PATTERN.search(round_trip.entry_row.reasoning)
    if direction_match is None or stop_match is None:
        return None

    stop_loss = float(stop_match.group(1))
    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit <= 0:
        return None

    if direction_match.group(1) == "LONG":
        return (exit_price - entry_price) / risk_per_unit
    return (entry_price - exit_price) / risk_per_unit


def _extract_or_reconstruct_r_multiple(round_trip: "_RoundTrip") -> float | None:
    """Tries the standard embedded-in-EXIT-reasoning extraction first (every
    strategy that already logs r_multiple= directly -- unchanged behavior);
    falls back to reconstruction ONLY when that fails. A strategy that
    already logs r_multiple= directly is never affected by this fallback
    even if its reasoning also happened to contain a direction=/stop_loss=
    substring, since the primary extraction already succeeded."""
    direct = _extract_r_multiple(round_trip.exit_row.reasoning)
    if direct is not None:
        return direct
    return _reconstruct_r_multiple(round_trip)


def _round_trip_return_pct(round_trip: _RoundTrip) -> float | None:
    entry_price = round_trip.entry_row.entry_price
    exit_price = round_trip.exit_row.exit_price
    if entry_price is None or exit_price is None or entry_price == 0:
        return None
    return (exit_price - entry_price) / entry_price * 100.0


SIGNAL_TYPES = ("ENTRY", "EXIT", "WATCH", "NO_TRADE")
_TRADE_SIGNAL_TYPES = ("ENTRY", "EXIT")


def _clean_trade_rows(rows: list[ExecutionLogRow]) -> list[ExecutionLogRow]:
    """ENTRY/EXIT rows from `rows` that survive nero_core.execution.quarantine's full
    clean-trade filter chain, applied in the same order list_clean_execution_log uses
    (exclude_quarantined -> exclude_mismatched_sources -> exclude_unrecorded_source) --
    reused directly, never reimplemented, per that module's own docstring. WATCH/
    NO_TRADE rows are dropped here on purpose: this answers "which TRADE LEGS are
    confirmed clean," not "which rows are clean" -- WATCH/NO_TRADE carry no
    performance claim (no entry/exit price pair to misrepresent), so callers that need
    them (signal_counts, the ledger export) source them separately, unfiltered."""
    trade_rows = [r for r in rows if r.signal_type in _TRADE_SIGNAL_TYPES]
    trade_rows = exclude_quarantined(trade_rows)
    trade_rows = exclude_mismatched_sources(trade_rows)
    return exclude_unrecorded_source(trade_rows)


def _strategy_stats(strategy_id: str, strategy_version: str, asset: str, group_rows: list[ExecutionLogRow]) -> dict[str, object]:
    chronological = sorted(group_rows, key=lambda r: (r.candle_timestamp, r.id or 0))

    # Round trips/open position are computed from the CONFIRMED-CLEAN subset only --
    # see _clean_trade_rows. `raw_round_trips` (unfiltered) exists only to derive
    # unverified_trades below; it is never used for win_rate/avg_return_pct/
    # expectancy_r/open_position, which must never be computed over an unconfirmed
    # source (see docs/execution_log_quarantine_migration_plan.md incident writeup --
    # this is exactly the gap that let a 32-trade, all-NULL-source ORDERFLOW_IMBALANCE
    # sample display as if it were verified performance evidence).
    raw_trade_rows = [r for r in chronological if r.signal_type in _TRADE_SIGNAL_TYPES]
    raw_round_trips, raw_open_entry = _pair_round_trips(raw_trade_rows)
    clean_trade_rows = _clean_trade_rows(chronological)
    round_trips, open_entry = _pair_round_trips(clean_trade_rows)

    # signal_counts stays raw/unfiltered -- it's an activity tally ("N signals of
    # each type were logged"), not a performance claim, so quarantine has no reason
    # to hide it (a strategy that logged 7 NO_TRADE evaluations before its data
    # source was wired should still show 7, not silently drop to 0).
    signal_counts = {signal_type: 0 for signal_type in SIGNAL_TYPES}
    for row in group_rows:
        signal_counts[row.signal_type] = signal_counts.get(row.signal_type, 0) + 1

    resolved_trades = len(round_trips)
    # Resolved round trips that existed in the raw ledger but did not survive the
    # clean-trade filter (quarantined by incident cutoff, mismatched entry/exit
    # source, or missing a recorded source entirely) -- the honest count behind the
    # website's "N trades pending source verification" state (see lib/statLine.ts /
    # app/strategy/[id]/page.tsx), never surfaced as 0 resolved trades pretending
    # nothing happened.
    unverified_trades = len(raw_round_trips) - resolved_trades

    # Phase 1 Fix A (docs/investigations/phase_a_pead_ledger_anomaly.md): the
    # OPEN-position counterpart to unverified_trades above. A trailing ENTRY
    # that exists in the raw ledger but was dropped from the clean subset
    # SOLELY by exclude_unrecorded_source (never quarantined by an incident
    # cutoff -- that's a materially different, already-flagged case) must not
    # silently collapse to the same open_position=None a config with no
    # signal at all shows. A lone open entry can never fail
    # exclude_mismatched_sources (that filter only drops a PAIRED
    # ENTRY/EXIT whose sources disagree; an entry with no exit yet has
    # nothing to disagree with), so checking is_quarantined + data_source is
    # None fully characterizes "unrecorded-source-only" for this case.
    unverified_open_entries = 0
    if open_entry is None and raw_open_entry is not None:
        if not is_quarantined(raw_open_entry) and raw_open_entry.data_source is None:
            unverified_open_entries = 1

    win_rate: float | None = None
    avg_return_pct: float | None = None
    expectancy_r: float | None = None

    if resolved_trades > 0:
        returns = [_round_trip_return_pct(rt) for rt in round_trips]
        valid_returns = [r for r in returns if r is not None]
        if valid_returns:
            win_rate = sum(1 for r in valid_returns if r > 0) / len(valid_returns)
            avg_return_pct = sum(valid_returns) / len(valid_returns)

        r_multiples = [_extract_or_reconstruct_r_multiple(rt) for rt in round_trips]
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
        "unverified_trades": unverified_trades,
        "win_rate": win_rate,
        "expectancy_r": expectancy_r,
        "avg_return_pct": avg_return_pct,
        "signal_counts": signal_counts,
        "open_position": open_position,
        "unverified_open_entries": unverified_open_entries,
    }


def _trading_roster_keys() -> list[tuple[str, str, str]]:
    """(strategy_id, strategy_version, asset) for every TRADING config in the live
    roster — i.e. every config with a genuine ENTRY/EXIT concept in execution_log.
    Excludes NEWS_SENTIMENT (a forward-only sentiment signal with no positions, logged
    to a separate table with its own BUY_BIAS/SELL_BIAS/NEUTRAL vocabulary —
    round-trip pairing has no meaning for it; it still appears in strategies.json)."""
    keys = [(c.strategy_id, c.strategy_version, c.asset) for c in SINGLE_ASSET_CONFIGS]
    keys.append((COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, "-".join(PAIRS_ASSETS)))
    keys.extend((ORDERFLOW_ID, ORDERFLOW_VERSION, asset) for asset in ORDERFLOW_BINANCE_SYMBOLS)
    keys.append((GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL))
    keys.extend((PEAD_ID, c.strategy_version, c.ticker) for c in PEAD_CONFIGS)
    keys.extend((DONCHIAN_TREND_ID, c.strategy_version, c.pair) for c in DONCHIAN_FOREX_CONFIGS)
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
            "verification_status": verification_status_for(config.strategy_id, config.strategy_version, config.asset),
            "source_report": source_report_for(config.strategy_id, config.strategy_version, config.asset),
            "source_report_written_at": source_report_written_at(source_report_for(config.strategy_id, config.strategy_version, config.asset)),
            "backtest_evaluation": backtest_evaluation_for(config.strategy_id, config.strategy_version, config.asset),
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
            "verification_status": verification_status_for(COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, pairs_label),
            "source_report": source_report_for(COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, pairs_label),
            "source_report_written_at": source_report_written_at(source_report_for(COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, pairs_label)),
            "backtest_evaluation": backtest_evaluation_for(COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, pairs_label),
        }
    )
    for asset in NEWS_SENTIMENT_ASSETS:
        entries.append(
            {
                "name": NEWS_SENTIMENT_ID,
                "version": NEWS_SENTIMENT_VERSION,
                "asset": asset,
                "timeframe": "daily",
                "verification_status": verification_status_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_VERSION, asset),
                "source_report": source_report_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_VERSION, asset),
                "source_report_written_at": source_report_written_at(source_report_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_VERSION, asset)),
                "backtest_evaluation": backtest_evaluation_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_VERSION, asset),
            }
        )
    # news-sentiment-v2.0.0-llm-claude wired 2026-07-28 IN PARALLEL with v1.0.0 above
    # (never replacing it) -- a separate, distinct roster entry so the site's strategy
    # pages, /lab, and site_summary counts reflect both versions honestly rather than
    # merging or confusing them.
    for asset in NEWS_SENTIMENT_ASSETS:
        entries.append(
            {
                "name": NEWS_SENTIMENT_ID,
                "version": NEWS_SENTIMENT_LLM_VERSION,
                "asset": asset,
                "timeframe": "daily",
                "verification_status": verification_status_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_LLM_VERSION, asset),
                "source_report": source_report_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_LLM_VERSION, asset),
                "source_report_written_at": source_report_written_at(source_report_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_LLM_VERSION, asset)),
                "backtest_evaluation": backtest_evaluation_for(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_LLM_VERSION, asset),
            }
        )
    for asset in ORDERFLOW_BINANCE_SYMBOLS:
        entries.append(
            {
                "name": ORDERFLOW_ID,
                "version": ORDERFLOW_VERSION,
                "asset": asset,
                "timeframe": "snapshot",
                "verification_status": verification_status_for(ORDERFLOW_ID, ORDERFLOW_VERSION, asset),
                "source_report": source_report_for(ORDERFLOW_ID, ORDERFLOW_VERSION, asset),
                "source_report_written_at": source_report_written_at(source_report_for(ORDERFLOW_ID, ORDERFLOW_VERSION, asset)),
                "backtest_evaluation": backtest_evaluation_for(ORDERFLOW_ID, ORDERFLOW_VERSION, asset),
            }
        )
    entries.append(
        {
            "name": GOLD_SILVER_RATIO_ID,
            "version": GOLD_SILVER_RATIO_VERSION,
            "asset": GOLD_SILVER_RATIO_LABEL,
            "timeframe": GOLD_SILVER_RATIO_TIMEFRAME,
            "verification_status": verification_status_for(GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL),
            "source_report": source_report_for(GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL),
            "source_report_written_at": source_report_written_at(source_report_for(GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL)),
            "backtest_evaluation": backtest_evaluation_for(GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL),
        }
    )
    for config in PEAD_CONFIGS:
        entries.append(
            {
                "name": PEAD_ID,
                "version": config.strategy_version,
                "asset": config.ticker,
                "timeframe": "1day",
                "verification_status": verification_status_for(PEAD_ID, config.strategy_version, config.ticker),
                "source_report": source_report_for(PEAD_ID, config.strategy_version, config.ticker),
                "source_report_written_at": source_report_written_at(source_report_for(PEAD_ID, config.strategy_version, config.ticker)),
                "backtest_evaluation": backtest_evaluation_for(PEAD_ID, config.strategy_version, config.ticker),
            }
        )
    for config in DONCHIAN_FOREX_CONFIGS:
        entries.append(
            {
                "name": DONCHIAN_TREND_ID,
                "version": config.strategy_version,
                "asset": config.pair,
                "timeframe": DONCHIAN_FOREX_TIMEFRAME,
                "verification_status": verification_status_for(DONCHIAN_TREND_ID, config.strategy_version, config.pair),
                "source_report": source_report_for(DONCHIAN_TREND_ID, config.strategy_version, config.pair),
                "source_report_written_at": source_report_written_at(source_report_for(DONCHIAN_TREND_ID, config.strategy_version, config.pair)),
                "backtest_evaluation": backtest_evaluation_for(DONCHIAN_TREND_ID, config.strategy_version, config.pair),
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

    # The public trade-by-trade ledger must not include an ENTRY/EXIT leg that
    # didn't survive _clean_trade_rows's quarantine chain -- same reasoning as
    # _strategy_stats above, applied to the raw ledger export instead of the
    # aggregates. WATCH/NO_TRADE rows are never trade legs and pass through
    # unfiltered (see _clean_trade_rows's own docstring).
    clean_trade_ids = {r.id for r in _clean_trade_rows(rows) if r.id is not None}
    ledger_rows = [r for r in rows if r.signal_type not in _TRADE_SIGNAL_TYPES or r.id in clean_trade_ids]

    exports = {
        "ledger_full.json": build_ledger_export(ledger_rows, limit=None, now=now),
        "ledger_recent.json": build_ledger_export(ledger_rows, limit=RECENT_LEDGER_LIMIT, now=now),
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
