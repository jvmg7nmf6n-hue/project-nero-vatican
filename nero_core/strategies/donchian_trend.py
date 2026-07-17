"""DONCHIAN_TREND — classic (Turtle-style) channel breakout trend-follower, GOLD 1week
only. Purpose (per the pre-registered hypothesis): if a completely different trend
method (no RSI, no MA, no ATR-multiple stop) is ALSO positive on GOLD 1week, the edge
found by BREAKOUT_MOMENTUM there is more likely an asset property than an artifact of
that specific rule set.

ARCHITECTURE NOTE: like SHORT_MOMENTUM and COINTEGRATION_PAIRS, this strategy doesn't
fit the shared long-only evaluate_exit in mean_reversion.py, for a different reason
than those two: its exit is a TRAILING channel level re-evaluated every candle (close
below the CURRENT rolling 10-period Donchian low), not a fixed stop/target price frozen
at entry. There is deliberately no max_holding_hours field and no fixed target — see
DonchianTrendParameters' docstring.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, reset_daily_guard_if_needed
from nero_core.strategies.mean_reversion_gold_calibrated import GOLD_FEE_SCALE_FACTOR
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "DONCHIAN_TREND"
STRATEGY_VERSION = "donchian-trend-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Long-only Donchian channel breakout trend-follower, GOLD 1week only. Entry: close "
    "breaks above the 20-period Donchian high computed over the PRIOR 20 candles "
    "(excluding the current candle — the current candle's own high never counts toward "
    "its own breakout threshold, matching BREAKOUT_MOMENTUM's shift(1) convention). "
    "Initial risk = entry_price minus the 10-period Donchian low over the prior 10 "
    "candles at entry; entry is skipped if that distance is zero or negative. Sizing is "
    "standard 1% fixed-fractional on that initial risk distance, and R is always "
    "measured against that INITIAL distance, not the (rising) trailing level. Exit: "
    "close drops below the CURRENT rolling 10-period Donchian low (a genuine trailing "
    "stop that rises as the trend extends) — there is deliberately no fixed target and "
    "no max-holding-hours cap; a channel trend-follower needs room to let a real trend "
    "run, and capping holding time would cut exactly the trades this strategy exists to "
    "catch. Fees are GOLD-calibrated (scaled by the measured BTC/GOLD price-to-ATR "
    "ratio from nero_core.strategies.mean_reversion_gold_calibrated) since this "
    "strategy has no crypto-scoped sibling to default to crypto fees against."
)


@dataclass(frozen=True)
class DonchianTrendParameters:
    """No max_holding_hours field and no fixed-target field at all — this is a
    deliberate registry-level parameter decision (not an omission): a channel
    trend-follower's whole edge depends on staying in a trade as long as the trend
    holds, which a time cap or fixed R target would directly work against."""

    entry_channel_period: int = 20
    exit_channel_period: int = 10
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    # GOLD-calibrated from the start (see mean_reversion_gold_calibrated.py for the
    # measured BTC/GOLD price-to-ATR scale-factor derivation) — this strategy has no
    # crypto counterpart, so there is no "default" crypto fee to keep separate.
    fee_bps: float = 10.0 * GOLD_FEE_SCALE_FACTOR
    slippage_bps: float = 2.0 * GOLD_FEE_SCALE_FACTOR
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = DonchianTrendParameters()


@dataclass
class OpenTrade:
    entry_price: float
    quantity: float
    notional: float
    risk_dollars: float  # fixed at entry — computed from the INITIAL channel distance
    entry_fee: float
    open_close_time: int
    entry_channel_high: float
    entry_exit_low: float  # the trailing-exit channel's value AT entry (informational)


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    entry_channel_high: float | None
    exit_channel_low: float | None
    risk_distance: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # always "TRAIL_EXIT" — no SL/TARGET/TIME categories for this strategy
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float


def add_indicators(candles: pd.DataFrame, params: DonchianTrendParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach the entry (20-period) and exit (10-period) Donchian channels to closed
    candles. Both use `.shift(1)` before the rolling window, so row i's channel values
    only ever reflect candles strictly before i — no lookahead, and a candle can
    actually break out of its own entry channel (the bug the hypothesis explicitly
    calls out: without the shift, close could never exceed a channel that includes its
    own high)."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    frame["entry_channel_high"] = frame["high"].shift(1).rolling(params.entry_channel_period).max()
    frame["exit_channel_low"] = frame["low"].shift(1).rolling(params.exit_channel_period).min()
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: DonchianTrendParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Evaluate the Donchian breakout rule set against one closed candle. Every
    rejection reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    close = float(candle["close"])
    entry_channel_high = candle.get("entry_channel_high")
    exit_channel_low = candle.get("exit_channel_low")

    if pd.isna(entry_channel_high) or close <= float(entry_channel_high):
        reasons.append("CLOSE_NOT_ABOVE_ENTRY_CHANNEL")

    risk_distance = None
    if pd.isna(exit_channel_low):
        reasons.append("RISK_DISTANCE_NOT_POSITIVE")
    else:
        risk_distance = close - float(exit_channel_low)
        if risk_distance <= 0:
            reasons.append("RISK_DISTANCE_NOT_POSITIVE")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=close,
        entry_channel_high=None if pd.isna(entry_channel_high) else float(entry_channel_high),
        exit_channel_low=None if pd.isna(exit_channel_low) else float(exit_channel_low),
        risk_distance=risk_distance,
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: DonchianTrendParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional sizing against the INITIAL channel-implied risk distance.
    Returns None if that distance isn't positive — callers should only invoke this
    after `evaluate_entry` has passed (which already guarantees a positive distance,
    this is a defensive re-check)."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    exit_channel_low = candle.get("exit_channel_low")
    if pd.isna(exit_channel_low):
        return None
    risk_per_unit = entry_price - float(exit_channel_low)
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

    entry_channel_high = candle.get("entry_channel_high")
    return OpenTrade(
        entry_price=entry_price,
        quantity=quantity,
        notional=notional,
        risk_dollars=risk_dollars,
        entry_fee=fees,
        open_close_time=int(candle["close_time"]),
        entry_channel_high=float(entry_channel_high) if not pd.isna(entry_channel_high) else float("nan"),
        entry_exit_low=float(exit_channel_low),
    )


def evaluate_exit(
    candle: pd.Series,
    state: MeanReversionState,
    params: DonchianTrendParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Trailing exit: close below the CURRENT (rolling, updated every candle) 10-period
    Donchian low — not a price frozen at entry. No stop/target/time categories: there is
    exactly one exit condition for this strategy, by design."""
    trade = state.open_trade
    if trade is None:
        return None

    exit_channel_low = candle.get("exit_channel_low")
    if pd.isna(exit_channel_low):
        return None

    close = float(candle["close"])
    if close >= float(exit_channel_low):
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    exit_price = apply_slippage(close, params.slippage_bps, "sell")
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

    return ExitEvent(
        exit_reason="TRAIL_EXIT",
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        holding_hours=hours_held,
        equity_after=equity_after,
    )


INDICATOR_COLUMNS_TO_CHECK = ["entry_channel_high", "exit_channel_low"]


def run_donchian_backtest(
    candles: pd.DataFrame,
    params: DonchianTrendParameters = DEFAULT_PARAMETERS,
) -> tuple[list[ExitEvent], MeanReversionState]:
    """Candle-by-candle simulation — same shape/contract as
    tools.backtest_compare.run_backtest, but wired to this module's own trailing exit
    instead of the shared fixed-price long-only one."""
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
    """Register the Donchian Trend strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
