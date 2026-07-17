"""Shared regime-scaled risk-budget helper (H3 hypothesis): scale the per-trade RISK
BUDGET (the fraction of equity risked) by the current volatility regime, as a variable
distinct from ATR-based position SIZE normalization (which every fixed-fractional
strategy in this codebase already does — quantity = risk_dollars / (ATR-based distance)
already shrinks size when ATR is high and grows it when ATR is low). This tests
scaling risk_dollars ITSELF by how the current candle's ATR% compares to its own
trailing distribution, on top of that existing size normalization.

risk_multiplier = clamp(median_trailing_ATR% / current_ATR%, 0.5, 2.0)

- ATR% = ATR / close (volatility relative to price, comparable across price levels).
- median_trailing_ATR% is the rolling median of ATR% over the trailing 100 CLOSED
  candles ENDING AT AND INCLUDING the entry candle — a standard trailing (backward-only)
  rolling window, no shift needed: the entry candle's own ATR/close are already known,
  closed data at decision time, so including it introduces no lookahead (identical
  convention to every other rolling indicator already used in this codebase, e.g. MA200).
- When current ATR% is ABOVE its trailing median (a higher-than-usual volatility
  regime), the ratio is < 1 -> risk budget shrinks. When current ATR% is BELOW its
  trailing median (a calmer regime), the ratio is > 1 -> risk budget grows, clamped to
  at most 2x so a very quiet regime can't blow past a sane per-trade risk cap.
"""
from __future__ import annotations

import pandas as pd

ATR_PCT_MEDIAN_WINDOW = 100
RISK_MULTIPLIER_CLAMP_MIN = 0.5
RISK_MULTIPLIER_CLAMP_MAX = 2.0


def atr_pct_rolling_median(close: pd.Series, atr: pd.Series, window: int = ATR_PCT_MEDIAN_WINDOW) -> pd.Series:
    """Rolling median of ATR% (ATR/close) over the trailing `window` candles, ending at
    and including each row. No lookahead: row i only ever uses rows <= i."""
    atr_pct = atr / close.replace(0, float("nan"))
    return atr_pct.rolling(window).median()


def regime_scaled_risk_per_trade(
    base_risk_per_trade: float,
    median_atr_pct: float,
    current_atr_pct: float,
    clamp_min: float = RISK_MULTIPLIER_CLAMP_MIN,
    clamp_max: float = RISK_MULTIPLIER_CLAMP_MAX,
) -> float:
    """Returns the scaled risk_per_trade. Falls back to the unscaled base value if the
    inputs aren't usable (NaN median/current, or non-positive current ATR%) rather than
    silently producing a nonsensical multiplier."""
    if pd.isna(median_atr_pct) or pd.isna(current_atr_pct) or current_atr_pct <= 0:
        return base_risk_per_trade
    ratio = median_atr_pct / current_atr_pct
    clamped_ratio = min(max(ratio, clamp_min), clamp_max)
    return base_risk_per_trade * clamped_ratio
