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
    TOO_SLOW,
    UNMEASURABLE,
    FrequencyMeasurement,
    measure_entry_frequency,
)
from nero_core.research_agent.rule_dsl import (
    ExitPlan,
    RuleAmbiguousError,
    StructuredRule,
    compute_indicator_frame,
    evaluate_condition,
    parse_exit_plan,
    parse_structured_rule,
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
    candle: pd.Series, state: MeanReversionState, params: MeanReversionParameters, exit_plan: ExitPlan
) -> OpenTrade | None:
    """LONG-only, ATR stop, R-multiple target, risk-based sizing -- the same
    shape mean_reversion.size_entry uses, generalized over an arbitrary
    structured entry trigger. entry_rsi/entry_ma20/entry_bb_lower/entry_ma200
    are unused filler for this generic path -- evaluate_exit's own logic never
    reads them, only entry_price/stop_loss/target/quantity/entry_fee/
    open_close_time do. Returns None (no trade opened) if the risk/reward
    geometry is invalid (missing/non-positive ATR), same contract as
    mean_reversion.size_entry."""
    atr_value = candle.get("atr14")
    if atr_value is None or pd.isna(atr_value) or atr_value <= 0:
        return None

    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    risk_per_unit = exit_plan.stop_atr_multiple * float(atr_value)
    if risk_per_unit <= 0:
        return None
    stop_loss = entry_price - risk_per_unit
    # Dynamic-target plans (exit_plan.dynamic_target_condition set) never read this
    # field -- _evaluate_exit_for_hypothesis checks the CURRENT candle's own indicator
    # value directly each row instead of a value frozen at entry. NaN, never a guessed
    # number, so an accidental read (there shouldn't be one) can never spuriously
    # compare True against a real high/low.
    target = (
        entry_price + risk_per_unit * exit_plan.target_r_multiple
        if exit_plan.target_r_multiple is not None
        else float("nan")
    )

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
        entry_rsi=0.0, entry_ma20=0.0, entry_bb_lower=0.0, entry_ma200=0.0, entry_atr=float(atr_value),
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
    TARGET checked in that same priority)."""
    if exit_plan.regime_break_condition is not None:
        fires = evaluate_condition(candle, exit_plan.regime_break_condition, None) is True
        state.regime_break_streak = state.regime_break_streak + 1 if fires else 0

    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3_600_000.0
    low = float(candle["low"])
    close = float(candle["close"])

    exit_reason: str | None = None
    raw_exit: float | None = None

    if low <= trade.stop_loss:
        exit_reason, raw_exit = "SL", trade.stop_loss
    elif exit_plan.dynamic_target_condition is not None:
        if evaluate_condition(candle, exit_plan.dynamic_target_condition, None) is True:
            # Deliberate convention match to nero_core.strategies.range_mean_reversion.
            # evaluate_exit (Vatican's own already-live port): a crossing-type exit
            # executes at the candle's own CLOSE, not the compared field's value --
            # matches every other crossing/regime exit's convention in this codebase.
            # The external source's ORIGINAL implementation used the compared field's
            # own value instead; this is a deliberate choice to match Vatican's own
            # established convention, not a re-derivation of that source exactly.
            exit_reason, raw_exit = "TARGET", close
    else:
        high = float(candle["high"])
        if high >= trade.target:
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
    exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
    quantity = trade.quantity
    gross_pnl = (exit_price - trade.entry_price) * quantity
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
    when the plan actually needs it."""
    uses_only_fixed_shape = (
        exit_plan.dynamic_target_condition is None
        and exit_plan.regime_break_condition is None
        and exit_plan.max_holding_hours is not None
    )
    if uses_only_fixed_shape:
        return evaluate_exit
    return lambda candle, state, params: _evaluate_exit_for_hypothesis(candle, state, params, exit_plan)


