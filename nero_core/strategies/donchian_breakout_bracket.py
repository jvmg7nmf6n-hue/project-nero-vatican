"""DONCHIAN_TREND, bracket-exit variant — Donchian Cross-Asset Deep-Dive, Task 2.

MECHANISM NOTE (why this is a separate module, not a recalibration of
donchian_trend.py): the existing donchian-trend-v1.0.0 (GOLD 1week only) exits on a
TRAILING channel level re-evaluated every candle, with no fixed stop/target and no
holding cap by design. This batch's task spec calls for a materially different exit
contract — a 2.0x-ATR(14) stop fixed at entry, a fixed 2R target (1:2 R:R), and an
explicit holding-period cap — and is bidirectional (LONG on an N-period high breakout,
SHORT on an N-period low breakout), where v1.0.0 is long-only. Per this project's rule
that a parameter/mechanism change registers as a new, explicitly versioned variant
rather than mutating an existing one in place, this is STRATEGY_ID "DONCHIAN_TREND"
(same family under test) at STRATEGY_VERSION "donchian-trend-v2.0.0-bracket-*"
(distinct major version — a different exit mechanism, not a calibration tweak).

DIRECTION INFERENCE (shared by the real entry path AND the Task-3 random-baseline
harness): `size_entry` infers direction from "is close closer to the N-period high or
the N-period low" rather than receiving direction as an argument, because
tools.backtest_statistics.random_entry_baseline_single_asset's shared random-entry
simulator calls `size_entry_fn(candle, state, params)` with no direction parameter —
this keeps one implementation usable in both the real backtest loop (where it always
agrees with the actual breakout direction, since a candle can't be both above the high
and below the low) and Task 3's near-breakout random baseline (where it doubles as the
direction proxy for candles that are merely NEAR an extreme, not necessarily past it).

HOLDING CAP: `max_holding_hours` is a REAL-TIME cap (holding_weeks * 168), not a
candle-count cap — this keeps the field consistent with every other strategy in this
codebase (mean_reversion.py, short_momentum.py) and makes it automatically
timeframe-agnostic (the same weeks-based thesis applies whether candles are 1week or
1day bars) rather than needing a separate day/week candle-count conversion for the cap
specifically. `channel_period` (the Donchian lookback itself), by contrast, IS a raw
candle count, since a channel is inherently defined over N bars — see
build_channel_period_for_timeframe for how the N-in-weeks values convert to an N-in-days
equivalent for 1day timeframe assets (SPY/QQQ), preserving the same real-world lookback
duration rather than the same candle count.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import (
    MeanReversionState,
    apply_slippage,
    atr,
    reset_daily_guard_if_needed,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "DONCHIAN_TREND"

TRADING_DAYS_PER_WEEK = 5
HOURS_PER_WEEK = 168

# The three N-value presets under test, per this batch's own spec: (channel_weeks,
# holding_weeks). Each preset's mechanical validity (holding cap > N) is asserted in
# build_parameters_for_n, per the task's own "flag and skip rather than force" rule.
N_PRESETS = {
    "N10": {"channel_weeks": 10, "holding_weeks": 20, "thesis": "tactical — short trend cycles"},
    "N20": {"channel_weeks": 20, "holding_weeks": 30, "thesis": "classic Donchian — medium-term trend"},
    "N40": {"channel_weeks": 40, "holding_weeks": 52, "thesis": "structural — major trends only"},
}


class MechanicallyInvalidConfigError(Exception):
    """Raised when a requested (channel_weeks, holding_weeks) pair violates holding
    cap > N — per this batch's own rule, such a config must be flagged and skipped,
    never silently forced through."""


@dataclass(frozen=True)
class DonchianBracketParameters:
    channel_period: int = 20  # in CANDLES of whatever timeframe is being backtested
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    target_r_multiple: float = 2.0  # target_distance = target_r_multiple * risk_distance -> 1:2 R:R
    max_holding_hours: int = 30 * HOURS_PER_WEEK
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


def build_parameters_for_n(n_key: str, timeframe: str, fee_bps: float, slippage_bps: float) -> DonchianBracketParameters:
    """Builds the DonchianBracketParameters for one of N_PRESETS at a given
    timeframe ("1week" or "1day"). channel_period converts channel_weeks to an
    equivalent candle count for the timeframe (1:1 for 1week, x5 trading-days/week for
    1day); max_holding_hours is timeframe-agnostic by construction (see module
    docstring). Raises MechanicallyInvalidConfigError if holding_weeks <= channel_weeks
    for the requested preset (none of N_PRESETS' own values trigger this; the check
    exists so a future preset can't silently violate it)."""
    preset = N_PRESETS[n_key]
    if preset["holding_weeks"] <= preset["channel_weeks"]:
        raise MechanicallyInvalidConfigError(
            f"{n_key}: holding cap ({preset['holding_weeks']}w) must exceed channel period "
            f"({preset['channel_weeks']}w) to let a trend develop — config skipped, not forced."
        )
    if timeframe == "1week":
        channel_period = preset["channel_weeks"]
    elif timeframe == "1day":
        channel_period = preset["channel_weeks"] * TRADING_DAYS_PER_WEEK
    else:
        raise ValueError(f"unsupported timeframe for Donchian bracket: {timeframe!r}")

    return DonchianBracketParameters(
        channel_period=channel_period,
        max_holding_hours=preset["holding_weeks"] * HOURS_PER_WEEK,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )


DEFAULT_PARAMETERS = DonchianBracketParameters()

STRATEGY_DESCRIPTION = (
    "Bidirectional Donchian channel breakout, bracket exit: LONG on close > the "
    "N-period highest high (prior N candles, shift(1) — the current candle's own high "
    "never counts toward its own threshold), SHORT on close < the N-period lowest low, "
    "symmetric. Stop = 2.0x ATR(14) from entry; target = 2.0x the stop distance (1:2 "
    "R:R); max_holding_hours is a real-time cap (holding_weeks * 168h), not a "
    "candle-count cap. Three N presets tested (N_PRESETS): N10 (tactical), N20 "
    "(classic Donchian), N40 (structural) — each with its own holding cap matched to "
    "let the intended trend horizon develop. Standard 1% fixed-fractional sizing on "
    "the ATR-stop risk distance."
)


@dataclass
class OpenTrade:
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    direction: str | None
    donchian_high: float | None
    donchian_low: float | None
    atr: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "SL", "TARGET", or "TIME"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float


INDICATOR_COLUMNS_TO_CHECK = ["donchian_high", "donchian_low", "atr"]


def add_indicators(candles: pd.DataFrame, params: DonchianBracketParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach the N-period Donchian high/low (both shift(1) before the rolling
    window — no lookahead, and a candle can genuinely break its own channel) and
    ATR(14) to closed candles."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    frame["donchian_high"] = frame["high"].shift(1).rolling(params.channel_period).max()
    frame["donchian_low"] = frame["low"].shift(1).rolling(params.channel_period).min()
    frame["atr"] = atr(frame, params.atr_period)
    return frame


def _infer_direction(candle: pd.Series) -> str | None:
    """Direction proxy shared by the real entry path and Task 3's near-breakout random
    baseline: whichever of the N-period high/low the close sits CLOSER to. For a real
    breakout candle (close actually past one extreme) this trivially agrees with the
    breached side; for a merely-near candle (Task 3's eligible pool) this is the only
    direction signal available, by design."""
    donchian_high = candle.get("donchian_high")
    donchian_low = candle.get("donchian_low")
    if pd.isna(donchian_high) or pd.isna(donchian_low):
        return None
    close = float(candle["close"])
    dist_to_high = abs(close - float(donchian_high))
    dist_to_low = abs(close - float(donchian_low))
    return "LONG" if dist_to_high <= dist_to_low else "SHORT"


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: DonchianBracketParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Real breakout rule: LONG requires close STRICTLY above donchian_high, SHORT
    requires close STRICTLY below donchian_low — every rejection reason reported, not
    just the first. (This is stricter than Task 3's near-breakout random baseline,
    which draws from a wider "close enough" pool — see near_breakout_mask.)"""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    close = float(candle["close"])
    donchian_high = candle.get("donchian_high")
    donchian_low = candle.get("donchian_low")
    atr_value = candle.get("atr")

    direction: str | None = None
    if pd.isna(donchian_high) or pd.isna(donchian_low) or pd.isna(atr_value):
        reasons.append("INDICATORS_NOT_AVAILABLE")
    elif close > float(donchian_high):
        direction = "LONG"
    elif close < float(donchian_low):
        direction = "SHORT"
    else:
        reasons.append("NO_BREAKOUT")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=close,
        direction=direction,
        donchian_high=None if pd.isna(donchian_high) else float(donchian_high),
        donchian_low=None if pd.isna(donchian_low) else float(donchian_low),
        atr=None if pd.isna(atr_value) else float(atr_value),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: DonchianBracketParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional sizing against a 2x-ATR stop distance; target = target_r_multiple
    x that distance. Direction is INFERRED (see _infer_direction), not passed in — the
    real backtest loop only calls this after evaluate_entry has passed (where inference
    trivially agrees with the confirmed breakout side); Task 3's random baseline calls
    it directly on any eligible near-extreme candle, where inference is the intended
    mechanism-isolation behavior. Returns None if the risk/reward geometry is invalid."""
    direction = _infer_direction(candle)
    if direction is None:
        return None

    raw_entry = float(candle["close"])
    atr_value = candle.get("atr")
    if pd.isna(atr_value):
        return None
    atr_value = float(atr_value)

    if direction == "LONG":
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
        stop_loss = entry_price - params.atr_stop_multiple * atr_value
        risk_per_unit = entry_price - stop_loss
    else:
        entry_price = apply_slippage(raw_entry, params.slippage_bps, "sell")
        stop_loss = entry_price + params.atr_stop_multiple * atr_value
        risk_per_unit = stop_loss - entry_price
    if risk_per_unit <= 0:
        return None

    target = (
        entry_price + params.target_r_multiple * risk_per_unit
        if direction == "LONG"
        else entry_price - params.target_r_multiple * risk_per_unit
    )

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
        direction=direction, entry_price=entry_price, stop_loss=stop_loss, target=target,
        quantity=quantity, notional=notional, risk_dollars=risk_dollars, entry_fee=fees,
        open_close_time=int(candle["close_time"]), entry_atr=atr_value,
    )


def evaluate_exit(
    candle: pd.Series,
    state: MeanReversionState,
    params: DonchianBracketParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Bracket exit, direction-aware: LONG mirrors mean_reversion.evaluate_exit exactly
    (stop below, target above); SHORT mirrors short_momentum.evaluate_exit exactly
    (stop above, target below, PnL inverted). Same conservative stop-priority tie-break
    as both of those (if a candle's range hits both stop and target, the stop is
    assumed to have happened first) and the same max_holding_hours TIME exit."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    low = float(candle["low"])
    high = float(candle["high"])
    close = float(candle["close"])

    if trade.direction == "LONG":
        if low <= trade.stop_loss:
            exit_reason, raw_exit = "SL", trade.stop_loss
        elif high >= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        elif hours_held >= params.max_holding_hours:
            exit_reason, raw_exit = "TIME", close
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
        gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    else:
        if high >= trade.stop_loss:
            exit_reason, raw_exit = "SL", trade.stop_loss
        elif low <= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        elif hours_held >= params.max_holding_hours:
            exit_reason, raw_exit = "TIME", close
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "buy")
        gross_pnl = (trade.entry_price - exit_price) * trade.quantity

    exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r = state.daily_r + r_multiple
    state.open_trade = None

    return ExitEvent(
        exit_reason=exit_reason, exit_price=exit_price, gross_pnl=gross_pnl, fees=total_fees,
        net_pnl=net_pnl, r_multiple=r_multiple, holding_hours=hours_held, equity_after=equity_after,
    )


def near_breakout_mask(evaluable: pd.DataFrame, proximity_pct: float = 2.0) -> pd.Series:
    """Task 3's mechanism-validation eligible pool: candles where close is within
    `proximity_pct`% of EITHER the N-period high or the N-period low — a strict
    superset of the real strategy's exact-breakout trigger (an actual breakout is 0%
    away, comfortably inside the 2% band), used to test whether precise breakout
    TIMING adds anything over merely being near an extreme."""
    donchian_high = evaluable["donchian_high"].astype(float)
    donchian_low = evaluable["donchian_low"].astype(float)
    close = evaluable["close"].astype(float)
    near_high = close >= donchian_high * (1.0 - proximity_pct / 100.0)
    near_low = close <= donchian_low * (1.0 + proximity_pct / 100.0)
    return near_high | near_low


def run_donchian_bracket_backtest(
    candles: pd.DataFrame,
    params: DonchianBracketParameters = DEFAULT_PARAMETERS,
) -> tuple[list[ExitEvent], MeanReversionState]:
    """Candle-by-candle simulation, same shape/contract as every other strategy's own
    run_*_backtest in this codebase."""
    state = MeanReversionState(equity=params.initial_equity)
    enriched = add_indicators(candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
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


def register_variant(version: str, params: DonchianBracketParameters, description: str, registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register a specific N-preset/asset-calibrated bracket variant under STRATEGY_ID
    "DONCHIAN_TREND". Raises StrategyAlreadyRegisteredError if called twice with the
    same version string."""
    return registry.register(strategy_id=STRATEGY_ID, version=version, parameters=asdict(params), description=description)
