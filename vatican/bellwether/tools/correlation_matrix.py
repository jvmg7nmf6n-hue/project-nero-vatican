"""CC-1 master directive, Part B Rung 1 (B1a): compute the REAL pairwise
correlation matrix across the 4 real Bellwether agent fields (real_yield_10y,
dxy, vix, BTC funding rate) over the real overlapping history available today.
Measured, not estimated -- a one-time analysis script, not part of the engine.

Sources (same functions/caches the real providers already use):
  - real_yield_10y: nero_core.data_sources.macro_data.fetch_dfii10_daily
    (FRED DFII10, cached at data/macro_cache/dfii10.csv)
  - dxy: yfinance DX-Y.NYB daily close (same ticker VaticanRealMarketData
    uses in production, pulled here over a longer window for a real
    correlation sample rather than production's own single-latest-value need)
  - vix: yfinance ^VIX daily close (same ticker VaticanRealMarketData uses)
  - funding: nero_core.data_sources.funding_data.load_funding_history("BTC")
    (Binance fapi/v1/fundingRate, cached at data/funding_cache/BTC_funding.csv),
    resampled to a daily mean (3 settlements/day) to align with the other 3
    daily series

All 4 series are aligned on calendar date via an INNER join (only dates all
4 series have a real observation for) -- no forward-fill, no synthetic
interpolation. Usage: python tools/correlation_matrix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_BELLWETHER_ROOT = Path(__file__).resolve().parents[1]
_VATICAN_ROOT = _BELLWETHER_ROOT.parents[1]
sys.path.insert(0, str(_BELLWETHER_ROOT))
sys.path.insert(0, str(_VATICAN_ROOT))

import pandas as pd


def load_real_yield_10y() -> pd.Series:
    from nero_core.data_sources.macro_data import fetch_dfii10_daily

    series, _label = fetch_dfii10_daily()
    series = series.copy()
    series.index = pd.to_datetime(series.index).normalize()
    series.name = "real_yield_10y"
    return series


def load_dxy(period: str = "5y") -> pd.Series:
    import yfinance as yf

    history = yf.Ticker("DX-Y.NYB").history(period=period, interval="1d")
    if history.empty:
        raise ValueError("empty yfinance response for DX-Y.NYB")
    series = history["Close"].copy()
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    series.name = "dxy"
    return series


def load_vix(period: str = "5y") -> pd.Series:
    import yfinance as yf

    history = yf.Ticker("^VIX").history(period=period, interval="1d")
    if history.empty:
        raise ValueError("empty yfinance response for ^VIX")
    series = history["Close"].copy()
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    series.name = "vix"
    return series


def load_funding_daily_mean_bps() -> pd.Series:
    from nero_core.data_sources.funding_data import load_funding_history

    result = load_funding_history("BTC")
    settlements = result.settlements.copy()
    settlements["date"] = pd.to_datetime(settlements["settlement_date"]).dt.tz_localize(None).dt.normalize()
    daily = settlements.groupby("date")["funding_rate"].mean() * 10_000  # fraction -> bps, matching btc_perp_funding_bps convention
    daily.name = "funding_rate_bps"
    return daily


def build_aligned_frame(period: str = "5y") -> pd.DataFrame:
    real_yield = load_real_yield_10y()
    dxy = load_dxy(period)
    vix = load_vix(period)
    funding = load_funding_daily_mean_bps()
    frame = pd.concat([real_yield, dxy, vix, funding], axis=1, join="inner").dropna()
    return frame


def main() -> None:
    frame = build_aligned_frame()
    print(f"Aligned real-history sample: n={len(frame)} calendar days, "
          f"{frame.index.min().date()} to {frame.index.max().date()}")
    print()
    print("Pairwise Pearson correlation matrix (level values):")
    corr = frame.corr(method="pearson")
    print(corr.round(4).to_string())
    print()
    print("Pairwise Pearson correlation matrix (20-trading-day CHANGE -- "
          "matches MACRO_RISK_ON's own t+2/20-bar-change convention, and is "
          "the more relevant comparison for a DSL condition that reacts to "
          "MOVEMENT, not level):")
    changed = frame.diff(20).dropna()
    corr_chg = changed.corr(method="pearson")
    print(corr_chg.round(4).to_string())


if __name__ == "__main__":
    main()