def run_backtest(
    frame: pd.DataFrame, rule: StructuredRule, exit_plan: ExitPlan, params: MeanReversionParameters
) -> tuple[list, MeanReversionState]:
    """One open position at a time (a new trigger is ignored while a trade is
    open -- matches every existing strategy's mutual-exclusivity convention).
    `frame` must already carry rule_dsl's indicator columns (compute_
    indicator_frame)."""
    state = MeanReversionState(equity=params.initial_equity)
    trades = []
    exit_evaluator = _make_exit_evaluator(exit_plan)
    for i in range(len(frame)):
        candle = frame.iloc[i]
        exit_event = exit_evaluator(candle, state, params)
        if exit_event is not None:
            trades.append(exit_event)
        if state.open_trade is None and rule_fires_at(frame, i, rule):
            trade = _size_entry_for_hypothesis(candle, state, params, exit_plan)
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


def _half_stats(trades: list, frame: pd.DataFrame, rule: StructuredRule, exit_plan: ExitPlan, params: MeanReversionParameters) -> HalfStats:
    n = len(trades)
    expectancy_r = sum(t.r_multiple for t in trades) / n if n else 0.0
    ci = bootstrap_mean_r_ci([t.r_multiple for t in trades]) if n else None

    baseline = None
    if n > 0:
        eligible_mask = _eligible_mask(frame, rule)

        def _size_entry_fn(candle: pd.Series, state: MeanReversionState, p: MeanReversionParameters) -> OpenTrade | None:
            return _size_entry_for_hypothesis(candle, state, p, exit_plan)

        # Same exit rules as the real backtest (_make_exit_evaluator) -- for an
        # old-shape plan this is evaluate_exit itself, unchanged; for a plan using
        # ExitPlan's extended fields, the random baseline must exercise the SAME
        # dynamic-target/regime-break/no-time-cap exit logic or the comparison
        # between real and random expectancy would be measuring two different games.
        baseline = random_entry_baseline_single_asset(
            frame, eligible_mask, params, _size_entry_fn, expectancy_r, n, evaluate_exit_fn=_make_exit_evaluator(exit_plan)
        )
    return HalfStats(trades=n, expectancy_r=expectancy_r, ci=ci, random_baseline=baseline)


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

    gate: FrequencyMeasurement = measure_entry_frequency(candles, hypothesis.get("structured_entry_rule"), generated_at)

    if gate.classification in (TOO_SLOW, UNMEASURABLE):
        review_status = REVIEW_REJECTED_TOO_SLOW if gate.classification == TOO_SLOW else REVIEW_REJECTED_UNMEASURABLE
        return TestResult(
            hypothesis_name, asset, timeframe, VERDICT_SKIPPED, review_status, gate.classification,
            gate.measured_trades_per_year, gate.expected_months_to_30_trades, gate.reason,
            None, None, now.isoformat(),
        )

    try:
        rule = parse_structured_rule(hypothesis.get("structured_entry_rule"))
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

    train_trades, _ = run_backtest(train_frame, rule, exit_plan, params) if not train_frame.empty else ([], None)
    test_trades, _ = run_backtest(test_frame, rule, exit_plan, params) if not test_frame.empty else ([], None)

    train_stats = _half_stats(train_trades, train_frame, rule, exit_plan, params)
    test_stats = _half_stats(test_trades, test_frame, rule, exit_plan, params)

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
    hypothesis: dict, grids: dict[str, pd.DataFrame], now: datetime | None = None
) -> dict[str, TestResult]:
    """Reruns test_hypothesis once per named candle grid (e.g. "native",
    "offset+3h", "offset+6h" -- the exact same offsets tools.
    grid_shift_robustness_audit.py already uses). The PIPELINE is responsible
    for building `grids` (fetching native + resampled hourly candles via
    nero_core.data_sources.candle_resampling.resample_hourly_to_grid, exactly
    as grid_shift_robustness_audit.py's own run_single_asset_config does) --
    this function only reruns the SAME harness against each one, never
    re-deriving the resampling itself."""
    now = now or datetime.now(timezone.utc)
    return {label: test_hypothesis(hypothesis, grid_candles, now) for label, grid_candles in grids.items()}


def persist_test_results(results: list[TestResult], path: Path = DEFAULT_TEST_RESULTS_PATH) -> None:
    append_json_list(path, [r.to_dict() for r in results])


def load_existing_test_results(path: Path = DEFAULT_TEST_RESULTS_PATH) -> list[dict]:
    return read_json_list(path)
