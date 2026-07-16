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
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "TREND_PULLBACK"
STRATEGY_VERSION = "trend-pullback-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Long-only trend-pullback: established uptrend (close > MA200 AND MA50 > MA200), "
    "entry when the PRIOR candle's close came within 1x ATR of MA50 (a pullback toward "
    "the intermediate trendline) and the CURRENT candle's close is back above MA50, with "
    "RSI between 40 and 60 (neither oversold nor overbought — a continuation signal, not "
    "a dip-buying one). Exit: 1.5x ATR(14) stop, 2.0x ATR(14) fixed target, "
    "timeframe-aware max holding (see nero_core.strategies.timeframe_calibration — "
    "max_holding_hours on this dataclass is a 1h-reference default, not meant to be used "
    "as-is against non-hourly candles). State, slippage, and stop/target/time exit "
    "mechanics are reused unchanged from nero_core.strategies.mean_reversion — only entry "
    "conditions and target sizing are new."
)


@dataclass(frozen=True)
class TrendPullbackParameters:
    rsi_period: int = 14
    rsi_lower: float = 40.0
    rsi_upper: float = 60.0
    ma50_period: int = 50
    ma200_period: int = 200
    pullback_atr_buffer: float = 1.0
    atr_period: int = 14
    atr_stop_multiple: float = 1.5
    atr_target_multiple: float = 2.0
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


DEFAULT_PARAMETERS = TrendPullbackParameters()


@dataclass
class OpenTrade:
    """Duck-types against evaluate_exit's needs: open_close_time, stop_loss, target,
    quantity, entry_price, entry_fee, risk_dollars (same contract as BREAKOUT_MOMENTUM's
    and VOLATILITY_SQUEEZE's OpenTrade)."""

    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    entry_rsi: float
    entry_ma50: float
    entry_ma200: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    rsi: float
    ma50: float
    ma200: float
    atr: float


def add_indicators(candles: pd.DataFrame, params: TrendPullbackParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach MA50/MA200/RSI/ATR and a "prior candle pulled back near MA50" flag to
    closed candles. No lookahead: `prior_near_ma50` is built from `.shift(1)` values, so
    row i only ever reflects information available BEFORE candle i — the pullback must
    have already happened on the candle before the one being evaluated as a breakout-back-
    above-MA50 entry."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["ma50"] = close.rolling(params.ma50_period).mean()
    frame["ma200"] = close.rolling(params.ma200_period).mean()
    frame["rsi"] = rsi(close, params.rsi_period)
    frame["atr"] = atr(frame, params.atr_period)
    # "within 1x ATR of MA50" = absolute distance, not just below it — a pullback can dip
    # from above down toward the line without necessarily crossing under it.
    distance_to_ma50 = (close - frame["ma50"]).abs()
    frame["prior_near_ma50"] = (distance_to_ma50 <= params.pullback_atr_buffer * frame["atr"]).shift(1).fillna(False)
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: TrendPullbackParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Evaluate the trend-pullback rule set against one closed candle. Every rejection
    reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    close = float(candle["close"])
    ma50 = float(candle["ma50"])
    ma200 = float(candle["ma200"])
    rsi_value = float(candle["rsi"])

    if close <= ma200 or ma50 <= ma200:
        reasons.append("NOT_IN_ESTABLISHED_UPTREND")
    if not bool(candle.get("prior_near_ma50", False)):
        reasons.append("NO_RECENT_PULLBACK_TO_MA50")
    if close <= ma50:
        reasons.append("CLOSE_NOT_BACK_ABOVE_MA50")
    if rsi_value < params.rsi_lower or rsi_value > params.rsi_upper:
        reasons.append("RSI_OUTSIDE_NEUTRAL_BAND")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=close,
        rsi=rsi_value,
        ma50=ma50,
        ma200=ma200,
        atr=float(candle["atr"]),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: TrendPullbackParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional position sizing: stop = 1.5x ATR, target = 2.0x ATR (both
    independent fixed ATR multiples). Returns None if the risk/reward geometry is
    invalid — callers should only invoke this after `evaluate_entry` has passed."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    entry_atr = float(candle["atr"])
    stop_loss = entry_price - params.atr_stop_multiple * entry_atr
    target = entry_price + params.atr_target_multiple * entry_atr
    risk_per_unit = entry_price - stop_loss
    reward_per_unit = target - entry_price
    if risk_per_unit <= 0 or reward_per_unit <= 0:
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
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        quantity=quantity,
        notional=notional,
        risk_dollars=risk_dollars,
        entry_fee=fees,
        open_close_time=int(candle["close_time"]),
        entry_atr=entry_atr,
        entry_rsi=float(candle["rsi"]),
        entry_ma50=float(candle["ma50"]),
        entry_ma200=float(candle["ma200"]),
    )


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the Trend Pullback strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
