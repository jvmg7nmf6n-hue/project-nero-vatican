"""Twice-daily strategy health check, run by its own GitHub Actions workflow
(.github/workflows/health_check.yml) on a schedule independent of the live
scheduler's own cron -- so a silent per-strategy starvation bug (like the
2026-07-28 PEAD/24h+1week candle_boundary_due tolerance bug, which left every
"24h"/"1week" strategy including GOLD/1week/BREAKOUT_MOMENTUM, this project's own
flagship SURVIVOR, unevaluated for 10+ days) gets caught within hours, not
discovered weeks later by someone manually checking. See
nero_core/execution/candle_schedule.py's own BUG FOUND note for the incident this
watchdog exists to catch going forward.

STRICTLY READ-ONLY over the Truth Ledger, same discipline as
nero_core.execution.export_site_data: every function here only ever calls
nero_core.truth_ledger.execution_log's list_*/latest_* functions, never an
insert/update/delete, and it never touches strategy logic or the live scheduler's
own gating -- it only reads what the scheduler already wrote and reports on it.

STALENESS SIGNAL -- two different bases, deliberately:
  - Most strategies (every SINGLE_ASSET_CONFIGS entry, COINTEGRATION_PAIRS,
    DONCHIAN_TREND forex, NEWS_SENTIMENT) log a signal on essentially every
    successful gate-satisfied evaluation, even when there's nothing to trade
    (NO_TRADE / NEUTRAL) -- see nero_core.execution.replay's own module docstring.
    For these, "last logged signal" IS an accurate proxy for "last successful
    evaluation," so staleness is judged directly against it.
  - PEAD and GOLD_SILVER_RATIO_MR are event-driven: replay_pead_events /
    replay_gold_silver_ratio_events correctly write NOTHING to execution_log on
    the overwhelming majority of runs (no qualifying earnings surprise / ratio
    extreme that day -- see nero_core.strategies.pead's own module docstring).
    For these, "last logged signal" can be legitimately old, or even None,
    while the scheduler is working perfectly -- using it would make this
    watchdog permanently cry wolf on exactly the strategies it most needs to
    watch correctly. Instead, staleness is judged against "was the shared 24h
    gate satisfied by any REAL recorded scheduler run recently" -- recomputed
    directly via candle_boundary_due against execution_metadata's own
    start_time history, the exact diagnostic technique that found the
    2026-07-28 bug in the first place.
  - ORDERFLOW_IMBALANCE has no candle_boundary_due gate at all (evaluated every
    run -- see nero_core/strategies/orderflow_imbalance.py's own module
    docstring) and only logs on a real ENTRY/EXIT, so neither basis applies:
    this class of starvation bug cannot happen to it (there's no gate to get
    stuck on), so it's reported but never flagged stale.

FRESHNESS GAP (2026-07-29 infrastructure-resilience follow-up): the staleness
check above answers "was this strategy evaluated at all, recently enough" --
binary, and only trips once a strategy has gone fully silent past its own
MAX_GAP_HOURS_BY_GATE threshold. It does NOT catch a strategy that IS still
being evaluated every period, just later and later each time -- e.g. a gate
whose candle closed at 00:00 UTC but wasn't actually logged until a run at
03:50 UTC, comfortably inside MAX_GAP_HOURS_BY_GATE's much more lenient
window (48h for "24h") but a clear sign of degrading cron timeliness that
would eventually tip into a full miss. evaluation_gap_hours (computed for
every non-event-driven, gated entry's MOST RECENT logged row, as wall-clock
`timestamp` minus the row's own `candle_timestamp`) makes that degradation
visible before it becomes one. The flag threshold reuses
candle_schedule.py's own SINGLE_SHOT_TOLERANCE_MINUTES/
MULTI_SHOT_TOLERANCE_MINUTES/DEFAULT_TOLERANCE_MINUTES (via
_expected_max_freshness_gap_minutes) rather than inventing a fourth set of
numbers -- those constants already ARE "how late can a candle's evaluation
run before candle_boundary_due itself would have rejected it," which is
exactly what "was this specific evaluation timely" needs to be judged
against. PEAD/GOLD_SILVER_RATIO_MR (event-driven) and ORDERFLOW_IMBALANCE
(no gate) are excluded for the same reasons the staleness check above
excludes them -- a logged row's candle_timestamp for these doesn't represent
"this period's gate was evaluated," so a gap computed against it wouldn't
mean the same thing.
"""
from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.execution.candle_schedule import (
    DEFAULT_TOLERANCE_MINUTES,
    MULTI_SHOT_TOLERANCE_MINUTES,
    SINGLE_SHOT_TOLERANCE_MINUTES,
    candle_boundary_due,
)
from nero_core.execution.export_site_data import build_stats_export
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
from nero_core.strategies.news_sentiment import STRATEGY_VERSION as NEWS_SENTIMENT_VERSION
from nero_core.strategies.news_sentiment_llm import STRATEGY_VERSION as NEWS_SENTIMENT_LLM_VERSION
from nero_core.strategies.timeframe_calibration import HOURS_PER_TIMEFRAME
from nero_core.truth_ledger.execution_log import (
    DEFAULT_DB_PATH,
    ExecutionLogRow,
    ExecutionMetadataRow,
    latest_news_sentiment_fetch_timestamp,
    list_execution_log,
    list_execution_metadata,
)

