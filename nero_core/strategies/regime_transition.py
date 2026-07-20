"""REGIME_TRANSITION v1.0.0 — Ranging-Regime Research Batch, Hypothesis R1.

MECHANISM: a mature range ENDING is a trend BEGINNING — the regime-detection route
to the same phenomenon this project's already-verified BREAKOUT_MOMENTUM survivor
exploits from a pure price-action angle. Trades the regime CHANGE itself, never a
band-extreme entry (per this batch's own framing: RMR proved random entries inside
ADX<25 regimes performed as well as band-extreme entries almost everywhere — the
regime filter does the work, not entry timing).

STATE MACHINE:
  1. RANGING: ADX(14) < 25 for >= mature_range_min_candles (10) CONSECUTIVE closed
     candles = a "mature range." While mature, the range boundaries are tracked
     live but never frozen until a transition actually fires.
  2. TRANSITION signal candle (call it T): ADX crosses >= 25 (breaking the streak)
     AND T's own close is beyond the FROZEN boundary — range_high/range_low computed
     ONLY over the mature-range candles that preceded T (T itself is EXCLUDED from
     the boundary computation — no self-reference: T's own extreme close could not
     inflate the very boundary it needs to clear).
     close > range_high -> LONG signal. close < range_low -> SHORT signal.
  3. EXECUTION at the candle AFTER T (T+1), at T+1's OPEN — the existing
     closed-candle convention (T's own close is already known at T+1's open, so no
     lookahead), same "wait one candle" timing RANGE_MEAN_REVERSION's confirmation
     variant already established as a valid discipline in this project.

STOP: the NEARER of (distance to the frozen range's midpoint) or
(2.5x ATR(14) from entry) — 2.5xATR acts as a CEILING on stop distance, not a
target. A FLOOR of 0.75xATR is additionally enforced (a very tight range's midpoint
could otherwise imply a near-zero stop). Which rule actually bound the stop
("midpoint" / "atr_ceiling" / "atr_floor") is recorded on every trade for aggregate
reporting.

TARGET: 2x the frozen range's height, measured from T's own breakout close (not the
actual T+1 fill price) — i.e. target = breakout_close +/- 2*(range_high - range_low).

EXIT priority (checked every closed candle after entry): STOP, then TARGET, then
FAILED_TRANSITION (ADX falls back below 20 — the breakout didn't hold), then TIME
(a timeframe-aware holding cap, re-derived per timeframe the same way every other
strategy in this project corrects its 1h-reference default — see
nero_core.strategies.timeframe_calibration.max_holding_hours_for_timeframe).

SHORT ACCOUNTING reuses the same generic short P&L math (apply_slippage direction,
inverted gross_pnl) already established by short_momentum.py and reused by
range_mean_reversion.py — not any strategy-specific signal logic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import apply_slippage, atr, reset_daily_guard_if_needed
from nero_core.strategies.range_mean_reversion import adx
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "REGIME_TRANSITION"
STRATEGY_VERSION = "regime-transition-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Trades the regime CHANGE, not a band-extreme entry: after ADX(14) < 25 for >= "
    "10 consecutive closed candles (a mature range), a transition candle where ADX "
    "crosses >= 25 AND closes beyond the FROZEN range boundary (computed only over "
    "the preceding mature-range candles, excluding the transition candle itself) "
    "fires a LONG (close above range_high) or SHORT (close below range_low) signal, "
    "executed at the NEXT candle's open. Stop: the nearer of the frozen range's "
    "midpoint or 2.5x ATR(14), floored at 0.75x ATR(14). Target: 2x the frozen range "
    "height from the breakout close. Exit also on ADX falling back below 20 (failed "
    "transition) or a timeframe-aware holding cap. Fixed-fractional 1% risk per trade."
)


@dataclass(frozen=True)
class RegimeTransitionParameters:
    adx_period: int = 14
    adx_entry_threshold: float = 25.0
    adx_failed_transition_threshold: float = 20.0
    mature_range_min_candles: int = 10
    atr_period: int = 14
    atr_stop_ceiling_multiple: float = 2.5
    atr_stop_floor_multiple: float = 0.75
    target_range_height_multiple: float = 2.0
    # 1h-reference default — see nero_core.strategies.timeframe_calibration.
    # max_holding_hours_for_timeframe for the per-timeframe re-derivation any real
    # backtest run must use instead of this raw value (same lesson as every other
    # strategy in this project).
    max_holding_hours: int = 24
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = RegimeTransitionParameters()

INDICATOR_COLUMNS_TO_CHECK = ["adx", "atr"]


@dataclass(frozen=True)
class PendingSignal:
    direction: str  # "LONG" | "SHORT"
    range_high: float
    range_low: float
    breakout_close: float


@dataclass
class OpenTrade:
    direction: str
    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    stop_type: str  # "midpoint" | "atr_ceiling" | "atr_floor"


@dataclass
class RegimeTransitionState:
    """Duck-types against nero_core.strategies.mean_reversion.reset_daily_guard_if_
    needed. `streak_start_index` is the index of the first candle in the CURRENT
    unbroken low-ADX streak (None outside a streak) — needed because streak length
    is unbounded/variable, unlike a fixed lookback, so it must be tracked
    incrementally rather than recomputed each candle. `pending_signal` holds a fired
    transition awaiting execution at the very next candle's open; always consumed
    (fired or not) after exactly one candle."""

    equity: float
    daily_r: float = 0.0
    daily_guard_day: str | None = None
    open_trade: OpenTrade | None = None
    streak_start_index: int | None = None
    pending_signal: PendingSignal | None = None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "STOP" | "TARGET" | "FAILED_TRANSITION" | "TIME"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float
    exit_close_time: int = 0
    stop_type: str = ""


def add_indicators(candles: pd.DataFrame, params: RegimeTransitionParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """No lookahead: every value at row i only uses candles up to and including i."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    frame["adx"] = adx(frame, params.adx_period)
    frame["atr"] = atr(frame, params.atr_period)
    return frame


