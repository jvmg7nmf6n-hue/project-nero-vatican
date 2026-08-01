"""Task 4 -- Auto Tester. Only ever tests hypotheses the frequency gate (Task
2) classifies FAST or VIABLE -- this module runs that gate as its own first
step, before any harness call, matching Task 2's own "hypothesis generation ke
baad, full harness se pehle" ordering: TOO_SLOW/UNMEASURABLE hypotheses are
recorded as SKIPPED right here and never reach split_chronological/bootstrap_
mean_r_ci/random_entry_baseline_single_asset below.

TRANSLATION TO BACKTESTABLE CODE: reuses nero_core.research_agent.rule_dsl for
BOTH halves of a testable trade definition -- structured_entry_rule (the same
parser/evaluator frequency_gate.py already validated the hypothesis against)
and structured_exit_plan (stop_atr_multiple / target_r_multiple /
max_holding_hours). If either is missing or unparseable, the hypothesis is
UNTESTABLE -- never approximated from the free-text entry_rule/exit_rule/
stop_rule.

EXIT MECHANICS ARE REUSED, NOT REIMPLEMENTED: this project's own "Replay
Machinery Generalization" convention (see nero_core.execution.replay.py's
docstring) already establishes that every strategy's state/exit machinery
defaults to nero_core.strategies.mean_reversion's MeanReversionState/OpenTrade/
evaluate_exit/apply_slippage unless a strategy sets its own -- evaluate_exit's
own stop/target/max-holding-hours logic depends only on OpenTrade's fields
(entry_price, stop_loss, target, quantity, entry_fee, open_close_time), never
on RSI/Bollinger specifics. This module supplies its own `_size_entry_for_
hypothesis` (ATR stop, R-multiple target, risk-based sizing -- the same shape
mean_reversion.size_entry uses) and reuses evaluate_exit/apply_slippage
UNCHANGED.

HARNESS REUSE (never re-derived): tools.backtest_train_test_split.
split_chronological (70/30, chronological, no shuffling), each half then gets
its OWN cold-start indicator warmup (compute_indicator_frame called
separately per half) -- matching that module's own "no information crosses
the boundary in either direction" contract. tools.backtest_statistics.
bootstrap_mean_r_ci (5000 iterations, fixed seed), .random_entry_baseline_
single_asset (target-calibrated random-entry-timing null, 200 runs, fixed
seed) -- since an LLM-authored hypothesis has no separate "regime
precondition" apart from its own trigger, the eligible pool for the random
baseline is every warmup-valid candle, the exact same fallback
COINTEGRATION_PAIRS' own PAIRS_REGIME_CAVEAT already documents for this
situation. .classify_verdict/.MIN_SAMPLE_SIZE for the final SURVIVED /
PROMISING-WATCHLIST / DIED call.

CRITICAL SAFETY: this module writes ONLY to docs/site_data/agent_test_results.
json via nero_core.research_agent.storage (append-only). It imports nothing
from nero_core.execution.live_scheduler or nero_core.strategies.registry --
see test_research_agent_no_auto_wire.py's HARD TEST proving nothing here can
reach the live scheduler config or the strategy registry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from nero_core.research_agent.frequency_gate import (
    FAST,
    FAST_MAX_MONTHS,
    TARGET_RESOLVED_TRADES,
    TOO_SLOW,
    UNMEASURABLE,
    VIABLE,
    VIABLE_MAX_MONTHS,
    FrequencyMeasurement,
    measure_entry_frequency,
)
from nero_core.research_agent.rule_dsl import (
    ExitPlan,
    RuleAmbiguousError,
    StructuredRule,
    compute_indicator_frame,
    evaluate_condition,
    mirror_condition,
    parse_bidirectional_entry_rules,
    parse_exit_plan,
    rule_fires_at,
)
from nero_core.research_agent.storage import append_json_list, read_json_list
from nero_core.strategies.mean_reversion import (
    ExitEvent,
    MeanReversionParameters,
    MeanReversionState,
    OpenTrade,
    apply_slippage,
    evaluate_exit,
)
from tools.backtest_statistics import (
    MIN_SAMPLE_SIZE,
    VERDICT_DIED,
    VERDICT_PROMISING_WATCHLIST,
    VERDICT_SURVIVED,
    BootstrapCI,
    RandomBaselineResult,
    bootstrap_mean_r_ci,
    classify_verdict,
    random_entry_baseline_bidirectional,
    random_entry_baseline_single_asset,
)
from tools.backtest_train_test_split import split_chronological

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_RESULTS_PATH = REPO_ROOT / "docs" / "site_data" / "agent_test_results.json"

VERDICT_UNTESTABLE = "UNTESTABLE"
VERDICT_SKIPPED = "SKIPPED"

REVIEW_PENDING = "pending_human_approval"
REVIEW_DEAD = "dead"
REVIEW_REJECTED_TOO_SLOW = "rejected_too_slow"
REVIEW_REJECTED_UNMEASURABLE = "rejected_unmeasurable"
REVIEW_UNTESTABLE = "untestable"


@dataclass(frozen=True)
class HalfStats:
    trades: int
    expectancy_r: float
    ci: BootstrapCI | None
    random_baseline: RandomBaselineResult | None

    def to_dict(self) -> dict:
        return {
            "trades": self.trades,
            "expectancy_r": self.expectancy_r,
            "bootstrap_ci": None if self.ci is None else asdict(self.ci),
            "random_baseline": None if self.random_baseline is None else asdict(self.random_baseline),
        }


@dataclass(frozen=True)
class TestResult:
    hypothesis_name: str
    asset: str
    timeframe: str
    verdict: str  # SURVIVED | PROMISING-WATCHLIST | DIED | UNTESTABLE | SKIPPED
    review_status: str
    frequency_classification: str  # FAST | VIABLE | TOO_SLOW | UNMEASURABLE
    measured_trades_per_year: float | None
    expected_time_to_30_trades_months: float | None
    reason: str
    train: HalfStats | None
    test: HalfStats | None
    tested_at: str

    def to_dict(self) -> dict:
        return {
            "hypothesis_name": self.hypothesis_name,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "verdict": self.verdict,
            "review_status": self.review_status,
            "frequency_classification": self.frequency_classification,
            "measured_trades_per_year": self.measured_trades_per_year,
            "expected_time_to_30_trades_months": self.expected_time_to_30_trades_months,
            "reason": self.reason,
            "train": None if self.train is None else self.train.to_dict(),
            "test": None if self.test is None else self.test.to_dict(),
            "tested_at": self.tested_at,
        }


def _parse_generated_at(raw: object) -> datetime | None:
    """Returns the parsed, tz-aware datetime, or None if `raw` is missing, not a
    string, or not a valid ISO8601 timestamp. Returning None instead of a
    fallback (e.g. `now()`) is deliberate: generated_at becomes the frequency
    gate's no-lookahead cutoff (measure_entry_frequency's own `generated_at`
    parameter) -- a fabricated fallback would silently WIDEN that cutoff to
    admit every candle up to the current moment, defeating the exact
    lookahead-bias guarantee this project has a hard test for
    (test_research_agent_frequency_gate.py). test_hypothesis rejects a None
    result as UNTESTABLE rather than ever backtesting against a fabricated
    cutoff."""
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _size_entry_for_hypothesis(
    candle: pd.Series, state: MeanReversionState, params: MeanReversionParameters, exit_plan: ExitPlan,
    direction: str = "LONG",
) -> OpenTrade | None:
    """Risk-based sizing -- the same shape mean_reversion.size_entry uses,
    generalized over an arbitrary structured entry trigger AND (added for
    feature/philosophy-hypotheses-dsl-check) an arbitrary stop/target basis.
    entry_rsi/entry_ma20/entry_bb_lower/entry_ma200 are unused filler for this
    generic path -- evaluate_exit's own logic never reads them, only
    entry_price/stop_loss/target/quantity/entry_fee/open_close_time do.

    DIRECTION (feature/short-side-support): `direction` defaults to "LONG" --
    every existing call site (this function was long-only-only before this
    branch) either omits it or passes "LONG" explicitly, so behavior for every
    pre-existing caller is unchanged. A "SHORT" trade mirrors
    nero_core.strategies.range_mean_reversion.size_entry's own already-proven
    convention exactly: entry via apply_slippage(..., "sell") ("selling to
    open"), stop ABOVE entry (entry_price + risk_per_unit, not minus), and a
    target BELOW entry for both the R-multiple and percentage shapes.

    STOP: exit_plan.stop_atr_multiple and exit_plan.stop_pct_of_entry are
    mutually exclusive (parse_exit_plan enforces exactly one) -- risk_per_unit
    is this many ATRs at entry, or this fraction of entry price, respectively
    (a MAGNITUDE either way -- direction only decides which side of entry_price
    it's applied to, never its own sign). Returns None (no trade opened) if the
    risk/reward geometry is invalid (missing/non-positive ATR for the ATR-based
    shape; non-positive risk_per_unit for either shape), same contract as
    mean_reversion.size_entry. Only the ATR-based shape requires atr14 to be
    present on the entry candle -- a stop_pct_of_entry plan can open a trade
    even where atr14 is still NaN, since it never reads that field for sizing
    (entry_atr is still populated when available, purely informational, same
    as every other unused-filler field above).

    TARGET: exactly one of target_r_multiple (a multiple of risk_per_unit,
    whatever its basis), dynamic_target_condition (never read here -- see the
    NaN comment below), or target_pct_of_entry (a fixed fraction of entry
    price, independent of risk_per_unit entirely -- NOT an R-multiple, matching
    a hypothesis that states its target as a flat percentage, not a multiple of
    its own risk)."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy" if direction == "LONG" else "sell")

    atr_value = candle.get("atr14")
    atr_is_valid = atr_value is not None and not pd.isna(atr_value) and atr_value > 0

    if exit_plan.stop_atr_multiple is not None:
        if not atr_is_valid:
            return None
        risk_per_unit = exit_plan.stop_atr_multiple * float(atr_value)
    else:
        risk_per_unit = exit_plan.stop_pct_of_entry * entry_price
    if risk_per_unit <= 0:
        return None
    stop_loss = entry_price - risk_per_unit if direction == "LONG" else entry_price + risk_per_unit

    if exit_plan.target_r_multiple is not None:
        target = (
            entry_price + risk_per_unit * exit_plan.target_r_multiple
            if direction == "LONG" else entry_price - risk_per_unit * exit_plan.target_r_multiple
        )
    elif exit_plan.target_pct_of_entry is not None:
        target = (
            entry_price * (1.0 + exit_plan.target_pct_of_entry)
            if direction == "LONG" else entry_price * (1.0 - exit_plan.target_pct_of_entry)
        )
    else:
        # dynamic_target_condition set -- never read here. _evaluate_exit_for_hypothesis
        # checks the CURRENT candle's own indicator value directly each row instead of a
        # value frozen at entry. NaN, never a guessed number, so an accidental read
        # (there shouldn't be one) can never spuriously compare True against a real high/low.
        target = float("nan")

    risk_dollars = state.equity * params.risk_per_trade
    quantity = risk_dollars / risk_per_unit
    notional = quantity * entry_price
    max_notional = state.equity * params.max_notional_pct
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * risk_per_unit
    entry_fee = notional * params.fee_bps / 10000.0

    return OpenTrade(
        entry_price=entry_price, stop_loss=stop_loss, target=target, quantity=quantity,
        notional=notional, risk_dollars=risk_dollars, entry_fee=entry_fee,
        open_close_time=int(candle["close_time"]),
        entry_rsi=0.0, entry_ma20=0.0, entry_bb_lower=0.0, entry_ma200=0.0,
        entry_atr=float(atr_value) if atr_is_valid else float("nan"),
        direction=direction,
    )


def _evaluate_exit_for_hypothesis(
    candle: pd.Series, state: MeanReversionState, params: MeanReversionParameters, exit_plan: ExitPlan
) -> ExitEvent | None:
    """Generalizes mean_reversion.evaluate_exit to support ExitPlan's optional
    dynamic-target and regime-break-hysteresis shapes (see ExitPlan's own
    docstring). Only ever called for a plan using at least one of those --
    _make_exit_evaluator returns evaluate_exit ITSELF, unchanged, for every
    old-shape plan (see that function), so this never runs for one.

    state.regime_break_streak is updated on EVERY call, whether or not a trade
    is open -- matching nero_core.strategies.range_mean_reversion.evaluate_exit's
    own identical convention (consecutive_high_adx_bars) for the same strategy
    family this exit shape was built for: the streak must reflect actual
    consecutive closed candles, not just ones a trade happened to be open for.

    Priority when multiple conditions fire on the same candle: STOP, then
    TARGET (dynamic or fixed), then REGIME_BREAK, then TIME -- identical
    ordering to both evaluate_exit's own (STOP always wins a same-candle tie)
    and range_mean_reversion.evaluate_exit's (STOP, REGIME_BREAK, REVERSION_
    TARGET checked in that same priority).

    DIRECTION (feature/short-side-support): `trade.direction` defaults to
    "LONG" (see mean_reversion.OpenTrade), so every branch below reduces to
    its pre-existing long-only behavior for a LONG trade -- unchanged, not
    merely equivalent. A SHORT trade mirrors every comparison exactly the way
    nero_core.strategies.range_mean_reversion.evaluate_exit's own already-
    proven SHORT branch does: stop hit on `high >=` (not `low <=`), fixed
    target hit on `low <=` (not `high >=`), exit slippage "buy" (not "sell"),
    gross_pnl = (entry - exit) * quantity (not (exit - entry) * quantity).
    regime_break_condition is DELIBERATELY NEVER mirrored -- it describes a
    market-regime observation (e.g. "ADX >= 28"), not a price-vs-entry
    relationship, so it fires identically for both directions (confirmed
    directly against range_mean_reversion.evaluate_exit, which checks its own
    regime-break condition identically for LONG and SHORT). dynamic_target_
    condition IS mirrored (rule_dsl.mirror_condition) for a SHORT trade -- a
    condition authored as "close >= ma20" (LONG: target on the way up) means
    "close <= ma20" (SHORT: target on the way down) for the opposite
    direction, the same field/threshold, only the comparison flipped -- this
    is why ExitPlan needs no second, separately-authored condition field for
    the short side (see rule_dsl.mirror_condition's own docstring)."""
    if exit_plan.regime_break_condition is not None:
        fires = evaluate_condition(candle, exit_plan.regime_break_condition, None) is True
        state.regime_break_streak = state.regime_break_streak + 1 if fires else 0

    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3_600_000.0
    low = float(candle["low"])
    high = float(candle["high"])
    close = float(candle["close"])
    is_long = trade.direction == "LONG"

    exit_reason: str | None = None
    raw_exit: float | None = None

    stop_hit = low <= trade.stop_loss if is_long else high >= trade.stop_loss
    if stop_hit:
        exit_reason, raw_exit = "SL", trade.stop_loss
    elif exit_plan.dynamic_target_condition is not None:
        condition = exit_plan.dynamic_target_condition if is_long else mirror_condition(exit_plan.dynamic_target_condition)
        if evaluate_condition(candle, condition, None) is True:
            # Deliberate convention match to nero_core.strategies.range_mean_reversion.
            # evaluate_exit (Vatican's own already-live port): a crossing-type exit
            # executes at the candle's own CLOSE, not the compared field's value --
            # matches every other crossing/regime exit's convention in this codebase.
            # The external source's ORIGINAL implementation used the compared field's
            # own value instead; this is a deliberate choice to match Vatican's own
            # established convention, not a re-derivation of that source exactly.
            exit_reason, raw_exit = "TARGET", close
    else:
        target_hit = high >= trade.target if is_long else low <= trade.target
        if target_hit:
            exit_reason, raw_exit = "TARGET", trade.target

    if (
        exit_reason is None
        and exit_plan.regime_break_condition is not None
        and state.regime_break_streak >= exit_plan.regime_break_consecutive_bars
    ):
        exit_reason, raw_exit = "REGIME_BREAK", close

    if exit_reason is None and exit_plan.max_holding_hours is not None and hours_held >= exit_plan.max_holding_hours:
        exit_reason, raw_exit = "TIME", close

    if exit_reason is None:
        return None

    # Accounting deliberately duplicated from mean_reversion.evaluate_exit rather than
    # factored into a shared helper -- keeps this project's live exit machinery
    # (evaluate_exit itself) completely untouched by this research-agent-only
    # extension; see ExitPlan's own docstring / this branch's design notes.
    quantity = trade.quantity
    if is_long:
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
        gross_pnl = (exit_price - trade.entry_price) * quantity
    else:  # SHORT: closing = buying back
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "buy")
        gross_pnl = (trade.entry_price - exit_price) * quantity
    exit_fee = exit_price * quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r = state.daily_r + r_multiple
    state.open_trade = None
    state.regime_break_streak = 0

    return ExitEvent(
        exit_reason=exit_reason, exit_price=exit_price, gross_pnl=gross_pnl, fees=total_fees,
        net_pnl=net_pnl, r_multiple=r_multiple, holding_hours=hours_held, equity_after=equity_after,
        exit_close_time=candle_time,
    )