NTFY_URL = "https://ntfy.sh/Terminal3039"
NTFY_TIMEOUT_SECONDS = 10
SCHEMA_VERSION = 1
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "health_check.json"

# Explicit thresholds straight from the task's own guidance: 12h -> "at least once
# per day", 24h -> "at least once per 1-2 days" (flag past the lenient upper bound),
# 1week -> "at least once every 7-8 days" (flag past the lenient upper bound).
# "daily" (NEWS_SENTIMENT's own daily_time_due gate, not a candle timeframe at all)
# gets the same once-per-day cadence as "24h" -- same single-shot-per-period
# fragility, so the same generous multi-day tolerance.
MAX_GAP_HOURS_BY_GATE: dict[str, float] = {
    "12h": 24.0,
    "24h": 48.0,
    "1week": 192.0,
    "daily": 48.0,
}
# Fallback for any gate not explicitly tuned above -- none of the currently-wired
# roster needs this (only 12h/24h/1week/daily gates exist today), kept for any
# future timeframe added to the live roster rather than raising.
_FALLBACK_MULTIPLIER = 3.0
_FALLBACK_MIN_HOURS = 6.0

# See this module's own docstring -- PEAD and GOLD_SILVER_RATIO_MR are event-driven
# and both gate on the SAME literal "24h" call in live_scheduler.run_once(), so one
# shared gate-satisfaction computation covers every config of both.
EVENT_DRIVEN_STRATEGY_IDS = frozenset({PEAD_ID, GOLD_SILVER_RATIO_ID})
EVENT_DRIVEN_GATE_TIMEFRAME = "24h"


def _expected_max_gap_hours(gate: str) -> float:
    if gate in MAX_GAP_HOURS_BY_GATE:
        return MAX_GAP_HOURS_BY_GATE[gate]
    hours = HOURS_PER_TIMEFRAME.get(gate)
    if hours is None:
        return _FALLBACK_MIN_HOURS
    return max(hours * _FALLBACK_MULTIPLIER, _FALLBACK_MIN_HOURS)


@dataclass(frozen=True)
class RosterEntry:
    strategy: str
    strategy_version: str
    asset: str
    gate: str | None  # candle_boundary_due timeframe, "daily" for daily_time_due, or
    # None when there is no gate at all (ORDERFLOW_IMBALANCE) -- staleness is not
    # applicable in that case.