def size_transition_entry(
    candle: pd.Series, pending: PendingSignal, state: RegimeTransitionState,
    params: RegimeTransitionParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Entry price is THIS candle's own OPEN (the candle after the transition
    signal). Returns None if the resulting stop distance isn't positive."""
    raw_entry = float(candle["open"])
    atr_value = float(candle["atr"])
    direction = pending.direction
    range_height = pending.range_high - pending.range_low
    range_midpoint = (pending.range_high + pending.range_low) / 2.0

    if direction == "LONG":
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    else:
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "sell")

    distance_to_midpoint = abs(entry_price - range_midpoint)
    distance_ceiling = params.atr_stop_ceiling_multiple * atr_value
    if distance_to_midpoint <= distance_ceiling:
        raw_distance, stop_type = distance_to_midpoint, "midpoint"
    else:
        raw_distance, stop_type = distance_ceiling, "atr_ceiling"

    floor_distance = params.atr_stop_floor_multiple * atr_value
    if raw_distance < floor_distance:
        final_distance, stop_type = floor_distance, "atr_floor"
    else:
        final_distance = raw_distance

    if final_distance <= 0:
        return None

    if direction == "LONG":
        stop_loss = entry_price - final_distance
        target = pending.breakout_close + params.target_range_height_multiple * range_height
    else:
        stop_loss = entry_price + final_distance
        target = pending.breakout_close - params.target_range_height_multiple * range_height

    risk_dollars = state.equity * params.risk_per_trade
    quantity = risk_dollars / final_distance
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * final_distance
    fees = notional * params.fee_bps / 10000.0

    return OpenTrade(
        direction=direction, entry_price=entry_price, stop_loss=stop_loss, target=target,
        quantity=quantity, notional=notional, risk_dollars=risk_dollars, entry_fee=fees,
        open_close_time=int(candle["close_time"]), entry_atr=atr_value, stop_type=stop_type,
    )