def _make_exit_evaluator(
    exit_plan: ExitPlan,
) -> Callable[[pd.Series, MeanReversionState, MeanReversionParameters], ExitEvent | None]:
    """Returns evaluate_exit ITSELF (not a reimplementation -- the literal same
    function object) for a plan using none of ExitPlan's extended fields, so
    every existing fixed-shape hypothesis's behavior is byte-identical to
    before this extension existed. Only returns _evaluate_exit_for_hypothesis
    when the plan actually needs it.

    stop_pct_of_entry/target_pct_of_entry (feature/philosophy-hypotheses-dsl-check)
    deliberately do NOT appear in this routing check: evaluate_exit itself only
    ever reads OpenTrade.stop_loss/.target as already-computed PRICE LEVELS (see
    mean_reversion.evaluate_exit) -- it has no idea, and no need to know, whether
    _size_entry_for_hypothesis derived those levels from an ATR multiple or a
    fixed percentage of entry price. A percentage-shape plan with a real
    max_holding_hours and no dynamic target/regime break is exactly as eligible
    for evaluate_exit ITSELF as the original ATR-shape plan is -- proven directly
    in test_research_agent_exitplan_percentage_shape.py, not just asserted by
    construction."""
    uses_only_fixed_shape = (
        exit_plan.dynamic_target_condition is None
        and exit_plan.regime_break_condition is None
        and exit_plan.max_holding_hours is not None
    )
    if uses_only_fixed_shape:
        return evaluate_exit
    return lambda candle, state, params: _evaluate_exit_for_hypothesis(candle, state, params, exit_plan)


