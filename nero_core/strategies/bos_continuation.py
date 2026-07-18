"""BOS_CONTINUATION v1.0.0 — Break of Structure continuation, both directions.

Trades a BOS-up (close breaks above the currently-active, unbroken confirmed swing
high) while close > MA200, or a BOS-down (mirrored) while close < MA200 — see
nero_core.strategies.bos_detection for the full pivot-confirmation and one-shot-break
rules. Like FVG_REVERSION, this ONE registered strategy trades BOTH directions under
one version (the break direction IS the trade direction) rather than having a separate
long/short sibling module; `OpenTrade.direction` drives a single evaluate_exit mirroring
mean_reversion.evaluate_exit for LONG and short_momentum.evaluate_exit for SHORT
(paper-short accounting only — see short_momentum.py's docstring on why).

STOP: the swing low preceding the broken high (mirrored: swing high preceding a broken
low), minus/plus a 0.25x ATR buffer — BUT capped at 3.0x ATR total distance from entry.
If the structural distance (entry to the buffered preceding-extreme level) exceeds 3x
ATR, the stop is placed at exactly 3x ATR from entry instead. Every trade records which
was actually used (`stop_type`: "structural" or "capped"), aggregated by the sweep
report tool per the task's "document which was used per trade in aggregate counts"
requirement. Target = 2x the ACTUAL (possibly capped) stop distance. No preceding
extreme confirmed yet (early history) -> no valid structural stop -> entry rejected,
never fabricated.

Timeframe-aware max holding (see nero_core.strategies.timeframe_calibration — the
default here is a 1h-reference value, not meant to be used as-is against non-hourly
candles). Standard 1% sizing and fees.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.bos_detection import attach_bos_columns
from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, atr, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "BOS_CONTINUATION"
STRATEGY_VERSION = "bos-continuation-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Break of Structure continuation, both directions: LONG on a BOS-up (close breaks "
    "above the currently-active, unbroken confirmed swing high — 5-candle-lookaround "
    "pivots, confirmed only 5 candles after formation, one signal per pivot ever) while "
    "close > MA200; SHORT (paper-only, mirrored accounting — see short_momentum.py) on "
    "a BOS-down while close < MA200. See nero_core.strategies.bos_detection for the "
    "full pivot lifecycle. Stop = the swing low/high preceding the broken pivot, +/- "
    "0.25x ATR buffer, capped at 3.0x ATR total distance (whichever is used is recorded "
    "per trade). Target = 2x the actual stop distance used. Timeframe-aware max "
    "holding, standard 1% sizing and fees."
)


@dataclass(frozen=True)
class BosContinuationParameters:
    ma200_period: int = 200
    atr_period: int = 14
    stop_atr_buffer_multiple: float = 0.25
    stop_atr_cap_multiple: float = 3.0
    reward_multiple: float = 2.0
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


DEFAULT_PARAMETERS = BosContinuationParameters()

INDICATOR_COLUMNS_TO_CHECK = ["ma200", "atr"]  # BOS signal columns are NaN on most rows by design, not warmup


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
    stop_type: str  # "structural" | "capped"


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
    stop_type: str  # carried over from the OpenTrade, for aggregate reporting


def add_indicators(candles: pd.DataFrame, params: BosContinuationParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["ma200"] = close.rolling(params.ma200_period).mean()
    frame["atr"] = atr(frame, params.atr_period)
    return attach_bos_columns(frame)


def evaluate_entry(
    candle: pd.Series, state: MeanReversionState, params: BosContinuationParameters = DEFAULT_PARAMETERS
) -> EntryEvaluation:
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    bos_up_pivot = candle.get("bos_up_signal_pivot_value")
    bos_down_pivot = candle.get("bos_down_signal_pivot_value")
    has_bos_up = bos_up_pivot is not None and not pd.isna(bos_up_pivot)
    has_bos_down = bos_down_pivot is not None and not pd.isna(bos_down_pivot)

    close = float(candle["close"])
    ma200 = float(candle["ma200"])

    direction: str | None = None
    if has_bos_up and close > ma200:
        direction = "LONG"
    elif has_bos_down and close < ma200:
        direction = "SHORT"

    if direction is None:
        if not has_bos_up and not has_bos_down:
            reasons.append("NO_BOS_THIS_CANDLE")
        else:
            if has_bos_up:
                reasons.append("BOS_UP_BUT_NOT_ABOVE_MA200")
            if has_bos_down:
                reasons.append("BOS_DOWN_BUT_NOT_BELOW_MA200")
    elif direction == "LONG" and (candle.get("bos_up_signal_preceding_low") is None or pd.isna(candle.get("bos_up_signal_preceding_low"))):
        reasons.append("NO_PRECEDING_SWING_LOW_FOR_STOP")
        direction = None
    elif direction == "SHORT" and (
        candle.get("bos_down_signal_preceding_high") is None or pd.isna(candle.get("bos_down_signal_preceding_high"))
    ):
        reasons.append("NO_PRECEDING_SWING_HIGH_FOR_STOP")
        direction = None

    passed = direction is not None and not reasons
    return EntryEvaluation(
        passed=passed,
        direction=direction if passed else None,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=close,
    )


def size_entry(
    candle: pd.Series, state: MeanReversionState, params: BosContinuationParameters, direction: str
) -> OpenTrade | None:
    """Returns None if the resulting risk/reward geometry is invalid — callers should
    only invoke this after `evaluate_entry` has passed with a non-None direction."""
    atr_value = float(candle["atr"])
    cap_distance = params.stop_atr_cap_multiple * atr_value

    if direction == "LONG":
        raw_entry = float(candle["close"])
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
        preceding_low = float(candle["bos_up_signal_preceding_low"])
        structural_stop = preceding_low - params.stop_atr_buffer_multiple * atr_value
        structural_distance = entry_price - structural_stop
        if structural_distance > cap_distance:
            stop_distance, stop_type = cap_distance, "capped"
        else:
            stop_distance, stop_type = structural_distance, "structural"
        if stop_distance <= 0:
            return None
        stop_loss = entry_price - stop_distance
        target = entry_price + params.reward_multiple * stop_distance
    else:  # SHORT
        raw_entry = float(candle["close"])
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "sell")  # opening a short: selling to open
        preceding_high = float(candle["bos_down_signal_preceding_high"])
        structural_stop = preceding_high + params.stop_atr_buffer_multiple * atr_value
        structural_distance = structural_stop - entry_price
        if structural_distance > cap_distance:
            stop_distance, stop_type = cap_distance, "capped"
        else:
            stop_distance, stop_type = structural_distance, "structural"
        if stop_distance <= 0:
            return None
        stop_loss = entry_price + stop_distance
        target = entry_price - params.reward_multiple * stop_distance

    risk_per_unit = stop_distance
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
        stop_type=stop_type,
    )


def evaluate_exit(
    candle: pd.Series, state: MeanReversionState, params: BosContinuationParameters = DEFAULT_PARAMETERS
) -> ExitEvent | None:
    """SL/TARGET/TIME, mirrored by direction — same shape as fvg_reversion.evaluate_exit."""
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
        stop_type=trade.stop_type,
    )


def run_backtest(
    evaluable: pd.DataFrame, params: BosContinuationParameters = DEFAULT_PARAMETERS
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
    """Register the Break of Structure Continuation strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