def evaluate_exit(
    candle: pd.Series, state: RegimeTransitionState, params: RegimeTransitionParameters = DEFAULT_PARAMETERS
) -> ExitEvent | None:
    """Priority: STOP, TARGET (tie-break to STOP if both hit the same candle,
    matching every other strategy's conservative convention), FAILED_TRANSITION,
    TIME."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3_600_000.0
    low = float(candle["low"])
    high = float(candle["high"])
    close = float(candle["close"])
    adx_value = candle.get("adx")

    exit_reason: str | None = None
    raw_exit: float | None = None

    if trade.direction == "LONG":
        if low <= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif high >= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        elif adx_value is not None and not pd.isna(adx_value) and float(adx_value) < params.adx_failed_transition_threshold:
            exit_reason, raw_exit = "FAILED_TRANSITION", close
        elif hours_held >= params.max_holding_hours:
            exit_reason, raw_exit = "TIME", close
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
        gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    else:  # SHORT
        if high >= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif low <= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        elif adx_value is not None and not pd.isna(adx_value) and float(adx_value) < params.adx_failed_transition_threshold:
            exit_reason, raw_exit = "FAILED_TRANSITION", close
        elif hours_held >= params.max_holding_hours:
            exit_reason, raw_exit = "TIME", close
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "buy")
        gross_pnl = (trade.entry_price - exit_price) * trade.quantity

    quantity = trade.quantity
    exit_fee = exit_price * quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r += r_multiple
    state.open_trade = None

    return ExitEvent(
        exit_reason=exit_reason, exit_price=exit_price, gross_pnl=gross_pnl, fees=total_fees,
        net_pnl=net_pnl, r_multiple=r_multiple, holding_hours=hours_held, equity_after=equity_after,
        exit_close_time=candle_time, stop_type=trade.stop_type,
    )


def _update_streak_and_detect_transition(
    evaluable: pd.DataFrame, i: int, state: RegimeTransitionState, params: RegimeTransitionParameters
) -> None:
    """Updates the low-ADX streak tracker using candle i's own ADX, and — if candle i
    breaks a mature (>= mature_range_min_candles) streak with a close beyond the
    FROZEN boundary (computed over the streak candles, i excluded) — sets
    state.pending_signal for execution at candle i+1. Never fires a new signal while
    a trade is already open or the daily loss guard is active."""
    adx_i = evaluable.iloc[i].get("adx")
    if adx_i is None or pd.isna(adx_i):
        return
    adx_i = float(adx_i)

    if adx_i < params.adx_entry_threshold:
        if state.streak_start_index is None:
            state.streak_start_index = i
        return  # still ranging; no transition possible this candle

    # ADX >= threshold: candle i is a potential transition candle.
    if state.streak_start_index is not None:
        streak_len = i - state.streak_start_index  # candles [start, i-1] are mature-range candles
        if (
            streak_len >= params.mature_range_min_candles
            and state.open_trade is None
            and state.daily_r > params.daily_loss_guard_r
        ):
            window = evaluable.iloc[state.streak_start_index:i]
            range_high = float(window["high"].max())
            range_low = float(window["low"].min())
            close_i = float(evaluable.iloc[i]["close"])
            direction: str | None = None
            if close_i > range_high:
                direction = "LONG"
            elif close_i < range_low:
                direction = "SHORT"
            if direction is not None:
                state.pending_signal = PendingSignal(
                    direction=direction, range_high=range_high, range_low=range_low, breakout_close=close_i
                )
    state.streak_start_index = None  # streak broken regardless of whether a transition fired


def run_backtest(
    evaluable: pd.DataFrame, params: RegimeTransitionParameters = DEFAULT_PARAMETERS
) -> tuple[list[ExitEvent], RegimeTransitionState]:
    state = RegimeTransitionState(equity=params.initial_equity)
    closed_trades: list[ExitEvent] = []

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        if state.pending_signal is not None:
            if state.open_trade is None:
                trade = size_transition_entry(candle, state.pending_signal, state, params)
                if trade is not None:
                    state.open_trade = trade
            state.pending_signal = None  # always consumed after exactly one candle

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        _update_streak_and_detect_transition(evaluable, i, state, params)

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register REGIME_TRANSITION's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
