"""Day 4/7 — Quant Intelligence Panel, Part 1: per-asset STANDALONE risk/return
metrics. Pure functions only — no network, no side effects, no composite/aggregate
score. Every metric here is independently interpretable; there is deliberately no
"overall quant score" the way nero_core.quant.quant_intelligence.build_quant_
consensus_report computes one (that module is untouched and not imported here).

WINDOW SIZING: Day 1's candle export currently produces ~200 candles per asset, not
the 252 a "one trading year" convention would assume. Every function below that
needs a trailing window takes that window as an explicit CALLER-SUPPLIED integer
(never hardcoded here) and independently re-clamps it to whatever is actually
available: `n = min(window, len(usable_data))`. If that clamped `n` still falls
below MIN_OBSERVATIONS, the function returns None rather than computing something
statistically meaningless on a handful of points. The orchestrator in
nero_core.execution.export_quant_metrics is the one place that decides the TARGET
window (e.g. 252) per metric family and reports the ACTUALLY-achieved value back as
`window_used` — these functions never assume their caller got that clamping right.

ANNUALIZATION: `periods_per_year` is always an explicit argument, never a default,
and every function accepts `None` (meaning "this timeframe has no annualization
factor in TIMEFRAME_PERIODS_PER_YEAR") and returns None for any annualized metric
rather than silently guessing 252 for everything, which is exactly the kind of
mistake that quietly makes every volatility number on the site wrong.

Log returns are used throughout (continuously compounded), not simple returns —
see this module's own cross-validation tests for why comparing against a reference
library fed the SAME log-return series (rather than simple returns) is the
apples-to-apples check, and why a small, expected divergence remains if a caller
elsewhere compares against simple-return-based numbers instead.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Below this many usable observations (returns, or closes for the z-score), a
# metric returns None rather than reporting a number with no real statistical
# grounding. Matches this task's own "e.g. 30" example verbatim.
MIN_OBSERVATIONS = 30

# Derived directly from Day 1's own export conventions (nero_core.execution.
# export_candle_data): "24h" is the token that pipeline uses EXCLUSIVELY for
# crypto/metals, "1day" EXCLUSIVELY for stocks -- there is currently no asset in
# this codebase where the same literal timeframe string means two different real
# cadences, so a flat string->periods-per-year lookup is unambiguous. If a future
# asset class ever reuses "1day" for a 24/7 market (or "24h" for a 5-day one) this
# table would need an asset-class-aware key instead of a bare timeframe string --
# flagged here rather than silently assumed to hold forever.
TIMEFRAME_PERIODS_PER_YEAR: dict[str, int] = {
    "12h": 730,   # crypto, 24/7: 2 candles/day x 365
    "24h": 365,   # crypto/metals, 24/7
    "1day": 252,  # stocks, trading days only
    "1week": 52,  # any asset class
}


def periods_per_year_for_timeframe(timeframe: str) -> int | None:
    """None (never a guess) for any timeframe string not in the explicit table
    above -- callers must treat that as "cannot annualize this," not "assume
    252."""
    return TIMEFRAME_PERIODS_PER_YEAR.get(timeframe)


def _clean_closes(closes) -> pd.Series:
    series = closes if isinstance(closes, pd.Series) else pd.Series(closes)
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def log_returns(closes) -> pd.Series:
    """Continuously compounded per-period returns: ln(close_t / close_{t-1}).
    NaN-safe (non-numeric/zero/negative closes drop out rather than raising or
    producing inf); the first period is necessarily absent (nothing precedes it),
    same "warmup of 1" every other function here accounts for."""
    clean = _clean_closes(closes)
    if len(clean) < 2:
        return pd.Series(dtype=float)
    return np.log(clean / clean.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()


def annualized_log_return(closes, periods_per_year: int | None) -> float | None:
    """Mean log return x periods_per_year. `closes` is used exactly as given --
    the CALLER is responsible for having already trimmed it to the intended
    window (see this module's docstring); this function only enforces the
    MIN_OBSERVATIONS floor on however many returns that produces."""
    if periods_per_year is None:
        return None
    returns = log_returns(closes)
    if len(returns) < MIN_OBSERVATIONS:
        return None
    return float(returns.mean() * periods_per_year)


def rolling_zscore(closes, window: int) -> float | None:
    """Z-score of the MOST RECENT close relative to the trailing `window`'s own
    mean and std (the window is self-inclusive -- it ends AT the latest close,
    matching nero_core.quant.quant_intelligence.zscore's existing rolling
    convention).

    DELIBERATELY NOT gated by the module's MIN_OBSERVATIONS (30) floor: that
    floor exists to protect the longer-horizon return-based metrics (which
    target a 252-period window and only make sense with a meaningfully large
    sample), whereas a stretch reading like this is conventionally a SHORT
    lookback (20 periods here) by design, not a shrunken-down long window --
    requiring 30 observations to compute a 20-period z-score would make it
    permanently null on every asset regardless of how much history is
    available, which is a bug, not a safety guard. The only requirement is
    having at least `window` closes to fill that window honestly; fewer than
    that returns None rather than silently using a shorter, un-requested
    window.
    """
    clean = _clean_closes(closes)
    if len(clean) < window:
        return None
    tail = clean.tail(window)
    std = tail.std()
    if pd.isna(std) or std == 0:
        return None
    return float((clean.iloc[-1] - tail.mean()) / std)


def realized_volatility(closes, window: int, periods_per_year: int | None) -> float | None:
    """Std of per-period log returns x sqrt(periods_per_year), expressed as a
    PERCENTAGE (e.g. 32.5, not 0.325). `window` counts RETURNS (not closes) and
    is re-clamped to whatever is actually available."""
    if periods_per_year is None:
        return None
    returns = log_returns(closes)
    n = min(window, len(returns))
    if n < MIN_OBSERVATIONS:
        return None
    std = returns.tail(n).std()
    if pd.isna(std):
        return None
    return float(std * math.sqrt(periods_per_year) * 100.0)


def sharpe_ratio(closes, window: int, periods_per_year: int | None, rf_annual: float) -> float | None:
    """(annualized log return - rf_annual) / annualized volatility (std of
    per-period log returns, ddof=1, x sqrt(periods_per_year)) -- algebraically
    identical to the conventional "mean(excess per-period return)/std(excess
    per-period return) x sqrt(periods_per_year)" form (subtracting a constant
    per-period risk-free rate before taking mean/std doesn't change the std),
    which is what lets this cross-validate directly against a reference
    implementation fed the same rf_annual."""
    if periods_per_year is None:
        return None
    returns = log_returns(closes)
    n = min(window, len(returns))
    if n < MIN_OBSERVATIONS:
        return None
    tail = returns.tail(n)
    ann_return = float(tail.mean() * periods_per_year)
    ann_vol = float(tail.std() * math.sqrt(periods_per_year))
    if pd.isna(ann_vol) or ann_vol == 0:
        return None
    return (ann_return - rf_annual) / ann_vol


def sortino_ratio(
    closes,
    window: int,
    periods_per_year: int | None,
    rf_annual: float,
    mar: float | None = None,
) -> float | None:
    """Same numerator as sharpe_ratio (annualized return - rf_annual); the
    denominator is annualized DOWNSIDE deviation instead of total volatility.

    MAR (minimum acceptable return, PER-PERIOD, not annual) defaults to
    rf_annual / periods_per_year when not given -- i.e. "downside" means "below
    the risk-free rate," the same convention this task's own instructions call
    out explicitly, because reference libraries differ (empyrical's own default
    `required_return` is 0, a materially different definition of "downside" that
    would silently produce a different number for the same data).

    Downside deviation follows empyrical's own divisor convention (verified by
    reading its source, not assumed): squared shortfalls below MAR are averaged
    over ALL `n` periods, not just the periods that fell short -- a periods-below-
    MAR-only divisor is a different, common alternative implementation and would
    NOT cross-validate against empyrical even on identical input.
    """
    if periods_per_year is None:
        return None
    returns = log_returns(closes)
    n = min(window, len(returns))
    if n < MIN_OBSERVATIONS:
        return None
    tail = returns.tail(n)
    per_period_mar = mar if mar is not None else rf_annual / periods_per_year

    ann_return = float(tail.mean() * periods_per_year)
    downside = (tail - per_period_mar).clip(upper=0.0)
    downside_variance = float((downside**2).mean())
    downside_deviation = math.sqrt(downside_variance) * math.sqrt(periods_per_year)
    if downside_deviation == 0 or pd.isna(downside_deviation):
        return None
    return (ann_return - rf_annual) / downside_deviation


CROSS_VALIDATION_TOLERANCE = 0.05


def relative_difference(value: float, reference: float) -> float | None:
    """abs(value - reference) / abs(reference). None when reference is exactly 0
    (relative difference is undefined, not infinite-and-failing)."""
    if reference == 0:
        return None
    return abs(value - reference) / abs(reference)


def cross_validates(value: float, reference: float, tolerance: float = CROSS_VALIDATION_TOLERANCE) -> bool:
    """True if `value` agrees with a reference implementation's `reference`
    output within `tolerance` relative difference (default 5%, per this
    project's own cross-validation bar). False (never True) when the relative
    difference is undefined (reference == 0) -- an undefined comparison is not
    a passing one."""
    diff = relative_difference(value, reference)
    return diff is not None and diff <= tolerance
