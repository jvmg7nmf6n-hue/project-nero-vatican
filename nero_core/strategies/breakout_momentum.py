from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import (
    MeanReversionState,
    apply_slippage,
    atr,
    evaluate_exit,
    reset_daily_guard_if_needed,
    rsi,
)
from nero_core.strategies.regime_risk import atr_pct_rolling_median, regime_scaled_risk_per_trade
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "BREAKOUT_MOMENTUM"
STRATEGY_VERSION = "breakout-momentum-v1.0.0"

STRATEGY_DESCRIPTION = (
    "20-bar breakout momentum: close above the prior 20-bar high, close above MA200, "
    "RSI >= 50, fixed 1.25R target, 1.2x ATR stop. Ported from the original NERO "
    "strategy_lab_agent.py BREAKOUT_MOMENTUM_V1 candidate (CandidateSpec family="
    "'Momentum'). Unlike the Mean Reversion family, this buys strength rather than "
    "dips — it never triggers a SHORT; entries are long-only. State, exit logic "
    "(stop/target/time-based), slippage, and RSI/ATR indicators are reused unchanged "
    "from nero_core.strategies.mean_reversion — only entry conditions and target "
    "sizing differ between the two families, matching how the original shared one "
    "MeanReversionAgent base class across both."
)


@dataclass(frozen=True)
class BreakoutMomentumParameters:
    """Strategy behavior parameters — the exact defaults from the original
    BREAKOUT_MOMENTUM_V1 CandidateSpec."""

    rsi_period: int = 14
    rsi_momentum_min: float = 50.0
    breakout_lookback: int = 20
    ma200_period: int = 200
    atr_period: int = 14
    atr_stop_multiple: float = 1.2
    reward_multiple: float = 1.25
    max_holding_hours: int = 24
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0
    # H3 hypothesis (see nero_core.strategies.regime_risk): when True, risk_per_trade is
    # scaled per-trade by clamp(median_trailing_ATRpct / current_ATRpct, 0.5, 2.0).
    # Default False preserves the original fixed risk_per_trade exactly.
    regime_scaled_risk: bool = False
    # H4 hypothesis: when True, entry additionally requires the entry candle's own
    # volume to exceed volume_multiple x the average volume of the prior 20 candles
    # (excluding the entry candle itself). Default False preserves v1.0.0 exactly — see
    # breakout_momentum_volume_confirmed.py for the variant that turns this on.
    volume_confirmed: bool = False
    volume_multiple: float = 1.5
    volume_lookback: int = 20


DEFAULT_PARAMETERS = BreakoutMomentumParameters()


@dataclass
class OpenTrade:
    """Own OpenTrade shape (no Mean Reversion-specific fields like ma20/bb_lower, which
    don't apply here). Duck-types against evaluate_exit's needs: open_close_time,
    stop_loss, target, quantity, entry_price, entry_fee, risk_dollars."""

    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_rsi: float
    entry_ma200: float
    entry_atr: float
    entry_breakout_high: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    rsi: float
    ma200: float
    atr: float
    breakout_high: float | None


def add_indicators(candles: pd.DataFrame, params: BreakoutMomentumParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach MA200/RSI/ATR/breakout-high to closed candles. `breakout_high` uses
    shift(1) before the rolling max, so a candle's own high never counts toward its own
    breakout threshold — no lookahead: row i only ever sees highs from rows < i."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["ma200"] = close.rolling(params.ma200_period).mean()
    frame["rsi"] = rsi(close, params.rsi_period)
    frame["atr"] = atr(frame, params.atr_period)
    frame["breakout_high"] = frame["high"].shift(1).rolling(params.breakout_lookback).max()
    # Always computed (cheap) regardless of regime_scaled_risk — only consumed by
    # size_entry when that flag is on; unused otherwise, matching v1's exact behavior.
    frame["atr_pct_median100"] = atr_pct_rolling_median(close, frame["atr"])
    # H4 hypothesis: prior-20-candle average volume, excluding the entry candle's own
    # volume (shift(1) before the rolling mean, same no-lookahead convention as
    # breakout_high). Always computed (cheap); only consumed when volume_confirmed=True.
    frame["avg_volume_prior"] = frame["volume"].shift(1).rolling(params.volume_lookback).mean()
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: BreakoutMomentumParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Evaluate the breakout-momentum rule set against one closed candle. Every
    rejection reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    breakout_high = candle.get("breakout_high")
    if pd.isna(breakout_high) or float(candle["close"]) <= float(breakout_high):
        reasons.append("CLOSE_NOT_ABOVE_BREAKOUT_HIGH")
    if float(candle["close"]) <= float(candle["ma200"]):
        reasons.append("CLOSE_NOT_ABOVE_MA200")
    if float(candle["rsi"]) < params.rsi_momentum_min:
        reasons.append("RSI_NOT_MOMENTUM_SUPPORTIVE")
    if params.volume_confirmed:
        avg_volume_prior = candle.get("avg_volume_prior")
        if pd.isna(avg_volume_prior) or float(candle["volume"]) <= params.volume_multiple * float(avg_volume_prior):
            reasons.append("VOLUME_NOT_CONFIRMED")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=float(candle["close"]),
        rsi=float(candle["rsi"]),
        ma200=float(candle["ma200"]),
        atr=float(candle["atr"]),
        breakout_high=None if pd.isna(breakout_high) else float(breakout_high),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: BreakoutMomentumParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional position sizing with a fixed 1.25R target (entry + reward_multiple
    * risk_per_unit) rather than Mean Reversion's floating MA20 target. Returns None if
    the risk geometry is invalid — callers should only invoke this after `evaluate_entry`
    has passed."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    stop_loss = entry_price - params.atr_stop_multiple * float(candle["atr"])
    risk_per_unit = entry_price - stop_loss
    if risk_per_unit <= 0:
        return None

    target = entry_price + params.reward_multiple * risk_per_unit
    reward_per_unit = target - entry_price
    if reward_per_unit <= 0:
        return None

    risk_per_trade = params.risk_per_trade
    if params.regime_scaled_risk:
        current_atr_pct = float(candle["atr"]) / raw_entry if raw_entry != 0 else float("nan")
        risk_per_trade = regime_scaled_risk_per_trade(
            params.risk_per_trade, candle.get("atr_pct_median100"), current_atr_pct
        )
    risk_dollars = state.equity * risk_per_trade
    quantity = risk_dollars / risk_per_unit
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * risk_per_unit
    fees = notional * params.fee_bps / 10000.0

    breakout_high = candle.get("breakout_high")
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
        entry_breakout_high=float(breakout_high) if not pd.isna(breakout_high) else float("nan"),
    )


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the Breakout Momentum strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
