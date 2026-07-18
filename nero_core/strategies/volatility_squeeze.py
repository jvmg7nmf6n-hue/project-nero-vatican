from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import pandas as pd

from nero_core.strategies.mean_reversion import (
    MeanReversionState,
    apply_slippage,
    atr,
    evaluate_exit,
    reset_daily_guard_if_needed,
)
from nero_core.strategies.mean_reversion_gold_calibrated import GOLD_FEE_SCALE_FACTOR
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry
from nero_core.strategies.timeframe_calibration import scaled_fees_for_asset

STRATEGY_ID = "VOLATILITY_SQUEEZE"

STRATEGY_DESCRIPTION_TEMPLATE = (
    "Long-only Bollinger Band volatility-squeeze breakout: (1) BB width (20-period, 2 std; "
    "width = (upper-lower)/middle) sits in the lowest {percentile:.0f}th percentile of its "
    "trailing {lookback}-candle history for at least {min_candles} CONSECUTIVE candles — "
    "this run of narrow-width candles is 'the squeeze'; (2) close breaks above the highest "
    "high reached during that squeeze run; (3) close > MA{trend_ma_period} (trend filter). "
    "Exit: 1.5x ATR(14) stop, 2.0x ATR(14) fixed target, timeframe-aware max holding (see "
    "max_holding_hours_for_timeframe — max_holding_hours on this dataclass is a 1h-reference "
    "default only, not meant to be used as-is against non-hourly candles, same lesson as the "
    "GOLD 1week max_holding_hours fix on MEAN_REVERSION/BREAKOUT_MOMENTUM). State, slippage, "
    "and stop/target/time exit mechanics are reused unchanged from nero_core.strategies."
    "mean_reversion — only entry conditions and target sizing are new."
)


@dataclass(frozen=True)
class VolatilitySqueezeParameters:
    """Strategy behavior parameters. `trend_ma_period` is the one field the three
    registered variants (ma200/ma150/ma100) differ on — everything else is identical
    across variants."""

    bb_period: int = 20
    bb_std: float = 2.0
    squeeze_lookback: int = 100
    squeeze_percentile: float = 0.20
    min_squeeze_candles: int = 5
    trend_ma_period: int = 200
    atr_period: int = 14
    atr_stop_multiple: float = 1.5
    atr_target_multiple: float = 2.0
    # 1h-reference default, matching the ORIGINAL (pre-fix) convention used by
    # MEAN_REVERSION/BREAKOUT_MOMENTUM. Any caller backtesting at a different candle
    # interval MUST re-derive this via max_holding_hours_for_timeframe() below instead of
    # using this raw default — see mean_reversion_gold_calibrated_1week.py for the bug
    # this exact mistake caused when skipped.
    max_holding_hours: int = 24
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS_MA200 = VolatilitySqueezeParameters(trend_ma_period=200)
DEFAULT_PARAMETERS_MA150 = VolatilitySqueezeParameters(trend_ma_period=150)
DEFAULT_PARAMETERS_MA100 = VolatilitySqueezeParameters(trend_ma_period=100)

STRATEGY_VERSION_MA200 = "volatility-squeeze-v1.0.0-ma200"
STRATEGY_VERSION_MA150 = "volatility-squeeze-v1.0.0-ma150"
STRATEGY_VERSION_MA100 = "volatility-squeeze-v1.0.0-ma100"

# Same candle-duration table used to fix MEAN_REVERSION/BREAKOUT_MOMENTUM's GOLD 1week bug
# (nero_core.strategies.mean_reversion_gold_calibrated_1week) — kept here too since this
# strategy is designed from day one to run across the full standard timeframe set, not
# retrofitted after the fact.
HOURS_PER_TIMEFRAME = {"2h": 2, "4h": 4, "12h": 12, "24h": 24, "1week": 168}
ORIGINAL_MAX_HOLDING_CANDLES = 24  # preserve "hold up to 24 candles" regardless of timeframe


def max_holding_hours_for_timeframe(timeframe: str, candles: int = ORIGINAL_MAX_HOLDING_CANDLES) -> int:
    """Convert a candle-count holding cap into hours for `timeframe`. Raises KeyError for
    an unrecognized timeframe rather than silently defaulting — a wrong holding cap is
    exactly the bug this function exists to prevent."""
    return candles * HOURS_PER_TIMEFRAME[timeframe]


