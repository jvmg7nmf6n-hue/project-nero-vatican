"""FVG_REVERSION v1.0.0 — Fair Value Gap reversion, both directions.

Trades the first touch of an open FVG zone (see nero_core.strategies.fvg_detection for
the full gap-lifecycle rules — formation, partial fills, expiry, the 5-per-direction
cap, and the "one signal per gap, ever" rule), gated by a MA200 trend filter: a bullish
gap touch only becomes a LONG entry if close > MA200; a bearish gap touch only becomes
a SHORT entry if close < MA200. A touch that fails its matching trend filter still
consumes that gap's one signal (see fvg_detection's docstring) — it just produces no
trade.

Unlike every other strategy in this codebase, this ONE registered strategy trades BOTH
directions (a bullish gap touch goes long, a bearish gap touch goes short) rather than
having a separate long/short sibling module (c.f. BREAKOUT_MOMENTUM/SHORT_MOMENTUM) —
because the gap type IS the direction signal, both sides share the exact same
mechanics and belong under one version. `OpenTrade.direction` ("LONG"/"SHORT") drives a
single evaluate_exit that mirrors mean_reversion.evaluate_exit's stop/target/time exit
shape for LONG and short_momentum.evaluate_exit's mirrored shape for SHORT — paper-short
accounting only (see short_momentum.py's docstring on why: this system is otherwise
long-only paper trading).

Stop = the gap zone's FAR boundary (the side away from where price approached from)
minus/plus 0.5x ATR(14) — for a bullish/LONG entry, that's `zone_bottom - 0.5*ATR`;
mirrored for bearish/SHORT, `zone_top + 0.5*ATR`. Target = 1.5x the resulting stop
distance. Timeframe-aware max holding (see nero_core.strategies.timeframe_calibration —
the max_holding_hours default here is a 1h-reference value, not meant to be used as-is
against non-hourly candles).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.fvg_detection import attach_fvg_columns
from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, atr, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "FVG_REVERSION"
STRATEGY_VERSION = "fvg-reversion-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Fair Value Gap reversion, both directions: LONG on the first touch of an open "
    "bullish FVG zone while close > MA200; SHORT (paper-only, mirrored accounting — "
    "see short_momentum.py) on the first touch of an open bearish FVG zone while "
    "close < MA200. See nero_core.strategies.fvg_detection for the full gap "
    "lifecycle (formation, partial fills, 100-candle expiry, 5-per-direction cap, "
    "one-signal-per-gap-ever). Stop = the gap zone's far boundary +/- 0.5x ATR(14); "
    "target = 1.5x that stop distance. Timeframe-aware max holding, standard 1% "
    "sizing and fees."
)


@dataclass(frozen=True)
class FvgReversionParameters:
    ma200_period: int = 200
    atr_period: int = 14
    stop_atr_multiple: float = 0.5
    reward_multiple: float = 1.5
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


DEFAULT_PARAMETERS = FvgReversionParameters()

INDICATOR_COLUMNS_TO_CHECK = ["ma200", "atr"]  # FVG signal columns are NaN on most rows by design, not warmup


@dataclass
class OpenTrade:
    direction: str  # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    entry_zone_bottom: float
    entry_zone_top: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    direction: str | None
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float


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
    exit_close_time: int


def add_indicators(candles: pd.DataFrame, params: FvgReversionParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["ma200"] = close.rolling(params.ma200_period).mean()
    frame["atr"] = atr(frame, params.atr_period)
    return attach_fvg_columns(frame)


def evaluate_entry(
    candle: pd.Series, state: MeanReversionState, params: FvgReversionParameters = DEFAULT_PARAMETERS
) -> EntryEvaluation:
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    bullish_zone_bottom = candle.get("fvg_bullish_signal_zone_bottom")
    bearish_zone_top = candle.get("fvg_bearish_signal_zone_top")
    has_bullish_touch = bullish_zone_bottom is not None and not pd.isna(bullish_zone_bottom)
    has_bearish_touch = bearish_zone_top is not None and not pd.isna(bearish_zone_top)

    close = float(candle["close"])
    ma200 = float(candle["ma200"])

    direction: str | None = None
    if has_bullish_touch and close > ma200:
        direction = "LONG"
    elif has_bearish_touch and close < ma200:
        direction = "SHORT"

    if direction is None:
        if not has_bullish_touch and not has_bearish_touch:
            reasons.append("NO_FVG_TOUCH_THIS_CANDLE")
        else:
            if has_bullish_touch:
                reasons.append("BULLISH_TOUCH_BUT_NOT_ABOVE_MA200")
            if has_bearish_touch:
                reasons.append("BEARISH_TOUCH_BUT_NOT_BELOW_MA200")

    passed = direction is not None and not reasons
    return EntryEvaluation(
        passed=passed,
        direction=direction if passed else None,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=close,
    )


def size_entry(
    candle: pd.Series, state: MeanReversionState, params: FvgReversionParameters, direction: str
) -> OpenTrade | None:
    """Returns None if the resulting risk/reward geometry is invalid — callers should
    only invoke this after `evaluate_entry` has passed with a non-None direction."""
    atr_value = float(candle["atr"])

    if direction == "LONG":
        raw_entry = float(candle["close"])
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
        zone_bottom = float(candle["fvg_bullish_signal_zone_bottom"])
        zone_top = float(candle["fvg_bullish_signal_remaining_top"])
        stop_loss = zone_bottom - params.stop_atr_multiple * atr_value
        risk_per_unit = entry_price - stop_loss
        if risk_per_unit <= 0:
            return None
        target = entry_price + params.reward_multiple * risk_per_unit
    else:  # SHORT
        raw_entry = float(candle["close"])
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "sell")  # opening a short: selling to open
        zone_top = float(candle["fvg_bearish_signal_zone_top"])
        zone_bottom = float(candle["fvg_bearish_signal_remaining_bottom"])
        stop_loss = zone_top + params.stop_atr_multiple * atr_value
        risk_per_unit = stop_loss - entry_price
        if risk_per_unit <= 0:
            return None
        target = entry_price - params.reward_multiple * risk_per_unit

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
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        quantity=quantity,
        notional=notional,
        risk_dollars=risk_dollars,
        entry_fee=fees,
        open_close_time=int(candle["close_time"]),
        entry_atr=atr_value,
        entry_zone_bottom=zone_bottom,
        entry_zone_top=zone_top,
    )


def evaluate_exit(
    candle: pd.Series, state: MeanReversionState, params: FvgReversionParameters = DEFAULT_PARAMETERS
) -> ExitEvent | None:
    """SL/TARGET/TIME, mirrored by direction — LONG mirrors mean_reversion.
    evaluate_exit exactly, SHORT mirrors short_momentum.evaluate_exit exactly (stop
    above entry, target below, inverted PnL, stop-priority tie-break)."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    low = float(candle["low"])
    high = float(candle["high"])
    close = float(candle["close"])

    if trade.direction == "LONG":
        if low <= trade.stop_loss and high >= trade.target:
            exit_reason, raw_exit = "SL", trade.stop_loss
        elif low <= trade.stop_loss:
            exit_reason, raw_exit = "SL", trade.stop_loss
        elif high >= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        elif hours_held >= params.max_holding_hours:
            exit_reason, raw_exit = "TIME", close
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
        gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    else:  # SHORT
        if high >= trade.stop_loss and low <= trade.target:
            exit_reason, raw_exit = "SL", trade.stop_loss
        elif high >= trade.stop_loss:
            exit_reason, raw_exit = "SL", trade.stop_loss
        elif low <= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        elif hours_held >= params.max_holding_hours:
            exit_reason, raw_exit = "TIME", close
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "buy")  # closing a short: buying back
        gross_pnl = (trade.entry_price - exit_price) * trade.quantity

    quantity = trade.quantity
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
        exit_close_time=candle_time,
    )


def run_backtest(
    evaluable: pd.DataFrame, params: FvgReversionParameters = DEFAULT_PARAMETERS
) -> tuple[list[ExitEvent], MeanReversionState]:
    state = MeanReversionState(equity=params.initial_equity)
    closed_trades: list[ExitEvent] = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params, evaluation.direction)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the Fair Value Gap Reversion strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
