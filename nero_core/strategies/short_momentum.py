"""SHORT_MOMENTUM — mirror image of BREAKOUT_MOMENTUM on the short side.

ARCHITECTURE NOTE: every other strategy in this codebase is long-only and shares one
hardcoded exit function — tools.backtest_compare.run_backtest imports
nero_core.strategies.mean_reversion.evaluate_exit directly (not via VariantSpec), and
that function's stop/target math (stop below entry, target above, PnL = (exit-entry)*
qty) is long-only by construction. A short strategy cannot be correctly evaluated by
that shared function — its stop is ABOVE entry and target BELOW, and PnL must invert.
Rather than making the shared long-only exit function branch on direction (which would
touch every existing registered strategy), SHORT_MOMENTUM gets its own
evaluate_exit_short and its own dedicated backtest loop (run_short_backtest), following
the same self-contained pattern already used for COINTEGRATION_PAIRS. It still reuses
MeanReversionState, apply_slippage, atr, rsi, and reset_daily_guard_if_needed from
mean_reversion.py — those are direction-agnostic.

Paper-SHORT only: this system is otherwise long-only paper trading (CLAUDE.md hard
rule 2 — no real exchange execution either way). Modeling a short's PnL in a paper
ledger is not a real order and carries no execution risk; it is simulated exactly like
every other paper trade in this system, just with inverted price arithmetic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import (
    MeanReversionState,
    apply_slippage,
    atr,
    reset_daily_guard_if_needed,
    rsi,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "SHORT_MOMENTUM"
STRATEGY_VERSION = "short-momentum-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Paper-short mirror of BREAKOUT_MOMENTUM breakout-momentum-v1.0.0: close breaks "
    "BELOW the lowest low of the prior 20 candles (excluding the current candle), "
    "close < MA200, RSI <= 50, fixed 1.25R target below entry, 1.2x ATR stop above "
    "entry, timeframe-aware max holding, mirrored stop-priority tie-break (if a "
    "candle's range hits both stop and target, the stop — the worse outcome for this "
    "position — is still assumed to have happened first). PnL accounting is inverted: "
    "profit when price falls. This is a paper-only short simulation; the system is "
    "otherwise long-only (see this module's docstring)."
)


@dataclass(frozen=True)
class ShortMomentumParameters:
    rsi_period: int = 14
    rsi_momentum_max: float = 50.0
    breakdown_lookback: int = 20
    ma200_period: int = 200
    atr_period: int = 14
    atr_stop_multiple: float = 1.2
    reward_multiple: float = 1.25
    # 1h-reference default — see nero_core.strategies.timeframe_calibration.
    # build_calibrated_params for the per-timeframe re-derivation any real backtest run
    # must use instead of this raw value.
    max_holding_hours: int = 24
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = ShortMomentumParameters()


@dataclass
class OpenTrade:
    entry_price: float
    stop_loss: float  # ABOVE entry_price
    target: float  # BELOW entry_price
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_rsi: float
    entry_ma200: float
    entry_atr: float
    entry_breakdown_low: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    rsi: float
    ma200: float
    atr: float
    breakdown_low: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float


def add_indicators(candles: pd.DataFrame, params: ShortMomentumParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach MA200/RSI/ATR/breakdown-low to closed candles. `breakdown_low` uses
    shift(1) before the rolling min, so a candle's own low never counts toward its own
    breakdown threshold — no lookahead: row i only ever sees lows from rows < i.
    Mirrors BREAKOUT_MOMENTUM's `breakout_high` exactly, using low/min instead of
    high/max."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["ma200"] = close.rolling(params.ma200_period).mean()
    frame["rsi"] = rsi(close, params.rsi_period)
    frame["atr"] = atr(frame, params.atr_period)
    frame["breakdown_low"] = frame["low"].shift(1).rolling(params.breakdown_lookback).min()
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: ShortMomentumParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Evaluate the short-breakdown-momentum rule set against one closed candle. Every
    rejection reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    breakdown_low = candle.get("breakdown_low")
    if pd.isna(breakdown_low) or float(candle["close"]) >= float(breakdown_low):
        reasons.append("CLOSE_NOT_BELOW_BREAKDOWN_LOW")
    if float(candle["close"]) >= float(candle["ma200"]):
        reasons.append("CLOSE_NOT_BELOW_MA200")
    if float(candle["rsi"]) > params.rsi_momentum_max:
        reasons.append("RSI_NOT_MOMENTUM_SUPPORTIVE")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=float(candle["close"]),
        rsi=float(candle["rsi"]),
        ma200=float(candle["ma200"]),
        atr=float(candle["atr"]),
        breakdown_low=None if pd.isna(breakdown_low) else float(breakdown_low),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: ShortMomentumParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional position sizing for the short leg: stop = entry + 1.2x ATR
    (above), target = entry - 1.25x risk-per-unit (below). Returns None if the
    risk/reward geometry is invalid — callers should only invoke this after
    `evaluate_entry` has passed."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "sell")  # opening a short: selling to open
    stop_loss = entry_price + params.atr_stop_multiple * float(candle["atr"])
    risk_per_unit = stop_loss - entry_price
    if risk_per_unit <= 0:
        return None

    target = entry_price - params.reward_multiple * risk_per_unit
    reward_per_unit = entry_price - target
    if reward_per_unit <= 0:
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

    breakdown_low = candle.get("breakdown_low")
    return OpenTrade(
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        quantity=quantity,
        notional=notional,
        risk_dollars=risk_dollars,
        entry_fee=fees,
        open_close_time=int(candle["close_time"]),
        entry_rsi=float(candle["rsi"]),
        entry_ma200=float(candle["ma200"]),
        entry_atr=float(candle["atr"]),
        entry_breakdown_low=float(breakdown_low) if not pd.isna(breakdown_low) else float("nan"),
    )


def evaluate_exit(
    candle: pd.Series,
    state: MeanReversionState,
    params: ShortMomentumParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Mirror of mean_reversion.evaluate_exit for a short position: stop is ABOVE
    entry, target is BELOW entry, and PnL is inverted (profit when price falls). Tie
    break is mirrored too — if a candle's range hits both stop and target, the stop
    (the worse outcome for a short) is still assumed to have happened first, matching
    the long-only version's conservative bias."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    stop_loss = trade.stop_loss
    target = trade.target
    low = float(candle["low"])
    high = float(candle["high"])
    close = float(candle["close"])

    if high >= stop_loss and low <= target:
        exit_reason, raw_exit = "SL", stop_loss
    elif high >= stop_loss:
        exit_reason, raw_exit = "SL", stop_loss
    elif low <= target:
        exit_reason, raw_exit = "TARGET", target
    elif hours_held >= params.max_holding_hours:
        exit_reason, raw_exit = "TIME", close
    else:
        return None

    exit_price = apply_slippage(raw_exit, params.slippage_bps, "buy")  # closing a short: buying back
    quantity = trade.quantity
    gross_pnl = (trade.entry_price - exit_price) * quantity  # inverted: profit when price fell
    exit_fee = exit_price * quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r = state.daily_r + r_multiple
    state.open_trade = None

    return ExitEvent(
        exit_reason=exit_reason,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        holding_hours=hours_held,
        equity_after=equity_after,
    )


INDICATOR_COLUMNS_TO_CHECK = ["ma200", "rsi", "atr", "breakdown_low"]


def run_short_backtest(
    candles: pd.DataFrame,
    params: ShortMomentumParameters = DEFAULT_PARAMETERS,
) -> tuple[list[ExitEvent], MeanReversionState]:
    """Candle-by-candle simulation — same shape/contract as
    tools.backtest_compare.run_backtest, but wired to this module's own
    evaluate_exit/evaluate_entry/size_entry instead of the shared long-only ones."""
    state = MeanReversionState(equity=params.initial_equity)
    enriched = add_indicators(candles, params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    closed_trades: list[ExitEvent] = []

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the Short Momentum strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