def gold_calibrated_fees(params: VolatilitySqueezeParameters) -> VolatilitySqueezeParameters:
    """Return `params` with fee_bps/slippage_bps scaled by the measured BTC/GOLD
    price-to-ATR ratio (nero_core.strategies.mean_reversion_gold_calibrated). Reused, not
    re-derived: ATR itself is computed identically regardless of strategy family, so this
    is an instrument characteristic, not something specific to Mean Reversion, Breakout
    Momentum, or Volatility Squeeze."""
    return replace(
        params,
        fee_bps=params.fee_bps * GOLD_FEE_SCALE_FACTOR,
        slippage_bps=params.slippage_bps * GOLD_FEE_SCALE_FACTOR,
    )


def build_params_for_run(base_params: VolatilitySqueezeParameters, timeframe: str, asset: str) -> VolatilitySqueezeParameters:
    """Build the correctly-calibrated, correctly-timeframed parameter set for one
    asset/timeframe backtest run, without mutating or re-registering `base_params` — the
    registered strategy variant's canonical parameters never change; this only produces an
    ephemeral, honestly-derived clone for the run at hand (the same relationship
    VARIANT_SPECS already has with GOLD_CALIBRATED_PARAMETERS in backtest_compare.py).
    Delegates fee scaling to timeframe_calibration.scaled_fees_for_asset so SILVER/
    PLATINUM (and any future non-GOLD, non-crypto asset) get the same treatment GOLD
    always has, instead of a GOLD-only special case."""
    params = replace(base_params, max_holding_hours=max_holding_hours_for_timeframe(timeframe))
    return scaled_fees_for_asset(params, asset)


@dataclass
class OpenTrade:
    """Duck-types against evaluate_exit's needs: open_close_time, stop_loss, target,
    quantity, entry_price, entry_fee, risk_dollars (same contract as BREAKOUT_MOMENTUM's
    OpenTrade)."""

    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    entry_trend_ma: float
    entry_bb_width: float
    entry_squeeze_streak: int
    entry_squeeze_run_high: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    bb_width: float | None
    squeeze_streak: int
    squeeze_run_high: float | None
    trend_ma: float


