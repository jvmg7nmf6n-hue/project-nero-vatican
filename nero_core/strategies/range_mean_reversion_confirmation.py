"""RANGE_MEAN_REVERSION confirmation-entry variant (v1.3.0) — RMR Variant Research
Cycle, Stage 1, variant (d) RMR_CONFIRMATION_BTC_1D.

Tests "wait for the turn" vs v1.0.0's immediate band-touch entry:
  LONG: candle t closes below the lower band; candle t+1 closes back ABOVE the lower
  band; ADX < 25 at t+1 -> enter LONG at t+2's OPEN (not close).
  SHORT (mirror): candle t closes above the upper band; candle t+1 closes back BELOW
  the upper band; ADX < 25 at t+1 -> enter SHORT at t+2's OPEN.

Reuses v1.0.0's exit mechanics, state, sizing math, and indicators completely
unchanged (evaluate_exit, RangeMeanReversionState, add_indicators, apply_slippage) —
only entry DETECTION (a 2-closed-candle lookback pattern instead of a single-candle
band breach) and the entry PRICE (the confirmation candle's own open, not the signal
candle's close) differ. Needs its own run_backtest loop because the standard
per-candle loop assumes the decision candle and the entry candle are the same row;
here they are deliberately two candles apart.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import apply_slippage, reset_daily_guard_if_needed
from nero_core.strategies.range_mean_reversion import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    OpenTrade,
    RangeMeanReversionParameters,
    RangeMeanReversionState,
    evaluate_exit,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "range-mean-reversion-v1.3.0-confirmation"

# Same numeric parameters as v1.0.0 — only the entry PATTERN/TIMING differs, which
# isn't representable as a parameter value, so there is genuinely nothing to replace().
CONFIRMATION_PARAMETERS = DEFAULT_PARAMETERS

STRATEGY_DESCRIPTION = (
    "Confirmation-entry variant of RANGE_MEAN_REVERSION v1.0.0: instead of entering "
    "immediately on a band breach, waits for price to close back inside the band on "
    "the NEXT closed candle (with ADX < 25 confirmed at that candle) before entering "
    "at the candle after that one's OPEN. Exit mechanics, state, and sizing are "
    "identical to v1.0.0. Tests 'wait for the turn' vs immediate entry. Both "
    "directions enabled. RMR Variant Research Cycle, Stage 1: BTC/1d."
)


@dataclass(frozen=True)
class ConfirmationEntryEvaluation:
    passed: bool
    direction: str | None
    reasons: tuple[str, ...]


def evaluate_confirmation_entry(
    evaluable: pd.DataFrame,
    i: int,
    state: RangeMeanReversionState,
    params: RangeMeanReversionParameters = CONFIRMATION_PARAMETERS,
) -> ConfirmationEntryEvaluation:
    """Checks candles i-2 (t) and i-1 (t+1) for the confirmation pattern; entry (if
    passed) executes at candle i's (t+2) OPEN — see size_confirmation_entry. Every
    rejection reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")
    if i < 2:
        reasons.append("INSUFFICIENT_LOOKBACK")
        return ConfirmationEntryEvaluation(passed=False, direction=None, reasons=tuple(reasons))

    t = evaluable.iloc[i - 2]
    t1 = evaluable.iloc[i - 1]
    bb_lower_t, bb_upper_t = t.get("bb_lower"), t.get("bb_upper")
    adx_t1 = t1.get("adx")
    if (
        bb_lower_t is None or bb_upper_t is None or adx_t1 is None
        or pd.isna(bb_lower_t) or pd.isna(bb_upper_t) or pd.isna(adx_t1)
    ):
        reasons.append("INDICATORS_NOT_AVAILABLE")
        return ConfirmationEntryEvaluation(passed=False, direction=None, reasons=tuple(reasons))

    close_t, close_t1 = float(t["close"]), float(t1["close"])
    adx_t1 = float(adx_t1)
    direction: str | None = None
    if close_t < float(bb_lower_t) and close_t1 > float(bb_lower_t) and adx_t1 < params.adx_entry_threshold:
        direction = "LONG"
    elif close_t > float(bb_upper_t) and close_t1 < float(bb_upper_t) and adx_t1 < params.adx_entry_threshold:
        direction = "SHORT"

    if direction == "SHORT" and not params.allow_short:
        # RMR Variant Research Cycle, Stage 3: reuses the same allow_short flag
        # v1.1.0-long-only introduced — see range_mean_reversion_long_only_
        # confirmation.py, which stacks this with the confirmation entry pattern.
        reasons.append("SHORT_DISABLED")
        direction = None

    if direction is None and "SHORT_DISABLED" not in reasons:
        reasons.append("NO_CONFIRMATION_PATTERN")

    passed = direction is not None and not reasons
    return ConfirmationEntryEvaluation(passed=passed, direction=direction if passed else None, reasons=tuple(reasons))


def size_confirmation_entry(
    candle: pd.Series,
    state: RangeMeanReversionState,
    params: RangeMeanReversionParameters = CONFIRMATION_PARAMETERS,
    direction: str = "LONG",
) -> OpenTrade | None:
    """Entry price is candle i's OWN OPEN (the confirmation candle), not its close —
    the entire point of 'wait for the turn, then enter at the next open'. Otherwise
    identical fixed-fractional sizing math to range_mean_reversion.size_entry."""
    raw_entry = float(candle["open"])
    atr_value = float(candle["atr"])
    if direction == "LONG":
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
        stop_loss = entry_price - params.atr_stop_multiple * atr_value
    else:  # SHORT
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "sell")
        stop_loss = entry_price + params.atr_stop_multiple * atr_value

    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit <= 0:
        return None

    risk_dollars = state.equity * params.risk_per_trade
    quantity = risk_dollars / risk_per_unit
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * risk_per_unit
    fees = notional * params.fee_bps / 10000.0

    return OpenTrade(
        direction=direction, entry_price=entry_price, stop_loss=stop_loss, quantity=quantity,
        notional=notional, risk_dollars=risk_dollars, entry_fee=fees,
        open_close_time=int(candle["close_time"]), entry_atr=atr_value,
    )


def run_backtest(
    evaluable: pd.DataFrame, params: RangeMeanReversionParameters = CONFIRMATION_PARAMETERS
) -> tuple[list, RangeMeanReversionState]:
    state = RangeMeanReversionState(equity=params.initial_equity)
    closed_trades: list = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_confirmation_entry(evaluable, i, state, params)
        if evaluation.passed:
            trade = size_confirmation_entry(candle, state, params, evaluation.direction)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the confirmation-entry variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(CONFIRMATION_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