def run_backtest(
    frame: pd.DataFrame, rule: StructuredRule, exit_plan: ExitPlan, params: MeanReversionParameters,
    short_rule: StructuredRule | None = None,
) -> tuple[list, MeanReversionState]:
    """One open position at a time (a new trigger is ignored while a trade is
    open -- matches every existing strategy's mutual-exclusivity convention).
    `frame` must already carry rule_dsl's indicator columns (compute_
    indicator_frame).

    `short_rule` (feature/short-side-support) defaults to None -- every
    pre-existing call site omits it, so `rule_fires_at(frame, i, rule)` alone
    still decides every entry exactly as before this parameter existed. When
    present, `rule` is checked FIRST (opens LONG) and `short_rule` only if
    `rule` didn't fire this candle (opens SHORT) -- mutually exclusive,
    mirroring range_mean_reversion.evaluate_entry's own "elif close >
    bb_upper: direction = SHORT" long-checked-first convention. For
    EXT_ADX_RANGE's own rule shape (long iff close < bb_lower, short iff
    close > bb_upper, under a shared ADX gate) the two conditions are
    mutually exclusive by construction anyway, so this priority never
    actually has to break a tie in practice -- documented as a real
    convention regardless, for any future rule pair where it could."""
    state = MeanReversionState(equity=params.initial_equity)
    trades = []
    exit_evaluator = _make_exit_evaluator(exit_plan)
    for i in range(len(frame)):
        candle = frame.iloc[i]
        exit_event = exit_evaluator(candle, state, params)
        if exit_event is not None:
            trades.append(exit_event)
        if state.open_trade is None:
            if rule_fires_at(frame, i, rule):
                trade = _size_entry_for_hypothesis(candle, state, params, exit_plan, direction="LONG")
                if trade is not None:
                    state.open_trade = trade
            elif short_rule is not None and rule_fires_at(frame, i, short_rule):
                trade = _size_entry_for_hypothesis(candle, state, params, exit_plan, direction="SHORT")
                if trade is not None:
                    state.open_trade = trade
    return trades, state