def _live_roster() -> list[RosterEntry]:
    """The full live roster this health check reports on -- every strategy
    live_scheduler.run_once() actually wires, built directly from the SAME
    constants run_once() itself iterates (not re-derived or guessed), so this
    can never silently drift out of sync with what's actually running."""
    entries = [
        RosterEntry(c.strategy_id, c.strategy_version, c.asset, c.timeframe) for c in SINGLE_ASSET_CONFIGS
    ]
    pairs_label = "-".join(PAIRS_ASSETS)
    entries.append(RosterEntry(COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, pairs_label, PAIRS_TIMEFRAME))
    entries.append(
        RosterEntry(GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL, GOLD_SILVER_RATIO_TIMEFRAME)
    )
    entries.extend(RosterEntry(PEAD_ID, c.strategy_version, c.ticker, "24h") for c in PEAD_CONFIGS)
    entries.extend(
        RosterEntry(DONCHIAN_TREND_ID, c.strategy_version, c.pair, DONCHIAN_FOREX_TIMEFRAME) for c in DONCHIAN_FOREX_CONFIGS
    )
    entries.extend(RosterEntry(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_VERSION, asset, "daily") for asset in NEWS_SENTIMENT_ASSETS)
    # v2.0.0-llm-claude wired 2026-07-28 IN PARALLEL with v1.0.0 above -- its own roster
    # entry, own staleness check (see the version-scoped latest_news_sentiment_fetch_
    # timestamp call below), so a silent v2-specific outage is caught even while v1
    # keeps succeeding.
    entries.extend(RosterEntry(NEWS_SENTIMENT_ID, NEWS_SENTIMENT_LLM_VERSION, asset, "daily") for asset in NEWS_SENTIMENT_ASSETS)
    entries.extend(RosterEntry(ORDERFLOW_ID, ORDERFLOW_VERSION, asset, None) for asset in ORDERFLOW_BINANCE_SYMBOLS)
    return entries


def _last_gate_satisfied_at(gate: str, metadata_rows: list[ExecutionMetadataRow]) -> datetime | None:
    """Most recent execution_metadata run.start_time for which
    candle_boundary_due(gate, start_time) is True -- i.e. the last time a REAL
    scheduler run actually had a chance to evaluate this gate, independent of
    whether that evaluation found a signal worth logging. This is exactly the
    diagnostic query that found the 2026-07-28 PEAD/24h+1week bug in the first
    place, reused here as the staleness signal for event-driven strategies (see
    this module's own docstring). "daily" isn't a candle_boundary_due timeframe
    (NEWS_SENTIMENT uses daily_time_due instead, and isn't event-driven -- see
    EVENT_DRIVEN_STRATEGY_IDS), so this is only ever called with "24h" today."""
    satisfied = [r.start_time for r in metadata_rows if candle_boundary_due(gate, r.start_time)]
    return max(satisfied) if satisfied else None


def _last_signal_at(rows: list[ExecutionLogRow], strategy: str, strategy_version: str, asset: str) -> datetime | None:
    matching = [
        r.timestamp for r in rows if r.strategy == strategy and r.strategy_version == strategy_version and r.asset == asset
    ]
    return max(matching) if matching else None


def _expected_max_freshness_gap_minutes(gate: str) -> float:
    """Mirrors candle_schedule.candle_boundary_due/daily_time_due's own default
    tolerance selection (see this module's own FRESHNESS GAP docstring note) --
    "24h"/"1week"/"daily" get SINGLE_SHOT_TOLERANCE_MINUTES (one boundary
    opportunity per period), "12h" gets MULTI_SHOT_TOLERANCE_MINUTES (two per
    day), everything else gets DEFAULT_TOLERANCE_MINUTES."""
    if gate in ("24h", "1week", "daily"):
        return float(SINGLE_SHOT_TOLERANCE_MINUTES)
    if gate == "12h":
        return float(MULTI_SHOT_TOLERANCE_MINUTES)
    return float(DEFAULT_TOLERANCE_MINUTES)