def add_indicators(candles: pd.DataFrame, params: VolatilitySqueezeParameters = DEFAULT_PARAMETERS_MA200) -> pd.DataFrame:
    """Attach BB width/percentile/squeeze-streak/trend-MA/ATR to closed candles. No
    lookahead: every value at row i only uses candles up to and including i, and the two
    "prior_*" columns are explicitly shifted so evaluate_entry only ever reads what was
    already known at the START of candle i (i.e. as of candle i-1's close).

    Interpretation note on the "3 shared entry rules": rule (1) — BB width in the lowest
    squeeze_percentile of its trailing history — defines which candles count as
    "squeeze-condition candles" used to build the consecutive streak; it is NOT re-checked
    on the breakout candle itself (a real breakout typically ends the squeeze, so the
    breakout candle's own width is usually no longer in the squeeze). Rule (2) is
    evaluated against that already-built streak. This matches "close breaks above the
    highest high of the consecutive squeeze-condition candles" read literally: the streak
    candles are the ones BEFORE the breakout, not the breakout candle."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)

    bb_middle = close.rolling(params.bb_period).mean()
    bb_std = close.rolling(params.bb_period).std(ddof=0)
    bb_upper = bb_middle + params.bb_std * bb_std
    bb_lower = bb_middle - params.bb_std * bb_std
    bb_width = (bb_upper - bb_lower) / bb_middle

    width_p20 = bb_width.rolling(params.squeeze_lookback).quantile(params.squeeze_percentile)
    squeeze_flag = bb_width <= width_p20

    run_id = (~squeeze_flag).cumsum()
    squeeze_streak = squeeze_flag.astype(int).groupby(run_id).cumsum()
    squeeze_run_high = high.groupby(run_id).cummax()

    frame["bb_middle"] = bb_middle
    frame["bb_upper"] = bb_upper
    frame["bb_lower"] = bb_lower
    frame["bb_width"] = bb_width
    frame["width_p20"] = width_p20
    frame["squeeze_streak"] = squeeze_streak
    # "prior_*" = as-of the candle immediately BEFORE this one — what evaluate_entry may
    # legitimately use when deciding whether row i is a breakout.
    frame["prior_squeeze_streak"] = squeeze_streak.shift(1).fillna(0)
    frame["prior_squeeze_run_high"] = squeeze_run_high.shift(1)
    frame["trend_ma"] = close.rolling(params.trend_ma_period).mean()
    frame["atr"] = atr(frame, params.atr_period)
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: VolatilitySqueezeParameters = DEFAULT_PARAMETERS_MA200,
) -> EntryEvaluation:
    """Evaluate the volatility-squeeze rule set against one closed candle. Every
    rejection reason is reported, not just the first, so trend-filter blocks (and every
    other reason) can be tallied across a full backtest run."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    prior_streak = float(candle.get("prior_squeeze_streak", 0.0) or 0.0)
    prior_run_high = candle.get("prior_squeeze_run_high")
    streak_long_enough = prior_streak >= params.min_squeeze_candles
    if not streak_long_enough:
        reasons.append("SQUEEZE_STREAK_TOO_SHORT")
    if pd.isna(prior_run_high) or not streak_long_enough or float(candle["close"]) <= float(prior_run_high):
        reasons.append("CLOSE_NOT_ABOVE_SQUEEZE_HIGH")

    trend_ma = candle.get("trend_ma")
    if pd.isna(trend_ma) or float(candle["close"]) <= float(trend_ma):
        reasons.append("CLOSE_NOT_ABOVE_TREND_MA")

    bb_width = candle.get("bb_width")
    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=float(candle["close"]),
        bb_width=None if pd.isna(bb_width) else float(bb_width),
        squeeze_streak=int(candle.get("squeeze_streak", 0) or 0),
        squeeze_run_high=None if pd.isna(prior_run_high) else float(prior_run_high),
        trend_ma=float(trend_ma) if not pd.isna(trend_ma) else float("nan"),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: VolatilitySqueezeParameters = DEFAULT_PARAMETERS_MA200,
) -> OpenTrade | None:
    """Fixed-fractional position sizing: stop = 1.5x ATR, target = 2.0x ATR (both
    independent fixed ATR multiples, not a reward-multiple-of-risk target). Returns None
    if the risk/reward geometry is invalid — callers should only invoke this after
    `evaluate_entry` has passed."""
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

    prior_run_high = candle.get("prior_squeeze_run_high")
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
        entry_trend_ma=float(candle["trend_ma"]),
        entry_bb_width=float(candle["bb_width"]),
        entry_squeeze_streak=int(candle.get("prior_squeeze_streak", 0) or 0),
        entry_squeeze_run_high=float(prior_run_high) if not pd.isna(prior_run_high) else float("nan"),
    )


def _register(registry: StrategyRegistry, version: str, params: VolatilitySqueezeParameters) -> StrategyVariant:
    description = STRATEGY_DESCRIPTION_TEMPLATE.format(
        percentile=params.squeeze_percentile * 100.0,
        lookback=params.squeeze_lookback,
        min_candles=params.min_squeeze_candles,
        trend_ma_period=params.trend_ma_period,
    )
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=version,
        parameters=asdict(params),
        description=description,
    )


def register_ma200_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    return _register(registry, STRATEGY_VERSION_MA200, DEFAULT_PARAMETERS_MA200)


def register_ma150_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    return _register(registry, STRATEGY_VERSION_MA150, DEFAULT_PARAMETERS_MA150)


def register_ma100_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    return _register(registry, STRATEGY_VERSION_MA100, DEFAULT_PARAMETERS_MA100)


def register_all_variants(registry: StrategyRegistry = default_registry) -> tuple[StrategyVariant, StrategyVariant, StrategyVariant]:
    """Register all three VOLATILITY_SQUEEZE trend-filter variants (ma200, ma150, ma100)
    simultaneously, as three separate explicit versions of the same strategy_id — never
    three silent parameter mutations of one version."""
    return (
        register_ma200_variant(registry),
        register_ma150_variant(registry),
        register_ma100_variant(registry),
    )