def _eligible_mask(frame: pd.DataFrame, rule: StructuredRule) -> pd.Series:
    """Every row where every field the rule reads is past its own indicator
    warmup. An LLM-authored hypothesis has no separate "regime precondition"
    distinct from its own entry trigger, so (matching COINTEGRATION_PAIRS' own
    PAIRS_REGIME_CAVEAT in tools.backtest_statistics for exactly this
    situation) the eligible pool for the random-entry-timing baseline is every
    warmup-valid candle, not a narrower regime filter that doesn't exist here."""
    mask = pd.Series(True, index=frame.index)
    for condition in rule.conditions:
        mask &= frame[condition.field].notna()
    return mask


def _half_stats(
    trades: list, frame: pd.DataFrame, rule: StructuredRule, exit_plan: ExitPlan, params: MeanReversionParameters,
    short_rule: StructuredRule | None = None,
) -> HalfStats:
    """`short_rule` (feature/short-side-support) defaults to None -- every
    pre-existing call site omits it, so this function's body takes the exact
    same random_entry_baseline_single_asset (long-only) branch it always has.
    Only when short_rule is given does this switch to tools.backtest_
    statistics.random_entry_baseline_bidirectional -- already built, already
    tested, already in production use for FVG_REVERSION (see that module's
    own docstring) -- reused here unmodified, not reimplemented."""
    n = len(trades)
    expectancy_r = sum(t.r_multiple for t in trades) / n if n else 0.0
    ci = bootstrap_mean_r_ci([t.r_multiple for t in trades]) if n else None

    baseline = None
    if n > 0:
        # Same exit rules as the real backtest (_make_exit_evaluator) -- for an
        # old-shape plan this is evaluate_exit itself, unchanged; for a plan using
        # ExitPlan's extended fields, the random baseline must exercise the SAME
        # dynamic-target/regime-break/no-time-cap exit logic or the comparison
        # between real and random expectancy would be measuring two different games.
        exit_evaluator = _make_exit_evaluator(exit_plan)

        if short_rule is None:
            eligible_mask = _eligible_mask(frame, rule)

            def _size_entry_fn(candle: pd.Series, state: MeanReversionState, p: MeanReversionParameters) -> OpenTrade | None:
                return _size_entry_for_hypothesis(candle, state, p, exit_plan)

            baseline = random_entry_baseline_single_asset(
                frame, eligible_mask, params, _size_entry_fn, expectancy_r, n, evaluate_exit_fn=exit_evaluator
            )
        else:
            long_eligible_mask = _eligible_mask(frame, rule)
            short_eligible_mask = _eligible_mask(frame, short_rule)

            def _bidirectional_size_entry_fn(
                candle: pd.Series, state: MeanReversionState, p: MeanReversionParameters, direction: str
            ) -> OpenTrade | None:
                return _size_entry_for_hypothesis(candle, state, p, exit_plan, direction)

            baseline = random_entry_baseline_bidirectional(
                frame, long_eligible_mask, short_eligible_mask, params, _bidirectional_size_entry_fn,
                exit_evaluator, expectancy_r, n,
            )
    return HalfStats(trades=n, expectancy_r=expectancy_r, ci=ci, random_baseline=baseline)