def _last_evaluation_gap_hours(
    rows: list[ExecutionLogRow], strategy: str, strategy_version: str, asset: str
) -> float | None:
    """Hours between the MOST RECENTLY logged row's own candle_timestamp (the
    candle that closed) and its wall-clock `timestamp` (when the scheduler run
    that logged it actually happened) -- "how late was the evaluation that DID
    happen," not "did one happen at all" (see this module's own FRESHNESS GAP
    docstring note). None if this (strategy, strategy_version, asset) has never
    logged anything -- the existing staleness check already covers that case.

    BUG FOUND 2026-07-29 (real production data, a status-check request that
    surfaced this while confirming the 24h/12h/daily tolerance fixes' backlog
    catch-up): a backlog catch-up run logs several rows in the SAME instant
    (one per missed candle, all sharing the identical wall-clock `timestamp`)
    -- e.g. SILVER/BREAKOUT_MOMENTUM's 2026-07-28 03:48:34 run logged 4 rows
    (candles 07-22 through 07-25) at that one timestamp. `max(matching,
    key=lambda r: r.timestamp)` doesn't break that tie by candle recency, so
    it silently returned whichever tied row happened to sort first (the
    OLDEST candle in the batch, since `rows` is already ordered by
    candle_timestamp ASC) -- reporting a 143.8h gap instead of the real
    ~71.8h. Breaking ties on candle_timestamp too (the newest candle among
    equally-recent log entries is the one that actually reflects "how fresh
    is the latest evaluation") fixes this without changing any single-row
    case's result."""
    matching = [
        r for r in rows if r.strategy == strategy and r.strategy_version == strategy_version and r.asset == asset
    ]
    if not matching:
        return None
    latest = max(matching, key=lambda r: (r.timestamp, r.candle_timestamp))
    candle_closed_at = datetime.fromtimestamp(latest.candle_timestamp / 1000.0, tz=timezone.utc)
    return (latest.timestamp - candle_closed_at).total_seconds() / 3600.0


@dataclass(frozen=True)
class StrategyHealth:
    strategy: str
    strategy_version: str
    asset: str
    gate: str | None
    last_signal_at: datetime | None
    resolved_trades: int | None
    win_rate: float | None
    open_position: dict[str, Any] | None
    stale: bool
    flag_reason: str | None
    evaluation_gap_hours: float | None = None
    freshness_flagged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "strategy_version": self.strategy_version,
            "asset": self.asset,
            "gate": self.gate,
            "last_signal_at": self.last_signal_at.isoformat() if self.last_signal_at is not None else None,
            "resolved_trades": self.resolved_trades,
            "win_rate": self.win_rate,
            "open_position": self.open_position,
            "stale": self.stale,
            "flag_reason": self.flag_reason,
            "evaluation_gap_hours": self.evaluation_gap_hours,
            "freshness_flagged": self.freshness_flagged,
        }


