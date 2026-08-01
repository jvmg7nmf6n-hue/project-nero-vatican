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
and every function accepts `None` (meaning "this (asset_class, timeframe)
combination has no annualization factor in TIMEFRAME_PERIODS_PER_YEAR") and
returns None for any annualized metric rather than silently guessing 252 for
everything, which is exactly the kind of mistake that quietly makes every
volatility number on the site wrong.

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

# feature/timeframe-periods-asset-aware: replaces the old bare-timeframe-string
# table (see git history) with an (asset_class, timeframe)-keyed one. THE BUG THIS
# CLOSES: a bare "timeframe" key cannot distinguish two assets that share a
# timeframe LABEL but not a trading calendar -- "4h" candle-data-gaps landed 4h
# exports for both 24/7 assets (BTC, BNB, GOLD) and session-based stocks in the
# same window a separate branch added a forex-only "4h": 1560 entry, which would
# have silently mis-annualized every non-forex 4h asset. That collision was
# averted by excluding "4h" entirely as a stopgap (2026-07-31 cross-branch
# review) -- this table is the permanent fix: every entry is now keyed by BOTH
# the asset class and the timeframe, so two different cadences can never collide
# under one string again.
#
# Asset classes are deliberately 5, not the more obvious 4 (forex/crypto/
# commodity/equity): GOLD and SILVER do NOT share a trading calendar in this
# codebase's actual data sourcing, verified empirically (not assumed) against
# real exported candle timestamps -- see docs/timeframe_periods_asset_aware_
# investigation.md. GOLD is Twelve Data spot XAU/USD, which trades near-
# continuously (matches crypto's own weekly cadence almost exactly). SILVER's
# Twelve Data endpoint 404s on this project's current plan (see market_data.py's
# own comment) and falls back to yfinance's SI=F -- a COMEX FUTURES contract, a
# different instrument on a different schedule entirely. Collapsing both into one
# "commodity" bucket would reintroduce the exact class of bug this table exists
# to prevent, just one level up. So: COMMODITY_SPOT (GOLD) and COMMODITY_FUTURES
# (SILVER) are separate classes, and COMMODITY_FUTURES intentionally has ZERO
# entries below -- SILVER's real trading-hours schedule (CME Globex) has not been
# independently verified, so every SILVER timeframe returns None rather than a
# fabricated number. See docs/timeframe_periods_asset_aware_investigation.md's
# backlog section for the follow-up ("verify CME Globex silver trading hours,
# then add commodity_futures periods/year constants") -- out of scope here.
CRYPTO = "crypto"
FOREX = "forex"
STOCK = "stock"
COMMODITY_SPOT = "commodity_spot"  # GOLD -- Twelve Data spot XAU/USD
COMMODITY_FUTURES = "commodity_futures"  # SILVER -- yfinance SI=F futures fallback

TIMEFRAME_PERIODS_PER_YEAR: dict[tuple[str, str], int] = {
    # CRYPTO (BTC, BNB) -- genuinely 24/7, no asset-class ambiguity, unchanged
    # values from the old table.
    (CRYPTO, "12h"): 730,   # 2 candles/day x 365
    (CRYPTO, "24h"): 365,   # 1 candle/day x 365
    (CRYPTO, "4h"): 2190,   # NEW (previously excluded entirely): 6 candles/day x 365

    # FOREX (EUR/USD, GBP/USD, USD/JPY).
    # "1day": 252 -- UNCHANGED VALUE, deliberately kept as-is (feature/timeframe-
    # periods-asset-aware, 2026-08-01 review): this project's own EURUSD_1day.json/
    # USDJPY_1day.json measure ~366.8 implied candles/year (Twelve Data serves a
    # "1day" candle on every calendar day, weekends included, non-flat) -- 252
    # (a trading-days-only convention) does NOT match that empirically, and is
    # very likely wrong for what's actually live today. NOT fixed here: this
    # value is already live on the site (EURUSD_1day/USDJPY_1day Sharpe/vol),
    # and changing it needs its own dedicated investigation + before/after impact
    # review, not a side effect of adding "4h". See docs/timeframe_periods_asset_
    # aware_investigation.md's backlog section.
    (FOREX, "1day"): 252,
    (FOREX, "1week"): 52,
    # "4h": NEW. Deliberately NOT the conventional 24/5-trading-week formula
    # (120h/week / 4h x 52 = 1560) -- this project's own EURUSD_4h.json/
    # GOLD_4h.json measure 6.03 candles/day, EVERY day of the week at near-
    # weekday density (Sat/Sun candles show real, non-flat O/H/L/C movement, not
    # forward-filled placeholders), statistically indistinguishable from BTC_4h.
    # json's own 6.03 candles/day. This value is MEASURED from live candle data,
    # not derived from the conventional forex-week formula -- 1560 would UNDER-
    # count this data provider's actual candle cadence by ~29%. See docs/
    # timeframe_periods_asset_aware_investigation.md for the full measurement.
    (FOREX, "4h"): 2190,

    # STOCK (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META).
    (STOCK, "1day"): 252,  # trading days only -- unchanged, empirically confirmed correct
    # "4h": NEW. NOT "6.5h RTH session / 4h ~= 1.6 candles/day" -- verified
    # against nero_core.data_sources.stock_data.resample_1h_to_4h_market_hours_
    # aware (and docs/stock_data_calibration_audit.md): a 6.5h RTH session
    # produces exactly 7 hourly candles, which groups into exactly ONE complete
    # 4h bar/session (the trailing ~2.5h/3-candle remainder is dropped, same
    # never-fabricate-a-partial-bar convention used everywhere else in this
    # codebase) -- confirmed empirically too (AAPL_4h.json: exactly 1 candle per
    # trading day). So stock "4h" and stock "1day" share the identical real
    # cadence: 1 sample/trading-day x 252.
    (STOCK, "4h"): 252,

    # COMMODITY_SPOT (GOLD) -- Twelve Data spot XAU/USD, empirically confirmed to
    # trade on the same near-continuous, 7-day calendar as crypto (GOLD_4h.json/
    # GOLD_24h.json both measure candles/day statistically indistinguishable from
    # BTC's own). No GOLD "1day" export currently exists (GOLD's daily-equivalent
    # export uses the "24h" cadence key, not "1day") -- deliberately no entry
    # here for that combination; see the closing report's "still null" section.
    (COMMODITY_SPOT, "24h"): 365,
    (COMMODITY_SPOT, "4h"): 2190,
    (COMMODITY_SPOT, "1week"): 52,

    # COMMODITY_FUTURES (SILVER) -- deliberately NO entries. See this table's own
    # docstring above.
}


def periods_per_year_for_timeframe(asset_class: str | None, timeframe: str) -> int | None:
    """None (never a guess) for any (asset_class, timeframe) combination not in
    the explicit table above, OR when asset_class itself is None (an asset this
    project doesn't yet know how to classify) -- callers must treat either case
    as "cannot annualize this," never "assume 252" or fall back to some other
    combination's constant."""
    if asset_class is None:
        return None
    return TIMEFRAME_PERIODS_PER_YEAR.get((asset_class, timeframe))


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