def _measure_frequency_for_hypothesis(candles: pd.DataFrame, hypothesis: dict, generated_at: datetime) -> FrequencyMeasurement:
    """Combines frequency_gate.measure_entry_frequency across BOTH of a
    hypothesis's entry rules when it's bidirectional (feature/short-side-
    support) -- frequency_gate.py itself needs ZERO changes for this: every
    constant this function re-derives against (FAST_MAX_MONTHS,
    VIABLE_MAX_MONTHS, TARGET_RESOLVED_TRADES) is already public on that
    module, reused directly, never copied or redefined.

    LONG-ONLY (no `structured_entry_rule_short` key -- every hypothesis
    before this branch, and the overwhelming majority after it): calls
    measure_entry_frequency exactly ONCE, on the long rule alone, and returns
    that result COMPLETELY UNCHANGED -- the literal same measurement this
    function always produced, not a new object with merely-equal values.

    BIDIRECTIONAL: also measures the short rule, and if BOTH sides are
    measurable, combines their trigger counts (mutually exclusive by
    construction for every rule pair this branch was built against --
    EXT_ADX_RANGE's own "long iff close < bb_lower, short iff close > bb_
    upper" under one shared ADX gate can never fire both on the same candle)
    over the SAME eligible span (both measurements share the same candles/
    cutoff, so span_days is identical) and reclassifies from the combined
    rate. If EITHER side comes back UNMEASURABLE, the combined result is
    UNMEASURABLE -- a rate this function can't trust on one side isn't
    trustworthy combined either."""
    long_measurement = measure_entry_frequency(candles, hypothesis.get("structured_entry_rule"), generated_at)
    short_rule_raw = hypothesis.get("structured_entry_rule_short")
    if short_rule_raw is None:
        return long_measurement

    short_measurement = measure_entry_frequency(candles, short_rule_raw, generated_at)
    combined_triggers = long_measurement.triggers_counted + short_measurement.triggers_counted

    if long_measurement.classification == UNMEASURABLE or short_measurement.classification == UNMEASURABLE:
        return FrequencyMeasurement(
            UNMEASURABLE, None, None, combined_triggers, long_measurement.eligible_candle_count, None,
            f"Bidirectional hypothesis -- long side: {long_measurement.reason} | "
            f"short side: {short_measurement.reason} -- combined measurement is UNMEASURABLE because "
            f"at least one side is.",
        )

    span_days = long_measurement.span_days
    if span_days is None or span_days <= 0:
        return FrequencyMeasurement(
            UNMEASURABLE, None, None, combined_triggers, long_measurement.eligible_candle_count, span_days,
            "Zero or negative time span across eligible (pre-cutoff) candles -- cannot annualize a combined rate.",
        )

    trades_per_year = combined_triggers / (span_days / 365.25)
    if trades_per_year <= 0:
        return FrequencyMeasurement(
            TOO_SLOW, trades_per_year, None, combined_triggers, long_measurement.eligible_candle_count, span_days,
            f"Bidirectional: 0 combined triggers (long + short) over {span_days:.0f} eligible days -- "
            f"neither side ever fired.",
        )

    months_to_target = (TARGET_RESOLVED_TRADES / trades_per_year) * 12.0
    if months_to_target <= FAST_MAX_MONTHS:
        classification = FAST
    elif months_to_target <= VIABLE_MAX_MONTHS:
        classification = VIABLE
    else:
        classification = TOO_SLOW

    reason = (
        f"Bidirectional: long {long_measurement.triggers_counted} trigger(s) + short "
        f"{short_measurement.triggers_counted} trigger(s) = {combined_triggers} combined over "
        f"{span_days:.0f} eligible days ({trades_per_year:.2f} trades/year) -> ~{months_to_target:.1f} "
        f"months to {TARGET_RESOLVED_TRADES} resolved trades -> {classification}."
    )
    return FrequencyMeasurement(
        classification, trades_per_year, months_to_target, combined_triggers,
        long_measurement.eligible_candle_count, span_days, reason,
    )