def _evaluate_entry(
    entry: RosterEntry,
    execution_rows: list[ExecutionLogRow],
    metadata_rows: list[ExecutionMetadataRow],
    stats_by_key: dict[tuple[str, str, str], dict[str, Any]],
    now: datetime,
    db_path: Path = DEFAULT_DB_PATH,
) -> StrategyHealth:
    stats = stats_by_key.get((entry.strategy, entry.strategy_version, entry.asset))
    resolved_trades = stats["resolved_trades"] if stats is not None else None
    win_rate = stats["win_rate"] if stats is not None else None
    open_position = stats["open_position"] if stats is not None else None

    if entry.strategy == NEWS_SENTIMENT_ID:
        # strategy_version-scoped: with v1.0.0 and v2.0.0-llm-claude both wired live,
        # a version-blind lookup would report v1's timestamp as "fresh" for v2's
        # roster entry even if v2 were silently broken. db_path is passed through
        # explicitly -- BUG FOUND while adding this: the previous call site
        # (`latest_news_sentiment_fetch_timestamp(entry.asset)`, pre-dating this
        # NEWS_SENTIMENT_ID branch's strategy_version argument too) never passed
        # db_path at all, so it silently always read execution_log.DEFAULT_DB_PATH
        # regardless of what db_path run_health_check itself was called with --
        # every other roster entry's staleness already correctly used the passed-in
        # db_path via execution_rows/metadata_rows, so NEWS_SENTIMENT was the one
        # inconsistent path. In production this coincided with the real path by
        # chance (nothing had ever called run_health_check with a non-default
        # db_path AND actually asserted on a NEWS_SENTIMENT staleness result), so it
        # was never observably wrong until a test exercised both together.
        last_signal_at = latest_news_sentiment_fetch_timestamp(entry.asset, entry.strategy_version, db_path=db_path)
    else:
        last_signal_at = _last_signal_at(execution_rows, entry.strategy, entry.strategy_version, entry.asset)

    if entry.gate is None:
        # ORDERFLOW_IMBALANCE -- no gate to starve, silence is normal.
        return StrategyHealth(
            entry.strategy, entry.strategy_version, entry.asset, entry.gate, last_signal_at,
            resolved_trades, win_rate, open_position, stale=False, flag_reason=None,
        )

    if entry.strategy in EVENT_DRIVEN_STRATEGY_IDS:
        reference = _last_gate_satisfied_at(EVENT_DRIVEN_GATE_TIMEFRAME, metadata_rows)
        reference_label = "gate last satisfied"
    else:
        reference = last_signal_at
        reference_label = "last signal"

    # FRESHNESS GAP -- see this module's own docstring note. Not applicable to
    # event-driven strategies (a logged row's candle_timestamp doesn't represent
    # "this period's gate was evaluated" for them) or NEWS_SENTIMENT (its rows
    # live in news_sentiment_log, gated by daily_time_due, with no candle at all).
    evaluation_gap_hours: float | None = None
    freshness_flagged = False
    freshness_reason: str | None = None
    if entry.strategy not in EVENT_DRIVEN_STRATEGY_IDS and entry.strategy != NEWS_SENTIMENT_ID:
        evaluation_gap_hours = _last_evaluation_gap_hours(
            execution_rows, entry.strategy, entry.strategy_version, entry.asset
        )
        if evaluation_gap_hours is not None:
            max_freshness_gap_hours = _expected_max_freshness_gap_minutes(entry.gate) / 60.0
            if evaluation_gap_hours > max_freshness_gap_hours:
                freshness_flagged = True
                freshness_reason = (
                    f"most recent evaluation lagged its own candle close by {evaluation_gap_hours:.1f}h "
                    f"(expected within {max_freshness_gap_hours:.1f}h) -- timeliness is degrading even "
                    f"though evaluations are still happening"
                )

    max_gap_hours = _expected_max_gap_hours(entry.gate)
    if reference is None:
        return StrategyHealth(
            entry.strategy, entry.strategy_version, entry.asset, entry.gate, last_signal_at,
            resolved_trades, win_rate, open_position, stale=True,
            flag_reason=f"no {reference_label} ever recorded (expected at least every {max_gap_hours:.0f}h)",
            evaluation_gap_hours=evaluation_gap_hours, freshness_flagged=freshness_flagged,
        )

    gap_hours = (now - reference).total_seconds() / 3600.0
    if gap_hours > max_gap_hours:
        return StrategyHealth(
            entry.strategy, entry.strategy_version, entry.asset, entry.gate, last_signal_at,
            resolved_trades, win_rate, open_position, stale=True,
            flag_reason=f"{reference_label} was {gap_hours:.1f}h ago, expected at least every {max_gap_hours:.0f}h",
            evaluation_gap_hours=evaluation_gap_hours, freshness_flagged=freshness_flagged,
        )

    if freshness_flagged:
        return StrategyHealth(
            entry.strategy, entry.strategy_version, entry.asset, entry.gate, last_signal_at,
            resolved_trades, win_rate, open_position, stale=True, flag_reason=freshness_reason,
            evaluation_gap_hours=evaluation_gap_hours, freshness_flagged=True,
        )

    return StrategyHealth(
        entry.strategy, entry.strategy_version, entry.asset, entry.gate, last_signal_at,
        resolved_trades, win_rate, open_position, stale=False, flag_reason=None,
        evaluation_gap_hours=evaluation_gap_hours, freshness_flagged=False,
    )


