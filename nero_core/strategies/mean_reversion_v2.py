from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.quant.quant_intelligence import build_garch_volatility_report
from nero_core.strategies.mean_reversion import (
    STRATEGY_ID,
    EntryEvaluation,
    MeanReversionParameters,
    MeanReversionState,
    add_indicators,
    evaluate_entry as evaluate_entry_v1,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "mean-reversion-v2.0.0-regime-filtered"

# GARCH/EWMA volatility regimes (from nero_core.quant.quant_intelligence) under which a
# NEW mean-reversion long entry is allowed. VOL_STRESS and VOL_ELEVATED are excluded on
# purpose: buying an oversold dip assumes the pullback will revert, and that assumption is
# weakest exactly when volatility clustering says a further shock is likely. VOL_NORMAL and
# VOL_COMPRESSED are the regimes the original strategy's rule set was actually designed for.
FAVORABLE_VOLATILITY_REGIMES: tuple[str, ...] = ("VOL_NORMAL", "VOL_COMPRESSED")

STRATEGY_DESCRIPTION = (
    "Same entry/exit rules as MEAN_REVERSION mean-reversion-v1.0.0 (RSI<35, close below "
    "lower Bollinger Band, close above MA200, MA20 frozen target), plus two additional "
    "entry gates: (a) a volatility-regime filter that blocks entries when the GARCH/EWMA "
    "regime is VOL_STRESS or VOL_ELEVATED, and (b) a higher-timeframe confirmation that "
    "blocks entries when the daily trend is in a confirmed Bear regime (mirrors the "
    "Bull/Bear/Range threshold convention already used in quant_intelligence's regime "
    "classifier: -3%/-5% on the 20D/60D daily trend)."
)


@dataclass(frozen=True)
class MeanReversionV2Parameters(MeanReversionParameters):
    """All of MeanReversionParameters' fields (same defaults, same core entry/exit rules),
    plus the two new v2 filter thresholds."""

    favorable_volatility_regimes: tuple[str, ...] = FAVORABLE_VOLATILITY_REGIMES
    higher_timeframe_short_window: int = 20
    higher_timeframe_long_window: int = 60
    higher_timeframe_bear_short_threshold: float = -0.03
    higher_timeframe_bear_long_threshold: float = -0.05
    min_higher_timeframe_observations: int = 60
    min_volatility_observations: int = 60


DEFAULT_V2_PARAMETERS = MeanReversionV2Parameters()


def _higher_timeframe_trend_is_bearish(
    daily_price_history: pd.DataFrame,
    params: MeanReversionV2Parameters,
) -> bool | None:
    """Returns True if the daily trend is a confirmed Bear regime (contradicts a long
    entry), False if not, None if there isn't enough daily history to judge at all."""
    if daily_price_history is None or daily_price_history.empty or "close" not in daily_price_history.columns:
        return None
    closes = pd.to_numeric(daily_price_history["close"], errors="coerce").dropna()
    long_window = params.higher_timeframe_long_window
    short_window = params.higher_timeframe_short_window
    if len(closes) < max(params.min_higher_timeframe_observations, long_window + 1):
        return None

    trend_short = float(closes.iloc[-1] / closes.iloc[-short_window - 1] - 1)
    trend_long = float(closes.iloc[-1] / closes.iloc[-long_window - 1] - 1)
    return trend_short < params.higher_timeframe_bear_short_threshold and trend_long < params.higher_timeframe_bear_long_threshold


def evaluate_entry_v2(
    candle: pd.Series,
    price_history: pd.DataFrame,
    daily_price_history: pd.DataFrame,
    state: MeanReversionState,
    params: MeanReversionV2Parameters = DEFAULT_V2_PARAMETERS,
    asset: str = "",
) -> EntryEvaluation:
    """v1's entry rules plus a volatility-regime filter and a higher-timeframe
    confirmation. `price_history` is the same entry-timeframe (e.g. 1h) closed-candle
    series used for indicators; `daily_price_history` is an independent higher-timeframe
    (daily) closed-candle series used only for the trend-contradiction check."""
    base = evaluate_entry_v1(candle, state, params)
    reasons = list(base.reasons)

    if price_history is None or price_history.empty or len(price_history) < params.min_volatility_observations:
        reasons.append("REGIME_FILTER_INSUFFICIENT_VOLATILITY_DATA")
    else:
        garch_report = build_garch_volatility_report(price_history, asset)
        if garch_report.regime == "NO_DATA":
            reasons.append("REGIME_FILTER_INSUFFICIENT_VOLATILITY_DATA")
        elif garch_report.regime not in params.favorable_volatility_regimes:
            reasons.append(f"REGIME_FILTER_UNFAVORABLE_VOLATILITY_{garch_report.regime}")

    is_bearish = _higher_timeframe_trend_is_bearish(daily_price_history, params)
    if is_bearish is None:
        reasons.append("HIGHER_TIMEFRAME_INSUFFICIENT_DATA")
    elif is_bearish:
        reasons.append("HIGHER_TIMEFRAME_TREND_CONTRADICTS")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=base.candle_close_time,
        close=base.close,
        rsi=base.rsi,
        ma20=base.ma20,
        bb_lower=base.bb_lower,
        ma200=base.ma200,
        atr=base.atr,
    )


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the v2 (regime-filtered) Mean Reversion variant under the SAME
    strategy_id as v1, but a distinct version string — proving the registry's versioning
    model with two real, independently evaluable variants of one strategy."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_V2_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