def test_hypothesis(
    hypothesis: dict,
    candles: pd.DataFrame,
    now: datetime | None = None,
    backtest_params: MeanReversionParameters | None = None,
) -> TestResult:
    """`candles` is the FULL available history for hypothesis["asset"]/
    ["timeframe"] (close_time epoch ms + close/high/low, volume optional) --
    NOT pre-filtered by the caller; the frequency gate enforces its own
    lookahead cutoff internally (see frequency_gate.py)."""
    now = now or datetime.now(timezone.utc)
    hypothesis_name = str(hypothesis.get("hypothesis_name", ""))
    asset = str(hypothesis.get("asset", ""))
    timeframe = str(hypothesis.get("timeframe", ""))
    raw_generated_at = hypothesis.get("generated_at")
    generated_at = _parse_generated_at(raw_generated_at)

    if generated_at is None:
        # Reject rather than default to now() -- see _parse_generated_at's own
        # docstring. A missing/malformed generated_at must never silently
        # become the most permissive possible lookahead cutoff.
        return TestResult(
            hypothesis_name, asset, timeframe, VERDICT_UNTESTABLE, REVIEW_UNTESTABLE, UNMEASURABLE,
            None, None,
            f"generated_at missing or unparseable ({raw_generated_at!r}) -- rejected rather than "
            f"defaulting to now(), which would silently widen the frequency gate's no-lookahead cutoff",
            None, None, now.isoformat(),
        )

    gate: FrequencyMeasurement = _measure_frequency_for_hypothesis(candles, hypothesis, generated_at)

    if gate.classification in (TOO_SLOW, UNMEASURABLE):
        review_status = REVIEW_REJECTED_TOO_SLOW if gate.classification == TOO_SLOW else REVIEW_REJECTED_UNMEASURABLE
        return TestResult(
            hypothesis_name, asset, timeframe, VERDICT_SKIPPED, review_status, gate.classification,
            gate.measured_trades_per_year, gate.expected_months_to_30_trades, gate.reason,
            None, None, now.isoformat(),
        )

    try:
        rule, short_rule = parse_bidirectional_entry_rules(hypothesis)
        exit_plan = parse_exit_plan(hypothesis.get("structured_exit_plan"))
    except RuleAmbiguousError as exc:
        return TestResult(
            hypothesis_name, asset, timeframe, VERDICT_UNTESTABLE, REVIEW_UNTESTABLE, gate.classification,
            gate.measured_trades_per_year, gate.expected_months_to_30_trades,
            f"entry_rule/structured_exit_plan not machine-checkable: {exc}",
            None, None, now.isoformat(),
        )

    # max_holding_hours always comes from the hypothesis's own exit_plan, never a caller
    # override -- every other knob (equity, risk, fees, slippage) takes the caller's
    # backtest_params if given, else this project's own MeanReversionParameters defaults.
    # exit_plan.max_holding_hours may be None ("no time-based exit" -- see ExitPlan's own
    # docstring); passed through literally, NEVER substituted with base's own default --
    # doing so would silently reintroduce a time cap the hypothesis deliberately has none
    # of. This is safe to pass through as-is: params.max_holding_hours is only ever
    # consulted by mean_reversion.evaluate_exit's own TIME check, and
    # _make_exit_evaluator only ever routes to evaluate_exit when exit_plan.
    # max_holding_hours is NOT None (see that function) -- so a None here is
    # provably never read.
    base = backtest_params or MeanReversionParameters()
    params = MeanReversionParameters(
        initial_equity=base.initial_equity, risk_per_trade=base.risk_per_trade,
        fee_bps=base.fee_bps, slippage_bps=base.slippage_bps, max_notional_pct=base.max_notional_pct,
        max_holding_hours=exit_plan.max_holding_hours,
    )

    train_raw, test_raw = split_chronological(candles)
    train_frame = compute_indicator_frame(train_raw) if not train_raw.empty else train_raw
    test_frame = compute_indicator_frame(test_raw) if not test_raw.empty else test_raw

    train_trades, _ = run_backtest(train_frame, rule, exit_plan, params, short_rule) if not train_frame.empty else ([], None)
    test_trades, _ = run_backtest(test_frame, rule, exit_plan, params, short_rule) if not test_frame.empty else ([], None)

    train_stats = _half_stats(train_trades, train_frame, rule, exit_plan, params, short_rule)
    test_stats = _half_stats(test_trades, test_frame, rule, exit_plan, params, short_rule)

    verdict = classify_verdict(
        {"expectancy_r": train_stats.expectancy_r, "trades": train_stats.trades, "ci": train_stats.ci},
        {"expectancy_r": test_stats.expectancy_r, "trades": test_stats.trades, "ci": test_stats.ci},
        min_sample_size=MIN_SAMPLE_SIZE,
    )
    review_status = REVIEW_PENDING if verdict in (VERDICT_SURVIVED, VERDICT_PROMISING_WATCHLIST) else REVIEW_DEAD

    reason = (
        f"train: N={train_stats.trades} ExpR={train_stats.expectancy_r:.3f}; "
        f"test: N={test_stats.trades} ExpR={test_stats.expectancy_r:.3f} -> {verdict}"
    )

    return TestResult(
        hypothesis_name, asset, timeframe, verdict, review_status, gate.classification,
        gate.measured_trades_per_year, gate.expected_months_to_30_trades, reason,
        train_stats, test_stats, now.isoformat(),
    )


