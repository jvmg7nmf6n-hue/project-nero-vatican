"""Quarantine registry for execution_log rows whose entry and exit legs may have been
priced off different data sources -- see docs/execution_log_quarantine_migration_plan.md
for the full incident writeup and a proposed durable (schema-based) alternative to this
module.

CONFIRMED INCIDENT (2026-07-29 orderflow-verification investigation): before commit
c106b8d (2026-07-28T05:33:53Z, "fix Binance 451 bug"), api.binance.com's public klines
endpoint returned HTTP 451 to GitHub Actions' US runner IPs on every request.
MarketDataClient.load_intraday cascades Binance -> Coinbase -> Kraken on failure (see
nero_core/data_sources/market_data.py), so ORDERFLOW_IMBALANCE's BTC/ETH 1h candle
fetches were silently falling through to a non-Binance exchange on essentially every
pre-fix scheduler run. Because ENTRY and EXIT are two independent scheduler runs (not
one atomic transaction), a trade's entry could be priced off one exchange and its own
exit off a different one -- not a valid paper-traded round trip, since no single
executable venue would ever have produced that entry/exit pair.

Detected via a candle_timestamp epoch-millisecond signature discontinuity (Binance's
own kline close_time convention ends "...999" ms; every pre-fix row consistently ends
"...000" ms, consistent with a fallback exchange's own close_time convention) rather
than execution_log.data_source itself -- process_orderflow_imbalance did not persist
data_source until this same investigation's own fix (see live_scheduler.py's
process_orderflow_imbalance docstring), so no historical row in the quarantine window
carries a directly-logged source string. The cutoffs below are each asset's first
CONFIRMED post-fix candle_timestamp (the boundary row itself is clean; strictly
earlier candle_timestamps for that key are quarantined).

This is a documented-cutoff quarantine (Python constants + a filter function), not a
schema change: it works against the CURRENT execution_log schema with no ALTER TABLE
and no migration risk. See the migration-plan doc above for a proposed `quarantined`
column as a more durable long-term alternative -- planned, not applied.

FOLLOW-UP (2026-07-29, same day): even a row with data_source recorded isn't safe
alone -- ENTRY and EXIT are separate scheduler runs (separate fetches), so a resolved
trade's two legs can independently land on different exchanges even after the
Binance-451 fix, if Binance 451s again only transiently. `source_mismatched_trade_ids`/
`exclude_mismatched_sources` pair each ENTRY with its EXIT (chronological, one open
position at a time -- confirmed true for every ENTRY/EXIT-logging strategy in this
codebase today) and drop both legs of any pair whose recorded sources disagree.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from nero_core.strategies.orderflow_imbalance import STRATEGY_ID as ORDERFLOW_STRATEGY_ID
from nero_core.strategies.orderflow_imbalance import STRATEGY_VERSION as ORDERFLOW_STRATEGY_VERSION
from nero_core.truth_ledger.execution_log import DEFAULT_DB_PATH, ExecutionLogRow, list_execution_log

# (strategy, strategy_version, asset) -> minimum candle_timestamp (INCLUSIVE) considered
# clean. Any row for this key with a STRICTLY SMALLER candle_timestamp is quarantined.
# A (strategy, strategy_version, asset) key absent from this dict is never quarantined --
# quarantine is opt-in per confirmed incident, not a default suspicion cast over every
# strategy. See this module's docstring for how these two values were derived.
QUARANTINE_CUTOFFS: dict[tuple[str, str, str], int] = {
    (ORDERFLOW_STRATEGY_ID, ORDERFLOW_STRATEGY_VERSION, "BTC"): 1785254399999,
    (ORDERFLOW_STRATEGY_ID, ORDERFLOW_STRATEGY_VERSION, "ETH"): 1785257999999,
}


def is_quarantined(row: ExecutionLogRow) -> bool:
    """True if `row` predates its (strategy, strategy_version, asset)'s cutoff in
    QUARANTINE_CUTOFFS."""
    cutoff = QUARANTINE_CUTOFFS.get((row.strategy, row.strategy_version, row.asset))
    if cutoff is None:
        return False
    return row.candle_timestamp < cutoff


def exclude_quarantined(rows: Iterable[ExecutionLogRow]) -> list[ExecutionLogRow]:
    """Filters out every quarantined row, preserving order. Use this (not raw
    execution_log rows) anywhere a harness or report draws statistical conclusions
    from execution_log data."""
    return [row for row in rows if not is_quarantined(row)]


def _trade_pairs(rows: Iterable[ExecutionLogRow]) -> list[tuple[ExecutionLogRow, ExecutionLogRow | None]]:
    """Groups ENTRY/EXIT rows by (strategy, strategy_version, asset), orders each
    group chronologically (candle_timestamp, then id as a tiebreak), and pairs each
    ENTRY with the EXIT that immediately follows it for that same key. Assumes one
    open position at a time per key -- true for every ENTRY/EXIT-logging strategy in
    this codebase today (confirmed for ORDERFLOW_IMBALANCE's live history: strict
    ENTRY/EXIT/ENTRY/EXIT alternation, no overlaps). An ENTRY with no following EXIT
    yet (still open) or an EXIT with no preceding ENTRY (shouldn't happen given the
    above, but handled defensively) pairs with None and is never flagged as
    mismatched -- only a CONFIRMED two-sided disagreement is a mismatch."""
    grouped: dict[tuple[str, str, str], list[ExecutionLogRow]] = defaultdict(list)
    for row in rows:
        if row.signal_type in ("ENTRY", "EXIT"):
            grouped[(row.strategy, row.strategy_version, row.asset)].append(row)

    pairs: list[tuple[ExecutionLogRow, ExecutionLogRow | None]] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda r: (r.candle_timestamp, r.id or 0))
        pending_entry: ExecutionLogRow | None = None
        for row in ordered:
            if row.signal_type == "ENTRY":
                if pending_entry is not None:
                    pairs.append((pending_entry, None))
                pending_entry = row
            else:  # EXIT
                if pending_entry is not None:
                    pairs.append((pending_entry, row))
                    pending_entry = None
                # else: orphaned EXIT with no preceding ENTRY in this key -- not
                # something this function can pair or flag; left out of `pairs`
                # entirely rather than guessed at.
        if pending_entry is not None:
            pairs.append((pending_entry, None))
    return pairs


def source_mismatched_trade_ids(rows: Iterable[ExecutionLogRow]) -> set[int]:
    """Row ids belonging to a resolved (ENTRY, EXIT) pair whose recorded data_source
    values disagree -- both legs' ids are included, since a mismatched trade isn't
    valid evidence from either side. A pair where either leg is still open (paired
    with None) or either leg's data_source is None is never flagged here -- that's a
    "can't verify" case, not a confirmed mismatch."""
    mismatched: set[int] = set()
    for entry, exit_row in _trade_pairs(rows):
        if exit_row is None:
            continue
        if entry.data_source is None or exit_row.data_source is None:
            continue
        if entry.data_source != exit_row.data_source:
            if entry.id is not None:
                mismatched.add(entry.id)
            if exit_row.id is not None:
                mismatched.add(exit_row.id)
    return mismatched


def exclude_mismatched_sources(rows: Iterable[ExecutionLogRow]) -> list[ExecutionLogRow]:
    """Drops both legs of any resolved ENTRY/EXIT pair whose recorded data_source
    values disagree, preserving order. Mismatch detection runs against the full given
    row set before filtering (source_mismatched_trade_ids needs both legs present to
    pair correctly) -- callers should pass this a row set that still has every leg
    present."""
    rows = list(rows)
    mismatched_ids = source_mismatched_trade_ids(rows)
    return [row for row in rows if row.id not in mismatched_ids]


def list_clean_execution_log(
    db_path: Path = DEFAULT_DB_PATH, asset: str | None = None, strategy: str | None = None
) -> list[ExecutionLogRow]:
    """list_execution_log's quarantine-aware counterpart -- the entrypoint any future
    statistical-verification harness should call instead of list_execution_log
    directly. Applies, in order: the documented incident-cutoff (exclude_quarantined),
    then the entry/exit source-agreement check (exclude_mismatched_sources)."""
    rows = exclude_quarantined(list_execution_log(db_path=db_path, asset=asset, strategy=strategy))
    return exclude_mismatched_sources(rows)