def run_health_check(db_path: Path = DEFAULT_DB_PATH, now: datetime | None = None) -> list[StrategyHealth]:
    """Read-only: fetches execution_log/execution_metadata ONCE and evaluates every
    roster entry against them. Never raises on a single entry's own bad data --
    each entry is independently computed from already-fetched, already-validated
    rows, so one strategy's weirdness can't take down the report for the others
    (fail-independent, same principle as run_once()'s own per-config try/except)."""
    now = now or datetime.now(timezone.utc)
    execution_rows = list_execution_log(db_path=db_path)
    metadata_rows = list_execution_metadata(db_path=db_path)
    stats_export = build_stats_export(execution_rows, now=now)
    stats_by_key = {
        (s["strategy"], s["strategy_version"], s["asset"]): s for s in stats_export["strategies"]
    }

    results: list[StrategyHealth] = []
    for entry in _live_roster():
        try:
            results.append(_evaluate_entry(entry, execution_rows, metadata_rows, stats_by_key, now, db_path=db_path))
        except Exception as exc:  # noqa: BLE001 - one entry's own failure must not blank the whole report
            results.append(
                StrategyHealth(
                    entry.strategy, entry.strategy_version, entry.asset, entry.gate, None,
                    None, None, None, stale=True,
                    flag_reason=f"health check itself failed for this entry: {exc.__class__.__name__}: {exc}",
                )
            )
    return results


def build_health_export(results: list[StrategyHealth], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    flagged = [r for r in results if r.stale]
    return {
        "schema_version": SCHEMA_VERSION,
        "last_updated": now.isoformat(),
        "strategies": [r.to_dict() for r in results],
        "flagged_count": len(flagged),
        "flagged_strategies": [f"{r.strategy}:{r.strategy_version}:{r.asset}" for r in flagged],
    }


def write_health_check(
    db_path: Path = DEFAULT_DB_PATH, output_path: Path = OUTPUT_PATH, now: datetime | None = None
) -> dict[str, Any]:
    results = run_health_check(db_path=db_path, now=now)
    export = build_health_export(results, now=now)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8")
    return export


def build_alert_message(export: dict[str, Any]) -> str | None:
    """None means healthy -- no alert needed. Mirrors
    scheduler_heartbeat_alert.build_alert_message's own contract so callers (and
    tests) never have to re-derive the wording."""
    flagged = export["flagged_strategies"]
    if not flagged:
        return None
    names = ", ".join(flagged)
    return f"VATICAN HEALTH CHECK — {len(flagged)} strategy(ies) stale: {names}"


def send_ntfy_alert(message: str, url: str = NTFY_URL, timeout_seconds: int = NTFY_TIMEOUT_SECONDS) -> bool:
    """Best-effort delivery -- never raises. Mirrors notify_ntfy.send_ntfy_notification
    and scheduler_heartbeat_alert.send_ntfy_alert."""
    try:
        response = requests.post(url, data=message.encode("utf-8"), timeout=timeout_seconds)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"ntfy alert failed (non-fatal): {exc.__class__.__name__}: {exc}")
        return False


def main() -> None:
    """Never raises -- a health-check bug must show up in the GitHub Actions log but
    must never fail the workflow step itself, and must never be able to affect the
    live scheduler or the Truth Ledger it only reads from."""
    try:
        export = write_health_check()
        print(
            f"Health check: {len(export['strategies'])} strategies, "
            f"{export['flagged_count']} flagged as stale."
        )
        for row in export["strategies"]:
            if row["stale"]:
                print(f"  STALE: {row['strategy']}:{row['strategy_version']}:{row['asset']} -- {row['flag_reason']}")
        message = build_alert_message(export)
        if message is None:
            print("No stale strategies -- no alert sent.")
            return
        print(f"Sending health-check alert to {NTFY_URL}: {message}")
        send_ntfy_alert(message)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