def run_grid_shift_check(
    hypothesis: dict,
    grids: dict[str, pd.DataFrame],
    now: datetime | None = None,
    backtest_params: MeanReversionParameters | None = None,
) -> dict[str, TestResult]:
    """Reruns test_hypothesis once per named candle grid (e.g. "native",
    "offset+3h", "offset+6h" -- the exact same offsets tools.
    grid_shift_robustness_audit.py already uses). The PIPELINE is responsible
    for building `grids` (fetching native + resampled hourly candles via
    nero_core.data_sources.candle_resampling.resample_hourly_to_grid, exactly
    as grid_shift_robustness_audit.py's own run_single_asset_config does) --
    this function only reruns the SAME harness against each one, never
    re-deriving the resampling itself.

    `backtest_params` (added for feature/external-candidates-formal-test,
    e.g. a forex-specific fee_bps distinct from the crypto default) is passed
    straight through to every grid's own test_hypothesis call, unchanged --
    closing a latent inconsistency test_hypothesis's own custom-cost support
    already had no companion for here: omitting this parameter (the default,
    None) is byte-for-byte identical to this function's behavior before this
    parameter existed, since test_hypothesis's own default is also None."""
    now = now or datetime.now(timezone.utc)
    return {
        label: test_hypothesis(hypothesis, grid_candles, now, backtest_params=backtest_params)
        for label, grid_candles in grids.items()
    }


def persist_test_results(results: list[TestResult], path: Path = DEFAULT_TEST_RESULTS_PATH) -> None:
    append_json_list(path, [r.to_dict() for r in results])


def load_existing_test_results(path: Path = DEFAULT_TEST_RESULTS_PATH) -> list[dict]:
    return read_json_list(path)


# Public re-exports (feature/repair-lab-v1): nero_core.research_agent.repair_
# forward_tracker's own per-tick evaluation needs the EXACT same generic
# entry-sizing/exit-evaluation logic this module's own run_backtest loop
# uses -- reused via alias, not reimplemented or duplicated. _evaluate_exit_
# for_hypothesis is a strict superset of evaluate_exit's own behavior (its
# dynamic-target/regime-break branches are no-ops when an ExitPlan doesn't
# use those fields -- see its own docstring), so it is safe to call
# unconditionally here, unlike _make_exit_evaluator's own byte-identity-
# preserving dispatch (which exists only to keep every historical, already-
# recorded backtest result reproducible -- not a concern for brand-new
# forward-tracking code with no history to preserve).
size_entry_for_hypothesis = _size_entry_for_hypothesis
evaluate_exit_for_hypothesis = _evaluate_exit_for_hypothesis
