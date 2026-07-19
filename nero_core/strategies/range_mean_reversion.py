"""RANGE_MEAN_REVERSION v1.0.0 — a user-designed strategy, formalized here.

ORIGIN: a discretionary trader ran this profitably by intuition — in a range-bound
market, buy when price drops meaningfully below its recent average (expecting
reversion up), short when it rises meaningfully above (expecting reversion down),
but ONLY while the market was genuinely ranging, never trending. The
regime-awareness IS the strategy; entries without it are just naive mean reversion
into a trend, which is a well-known way to get run over.

REGIME GATE (checked first): ADX(14) < 25 is required for a NEW entry. ADX is
computed here from scratch — no prior implementation existed anywhere in this
codebase. Smoothed via the SAME simple rolling-mean convention this codebase's own
ATR (nero_core.strategies.mean_reversion.atr) already uses, not Wilder's classic
exponential smoothing — a deliberate consistency choice with the rest of this
project's indicator conventions, not an oversight or an approximation error.

ENTRY (only while ADX < 25): LONG when close < lower Bollinger Band (SMA20, 2.0std);
SHORT when close > upper Bollinger Band. Entry is always strictly beyond a band —
i.e. beyond SMA20 +/- 2 std — so a same-candle SMA20-cross exit is structurally
impossible on the entry candle itself; combined with this module's shared
candle-by-candle loop convention (evaluate_exit is always called on candle i BEFORE
evaluate_entry considers opening a NEW trade on candle i), no trade is ever exited on
the same candle it was opened.

EXIT, in priority order (checked every closed candle, never the entry candle):
  1. Disaster stop: 2.0x ATR(14) beyond entry — checked first, matching every other
     strategy's "safety before signal" convention in this codebase.
  2. Regime-break (hysteresis): ADX >= 28 for TWO CONSECUTIVE closed candles while a
     trade is open. The 25/28 gap between entry and exit thresholds, plus the
     2-consecutive-bar requirement, is deliberate: it prevents a single ADX tick
     right at the boundary from bouncing the strategy in and out of a trade
     (whipsaw) — entry and exit never fire off the same knife-edge value.
  3. Reversion target: close touches/crosses back to SMA20 from the direction the
     trade entered from.
No fixed holding-hours cap — deliberate, matching DONCHIAN_TREND/MACRO_RISK_ON's own
precedent: this strategy's premise is waiting out a range until it reverts or
genuinely breaks, and a time cap would cut exactly the trades it exists to catch.

SHORT ACCOUNTING: reuses ONLY the generic short P&L math (apply_slippage direction,
inverted gross_pnl, standard fee/r_multiple formulas) that
nero_core.strategies.short_momentum.evaluate_exit already established as this
codebase's short-accounting convention — NOT short_momentum's own entry/exit signal
logic (breakdown-low/RSI/MA200), which is specific to that strategy and irrelevant
here. This strategy defines its own entry/exit rules from scratch.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import apply_slippage, atr, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "RANGE_MEAN_REVERSION"
STRATEGY_VERSION = "range-mean-reversion-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Regime-gated mean reversion, both directions: LONG when close < lower Bollinger "
    "Band (SMA20, 2.0std) AND ADX(14) < 25 (ranging); SHORT when close > upper band "
    "under the same regime gate. Exit priority: 2x-ATR(14) disaster stop, then a "
    "regime-break exit (ADX >= 28 for 2 consecutive closed candles — hysteresis "
    "against the 25 entry threshold to avoid whipsaw), then a reversion target (close "
    "crosses back to SMA20). No fixed holding-hours cap. Fixed-fractional 1% risk per "
    "trade. Formalized from a discretionary trader's profitable-by-intuition rule set "
    "— the regime gate (never trade band-extremes in a trending market) IS the "
    "strategy, not an add-on filter."
)


@dataclass(frozen=True)
class RangeMeanReversionParameters:
    """No max_holding_hours field — deliberate (see module docstring): this
    strategy's exit is fully regime/reversion/stop-driven, matching DONCHIAN_TREND
    and MACRO_RISK_ON's own no-time-cap precedent."""

    adx_period: int = 14
    adx_entry_threshold: float = 25.0
    adx_exit_threshold: float = 28.0
    adx_exit_consecutive_bars: int = 2
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0
    # RMR Variant Research Cycle additions (v1.1.0/v1.2.0) — both default to v1.0.0's
    # exact original behavior, so DEFAULT_PARAMETERS (and every pre-existing caller)
    # is completely unchanged; only a variant module that explicitly sets these differs.
    allow_short: bool = True  # False disables the SHORT side entirely (long-only variants)
    require_adx_falling: bool = False  # extra entry condition: ADX[t] < ADX[t - adx_falling_lookback]
    adx_falling_lookback: int = 3  # in CLOSED candles, not 1-candle noise


