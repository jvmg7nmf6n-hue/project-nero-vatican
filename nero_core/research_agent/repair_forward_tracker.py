"""Repair Lab v1, Task 4b: forward-testing tick + PENDING_FORWARD_DATA
resolution -- the "forward testing" half of the two accepted fresh-data
mechanisms (docs/repair_lab_investigation_report.md Task 2). See
nero_core.research_agent.repair_historical_reservation for the other half.

REUSES ORDERFLOW_IMBALANCE's OWN MECHANISM, NOT ITS TABLE: nero_core.
execution.live_scheduler.process_orderflow_imbalance already proves out the
exact shape this needs -- no historical replay (the data genuinely didn't
exist before the attempt was launched, which is what makes it fresh by
construction), state reconstructed from the LAST logged row rather than
rebuilt from a replayable series, one signal per tick. This module reuses
that same pattern via nero_core.truth_ledger.execution_log's own generic,
already-tested insert_execution_log_row/list_execution_log functions -- but
writes to its OWN, completely separate SQLite file (DEFAULT_FORWARD_
TRACKING_DB_PATH, "data/repair_lab_forward_tracking.db"), never the
production truth_ledger.db ORDERFLOW_IMBALANCE and every live strategy
share. This is the architectural isolation Task 7 requires: same tested
plumbing, physically separate storage, and execution_log.py itself neither
imports live_scheduler nor references default_registry, so this reuse
introduces neither.

STATE ENCODING: unlike ORDERFLOW_IMBALANCE (which encodes only direction/
stop_loss as prose inside `reasoning` -- see live_scheduler._reconstruct_
open_position's own docstring on why only those two fields are ever
recoverable), this module encodes the FULL OpenTrade/ExitEvent dataclass as
JSON inside `reasoning` -- robust structural reconstruction, not prose
parsing, since a repair attempt's own entry sizing (ATR/pct stop, R-multiple
or pct target) needs every OpenTrade field back, not just two.

VERDICT COMPUTATION: nothing in this codebase computes a verdict from
ORDERFLOW_IMBALANCE's own accrued execution-log rows today (a real gap the
investigation's Task 2 named explicitly) -- compute_forward_verdict is the
new component that closes it FOR REPAIR LAB specifically: once at least
2*MIN_SAMPLE_SIZE trades have resolved, the accrued trades are split
chronologically (first half = train, second half = test, mirroring this
project's existing 70/30-adjacent convention) and fed through the SAME,
unmodified classify_verdict/bootstrap_mean_r_ci functions the historical
path already uses -- one verdict semantics across both fresh-data methods,
not a second invented scheme."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from nero_core.research_agent.auto_tester import evaluate_exit_for_hypothesis, size_entry_for_hypothesis
from nero_core.research_agent.rule_dsl import compute_indicator_frame, parse_bidirectional_entry_rules, parse_exit_plan, rule_fires_at
from nero_core.strategies.mean_reversion import ExitEvent, MeanReversionParameters, MeanReversionState, OpenTrade
from nero_core.truth_ledger.execution_log import ExecutionLogRow, insert_execution_log_row, list_execution_log
from tools.backtest_statistics import MIN_SAMPLE_SIZE, bootstrap_mean_r_ci, classify_verdict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FORWARD_TRACKING_DB_PATH = REPO_ROOT / "data" / "repair_lab_forward_tracking.db"

# Every forward-tracked attempt's rows share this strategy-name prefix in the
# execution_log's own `strategy` column, so list_execution_log's existing
# strategy filter scopes cleanly to one attempt without any schema change.
FORWARD_STRATEGY_PREFIX = "REPAIR_LAB_ATTEMPT"


def _strategy_key(attempt_id: str, strategy_prefix: str = FORWARD_STRATEGY_PREFIX) -> str:
    return f"{strategy_prefix}:{attempt_id}"


@dataclass(frozen=True)
class ForwardTickResult:
    signal_type: str  # "ENTRY" | "EXIT" | "NO_TRADE"
    trade: OpenTrade | None = None
    exit_event: ExitEvent | None = None


def _reconstruct_open_trade(attempt_id: str, db_path: Path, strategy_prefix: str = FORWARD_STRATEGY_PREFIX) -> OpenTrade | None:
    """Mirrors live_scheduler._reconstruct_open_position's own "read the
    last logged row back, don't rebuild state from a data series that
    doesn't exist" approach -- there is nothing to replay here either (a
    forward-tracked attempt's own history IS its own log). None if the
    attempt has never logged anything, or if its most recent logged signal
    is an EXIT (position already closed)."""
    rows: list[ExecutionLogRow] = list_execution_log(db_path=db_path, strategy=_strategy_key(attempt_id, strategy_prefix))
    if not rows:
        return None
    last = rows[-1]
    if last.signal_type != "ENTRY":
        return None
    return OpenTrade(**json.loads(last.reasoning))


def evaluate_forward_tick(
    attempt_id: str,
    hypothesis: dict,
    recent_candles: pd.DataFrame,
    now: datetime,
    params: MeanReversionParameters | None = None,
    db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH,
    strategy_prefix: str = FORWARD_STRATEGY_PREFIX,
) -> ForwardTickResult:
    """ONE tick: `recent_candles` is enough trailing history (already
    closed candles only -- the caller's responsibility, matching every
    other no-lookahead boundary in this codebase) for indicator warmup; the
    LAST row is evaluated as "now". Reconstructs open-position state from
    this attempt's own log, evaluates exit if a position is open, else
    evaluates entry via the exact same size_entry_for_hypothesis/
    evaluate_exit_for_hypothesis auto_tester.py's own backtest loop uses --
    reused, not reimplemented. Idempotent per (attempt_id, candle): logging
    the same candle twice is a no-op (execution_log's own UNIQUE constraint
    on (asset, strategy, strategy_version, candle_timestamp, signal_type)),
    matching ORDERFLOW_IMBALANCE's own "already processed, don't retry"
    convention.

    `strategy_prefix` (CC-1 directive item 4, added 2026-08-05): defaults to
    FORWARD_STRATEGY_PREFIX ("REPAIR_LAB_ATTEMPT"), so every existing
    Repair Lab caller/test is byte-identical to before. nero_core.
    research_agent.trial (item 4's fresh/non-repair Trial admissions) is the
    one other caller, passing strategy_prefix="TRIAL" against the SAME
    execution_log mechanism and (by default) the SAME db_path -- reusing
    this proven single-tick pattern rather than inventing a second one, per
    docs/investigations/factory_loop_specification.md's own B1
    recommendation. The `attempt_id` parameter name is unchanged (a rename
    would touch every existing call site for a clarity-only gain); for a
    Trial caller it holds that Trial's own trial_id instead of a repair
    attempt_id -- the prefix, not this parameter's name, is what keeps the
    two forward-tracked populations from colliding in execution_log's own
    `strategy` column."""
    params = params or MeanReversionParameters()
    if recent_candles.empty:
        return ForwardTickResult("NO_TRADE")

    frame = compute_indicator_frame(recent_candles)
    if frame.empty:
        return ForwardTickResult("NO_TRADE")

    idx = len(frame) - 1
    candle = frame.iloc[idx]
    candle_time = int(candle["close_time"])
    asset = str(hypothesis.get("asset", ""))
    strategy_key = _strategy_key(attempt_id, strategy_prefix)
    run_id = f"repair-lab-forward-{now.date().isoformat()}"

    # Idempotency, EXIT side (Phase 2 Fix J, docs/investigations/
    # phase2_pending_cleanup_report.md): re-evaluating the IDENTICAL exit
    # tick must be a no-op, matching the ENTRY-side guarantee this
    # function's own docstring already claims. Cannot be caught by
    # insert_execution_log_row's UNIQUE constraint the way a repeat ENTRY
    # is: once an EXIT is logged, _reconstruct_open_trade's "last row is an
    # ENTRY?" check reports no open position, so a repeat call never
    # re-enters the `if open_trade is not None` branch below at all -- it
    # falls through to entry evaluation and can log a brand-new, phantom
    # ENTRY at the SAME candle_timestamp (a different signal_type, so the
    # UNIQUE constraint never sees it as a duplicate). Keying idempotency on
    # "has THIS attempt logged ANY row for this candle_timestamp already"
    # (not "was the last row specifically an ENTRY") closes that gap for
    # both directions at once, before either branch below ever runs.
    already_logged = any(
        r.candle_timestamp == candle_time
        for r in list_execution_log(db_path=db_path, strategy=strategy_key)
    )
    if already_logged:
        return ForwardTickResult("NO_TRADE")

    exit_plan = parse_exit_plan(hypothesis.get("structured_exit_plan"))
    open_trade = _reconstruct_open_trade(attempt_id, db_path, strategy_prefix)
    state = MeanReversionState(equity=params.initial_equity, open_trade=open_trade)

    if open_trade is not None:
        exit_event = evaluate_exit_for_hypothesis(candle, state, params, exit_plan)
        if exit_event is None:
            return ForwardTickResult("NO_TRADE")
        insert_execution_log_row(
            run_id=run_id, strategy=strategy_key, strategy_version="v1", asset=asset, signal_type="EXIT",
            reasoning=json.dumps(asdict(exit_event)), candle_timestamp=candle_time,
            entry_price=None, exit_price=exit_event.exit_price, timestamp=now, db_path=db_path,
        )
        return ForwardTickResult("EXIT", exit_event=exit_event)

    rule, short_rule = parse_bidirectional_entry_rules(hypothesis)
    direction: str | None = None
    if rule_fires_at(frame, idx, rule):
        direction = "LONG"
    elif short_rule is not None and rule_fires_at(frame, idx, short_rule):
        direction = "SHORT"
    if direction is None:
        return ForwardTickResult("NO_TRADE")

    trade = size_entry_for_hypothesis(candle, state, params, exit_plan, direction)
    if trade is None:
        return ForwardTickResult("NO_TRADE")

    inserted = insert_execution_log_row(
        run_id=run_id, strategy=strategy_key, strategy_version="v1", asset=asset, signal_type="ENTRY",
        reasoning=json.dumps(asdict(trade)), candle_timestamp=candle_time,
        entry_price=trade.entry_price, exit_price=None, timestamp=now, db_path=db_path,
    )
    if inserted is None:
        return ForwardTickResult("NO_TRADE")  # already logged this exact candle -- idempotent, not a new signal
    return ForwardTickResult("ENTRY", trade=trade)


def resolved_trade_count(attempt_id: str, db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH, strategy_prefix: str = FORWARD_STRATEGY_PREFIX) -> int:
    rows = list_execution_log(db_path=db_path, strategy=_strategy_key(attempt_id, strategy_prefix))
    return sum(1 for r in rows if r.signal_type == "EXIT")


def compute_forward_verdict(
    attempt_id: str, db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH, min_sample_size: int = MIN_SAMPLE_SIZE,
    strategy_prefix: str = FORWARD_STRATEGY_PREFIX,
) -> dict | None:
    """None (never a fabricated in-progress verdict) until at least
    2*min_sample_size trades have resolved -- the caller reports
    PENDING_FORWARD_DATA in that case. Once enough have accrued, splits
    chronologically into train/test halves and classifies via the SAME
    classify_verdict/bootstrap_mean_r_ci this project's historical path
    already uses -- one verdict semantics, not a second invented one.
    `strategy_prefix`: see evaluate_forward_tick's own docstring -- same
    default, same reuse-not-reinvent reasoning for item 4's Trial caller."""
    rows = list_execution_log(db_path=db_path, strategy=_strategy_key(attempt_id, strategy_prefix))
    exits = [r for r in rows if r.signal_type == "EXIT"]
    if len(exits) < 2 * min_sample_size:
        return None

    r_values = [float(json.loads(r.reasoning)["r_multiple"]) for r in exits]
    mid = len(r_values) // 2
    train_r, test_r = r_values[:mid], r_values[mid:]

    def half_stats(values: list[float]) -> dict:
        n = len(values)
        expectancy = sum(values) / n if n else 0.0
        ci = bootstrap_mean_r_ci(values) if n else None
        return {"trades": n, "expectancy_r": expectancy, "ci": ci}

    train_stats = half_stats(train_r)
    test_stats = half_stats(test_r)
    verdict = classify_verdict(train_stats, test_stats, min_sample_size=min_sample_size)

    def half_to_dict(stats: dict) -> dict:
        return {
            "trades": stats["trades"], "expectancy_r": stats["expectancy_r"],
            "bootstrap_ci": None if stats["ci"] is None else asdict(stats["ci"]),
        }

    return {
        "verdict": verdict,
        "train": half_to_dict(train_stats),
        "test": half_to_dict(test_stats),
        "reason": (
            f"forward-tracked: train N={train_stats['trades']} ExpR={train_stats['expectancy_r']:.3f}; "
            f"test N={test_stats['trades']} ExpR={test_stats['expectancy_r']:.3f} -> {verdict}"
        ),
        "resolved_trade_count": len(exits),
    }