DEFAULT_PARAMETERS = RangeMeanReversionParameters()

INDICATOR_COLUMNS_TO_CHECK = ["sma20", "bb_lower", "bb_upper", "adx", "atr"]


@dataclass
class OpenTrade:
    direction: str  # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float


@dataclass
class RangeMeanReversionState:
    """Duck-types against nero_core.strategies.mean_reversion.reset_daily_guard_if_
    needed (only reads/writes equity/daily_r/daily_guard_day, so any object exposing
    those works — reused as-is rather than reimplemented, since the daily-loss-guard
    mechanic doesn't vary by strategy family). `consecutive_high_adx_bars` is this
    strategy's own addition: the regime-break exit's hysteresis counter, incremented
    by evaluate_exit while a trade is open and ADX stays >= adx_exit_threshold, reset
    to 0 the moment ADX drops back below that threshold or a trade closes."""

    equity: float
    daily_r: float = 0.0
    daily_guard_day: str | None = None
    open_trade: OpenTrade | None = None
    consecutive_high_adx_bars: int = 0


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    direction: str | None
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    adx: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "STOP" | "REGIME_BREAK" | "REVERSION_TARGET"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float
    exit_close_time: int = 0


def _true_range(frame: pd.DataFrame) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    return pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)


def _directional_movement(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(0.0, index=frame.index)
    minus_dm = pd.Series(0.0, index=frame.index)
    plus_mask = (up_move > down_move) & (up_move > 0)
    minus_mask = (down_move > up_move) & (down_move > 0)
    plus_dm[plus_mask] = up_move[plus_mask]
    minus_dm[minus_mask] = down_move[minus_mask]
    return plus_dm, minus_dm


def adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX(period), smoothed via simple rolling mean throughout (+DM, -DM, TR, and
    the final DX-to-ADX step) — see module docstring for why this deliberately
    doesn't use Wilder's classic exponential smoothing. No lookahead: row i only
    ever uses rows <= i."""
    plus_dm, minus_dm = _directional_movement(frame)
    true_range = _true_range(frame)
    tr_smoothed = true_range.rolling(period).mean().replace(0, math.nan)
    plus_di = 100.0 * plus_dm.rolling(period).mean() / tr_smoothed
    minus_di = 100.0 * minus_dm.rolling(period).mean() / tr_smoothed
    di_sum = (plus_di + minus_di).replace(0, math.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    return dx.rolling(period).mean()


def add_indicators(candles: pd.DataFrame, params: RangeMeanReversionParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """No lookahead: every value at row i only uses candles up to and including i."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["sma20"] = close.rolling(params.bollinger_period).mean()
    bb_std = close.rolling(params.bollinger_period).std(ddof=0)
    frame["bb_upper"] = frame["sma20"] + params.bollinger_std * bb_std
    frame["bb_lower"] = frame["sma20"] - params.bollinger_std * bb_std
    # Secondary logged metric only (per the task spec) — NOT part of the v1.0 regime
    # gate, which is ADX alone. Kept purely for later analysis of whether BB width
    # would have made a better/complementary regime signal.
    frame["bb_width_pct"] = (frame["bb_upper"] - frame["bb_lower"]) / frame["sma20"].replace(0, math.nan) * 100.0
    frame["adx"] = adx(frame, params.adx_period)
    frame["atr"] = atr(frame, params.atr_period)
    # RMR Variant Research Cycle: a 3-CLOSED-candle ADX decline (not 1-candle noise),
    # always computed (harmless when params.require_adx_falling is False — it's simply
    # never consulted by evaluate_entry in that case). NaN wherever fewer than
    # adx_falling_lookback prior candles exist; comparing against NaN correctly
    # evaluates False (never satisfied), not a crash.
    frame["adx_falling"] = frame["adx"] < frame["adx"].shift(params.adx_falling_lookback)
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: RangeMeanReversionState,
    params: RangeMeanReversionParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Every rejection reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    close_time = int(candle["close_time"])
    close = float(candle["close"])
    adx_value = candle.get("adx")

    if adx_value is None or pd.isna(adx_value):
        reasons.append("ADX_NOT_AVAILABLE")
        return EntryEvaluation(passed=False, direction=None, reasons=tuple(reasons), candle_close_time=close_time, close=close, adx=None)

    adx_value = float(adx_value)
    if adx_value >= params.adx_entry_threshold:
        reasons.append("NOT_RANGING")

    bb_lower = candle.get("bb_lower")
    bb_upper = candle.get("bb_upper")
    direction: str | None = None
    if bb_lower is None or bb_upper is None or pd.isna(bb_lower) or pd.isna(bb_upper):
        reasons.append("BANDS_NOT_AVAILABLE")
    elif close < float(bb_lower):
        direction = "LONG"
    elif close > float(bb_upper):
        direction = "SHORT"
    else:
        reasons.append("NO_BAND_BREACH")

    if direction == "SHORT" and not params.allow_short:
        reasons.append("SHORT_DISABLED")
        direction = None

    if direction is not None and params.require_adx_falling:
        adx_falling = candle.get("adx_falling")
        if adx_falling is None or pd.isna(adx_falling) or not bool(adx_falling):
            reasons.append("ADX_NOT_FALLING")
            direction = None

    passed = direction is not None and not reasons
    return EntryEvaluation(
        passed=passed, direction=direction if passed else None, reasons=tuple(reasons),
        candle_close_time=close_time, close=close, adx=adx_value,
    )


def size_entry(
    candle: pd.Series,
    state: RangeMeanReversionState,
    params: RangeMeanReversionParameters = DEFAULT_PARAMETERS,
    direction: str = "LONG",
) -> OpenTrade | None:
    """Fixed-fractional sizing against a 2x-ATR stop distance. Returns None if that
    distance isn't positive. SHORT opening reuses short_momentum's own
    apply_slippage(..., "sell") convention ("selling to open")."""
    raw_entry = float(candle["close"])
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


def evaluate_exit(
    candle: pd.Series,
    state: RangeMeanReversionState,
    params: RangeMeanReversionParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Priority order: STOP, then REGIME_BREAK, then REVERSION_TARGET — matching
    every other strategy's "safety before signal" convention. Updates
    state.consecutive_high_adx_bars every call, whether or not a trade is open."""
    trade = state.open_trade

    adx_value = candle.get("adx")
    if adx_value is not None and not pd.isna(adx_value) and float(adx_value) >= params.adx_exit_threshold:
        state.consecutive_high_adx_bars += 1
    else:
        state.consecutive_high_adx_bars = 0

    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3_600_000.0
    close = float(candle["close"])
    low = float(candle["low"])
    high = float(candle["high"])
    sma20 = candle.get("sma20")

    exit_reason: str | None = None
    raw_exit: float | None = None

    if trade.direction == "LONG":
        if low <= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif state.consecutive_high_adx_bars >= params.adx_exit_consecutive_bars:
            exit_reason, raw_exit = "REGIME_BREAK", close
        elif sma20 is not None and not pd.isna(sma20) and close >= float(sma20):
            exit_reason, raw_exit = "REVERSION_TARGET", close
    else:  # SHORT
        if high >= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif state.consecutive_high_adx_bars >= params.adx_exit_consecutive_bars:
            exit_reason, raw_exit = "REGIME_BREAK", close
        elif sma20 is not None and not pd.isna(sma20) and close <= float(sma20):
            exit_reason, raw_exit = "REVERSION_TARGET", close

    if exit_reason is None:
        return None

    if trade.direction == "LONG":
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
        gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    else:  # SHORT: closing = buying back (short_momentum's own convention, reused)
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "buy")
        gross_pnl = (trade.entry_price - exit_price) * trade.quantity

    exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r += r_multiple
    state.open_trade = None
    state.consecutive_high_adx_bars = 0

    return ExitEvent(
        exit_reason=exit_reason, exit_price=exit_price, gross_pnl=gross_pnl, fees=total_fees,
        net_pnl=net_pnl, r_multiple=r_multiple, holding_hours=hours_held, equity_after=equity_after,
        exit_close_time=candle_time,
    )


def run_backtest(
    evaluable: pd.DataFrame, params: RangeMeanReversionParameters = DEFAULT_PARAMETERS
) -> tuple[list[ExitEvent], RangeMeanReversionState]:
    state = RangeMeanReversionState(equity=params.initial_equity)
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


def range_eligible_mask(evaluable: pd.DataFrame, params: RangeMeanReversionParameters = DEFAULT_PARAMETERS) -> pd.Series:
    """The regime gate ITSELF (ADX < entry threshold) is the eligible pool for a
    random-entry baseline — the whole point of Task 2's random-baseline comparison is
    to isolate whether band-extreme timing adds value BEYOND the regime filter alone,
    so the baseline must only ever fire within the same ranging regime this strategy
    requires."""
    return evaluable["adx"] < params.adx_entry_threshold


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register RANGE_MEAN_REVERSION's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
