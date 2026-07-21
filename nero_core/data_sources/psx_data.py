"""PSX (Pakistan Stock Exchange) data pipeline — Phase 1, Vatican's first emerging-
market research batch. Built directly on docs/psx_data_audit.md's YELLOW-verdict
findings: yfinance's `.KA` suffix covers individual PSX stocks cleanly (~18.5 years,
OGDC/LUCK/HBL/MARI confirmed), but has zero KSE-100 index coverage under any naming
convention; the KSE-100 index is only reachable via PSX's own undocumented
dps.psx.com.pk portal endpoint.

CORPORATE-ACTION GUARD (the audit's one confirmed blocker): the audit directly
observed an unadjusted ~8:1 bonus-share/split cliff in MARI's Sept 2024 closes,
present in BOTH the raw dps.psx.com.pk series and yfinance's own Adj Close — no
tested PSX source can be trusted to arrive pre-adjusted. OGDC/LUCK/HBL were
confirmed CLEAN in that audit, but every fetch through `fetch_psx_stock_ohlcv` still
runs `detect_corporate_action_breaks` before returning data: a >40% single-day
close-to-close move HALTS that ticker (raises PsxCorporateActionSuspectedError)
rather than silently handing back a corrupted series to a caller with no way to know.

CURRENCY: every PSX instrument is PKR-denominated — there is no USD-quoted
alternative on this exchange (confirmed in the audit; the DPS portal's own /symbols
endpoint doesn't even carry a currency field for this reason). This module returns
raw PKR prices, unconverted. This is safe for Vatican's existing strategy machinery:
every strategy in this codebase sizes and scores trades in R-multiples
(net_pnl / risk_dollars — a dimensionless, risk-normalized ratio), which is identical
whether the underlying currency is USD or PKR. Nothing about R-multiple accounting
requires a common currency across assets. A cross-asset USD-denominated equity curve
(mixing PSX with crypto/GOLD positions) is a different, out-of-scope question this
module does not attempt to answer.

MACRO PROXIES: USD/PKR (yfinance "PKR=X") and WTI crude (yfinance "CL=F") are both
market-quoted prices — the same publication-lag class as macro_data.py's existing
dollar proxy (t+1, no reporting lag beyond the standard closed-candle rule). SBP's own
policy rate is NOT available from this module — see `fetch_sbp_policy_rate`'s
docstring for why; USD/PKR is used as PSX's sole macro proxy per this task's own
documented fallback.
"""
from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from nero_core.data_sources.macro_data import align_macro_to_daily_candles, compute_lagged_change
from nero_core.data_sources.stock_data import (
    CANDLE_COLUMNS,
    StockDataResult,
    StockDataUnavailableError,
    fetch_stock_ohlcv,
)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "macro_cache"

# Bare PSX symbol -> yfinance Karachi-market ticker. Deliberately explicit (no
# suffix-guessing) — an unknown symbol raises ValueError rather than being silently
# guessed, matching stock_data.py's own TICKER RESOLUTION discipline.
PSX_YFINANCE_TICKERS = {
    "OGDC": "OGDC.KA",
    "LUCK": "LUCK.KA",
    "HBL": "HBL.KA",
    "MARI": "MARI.KA",  # confirmed corporate-action break in the audit; the guard below will halt it
}

DPS_HISTORICAL_URL = "https://dps.psx.com.pk/historical"
KSE100_SYMBOL = "KSE100"  # no hyphen -- "KSE-100" silently returns an empty stub, confirmed in the audit

CORPORATE_ACTION_THRESHOLD_PCT = 40.0

# Both legs are market-quoted (same t+1 class as macro_data.DOLLAR_LAG_BUSINESS_DAYS);
# neither carries a FRED-style extra reporting-lag day.
PSX_MACRO_CHANGE_WINDOW_DAYS = 20
PSX_MACRO_LAG_BUSINESS_DAYS = 1


class PsxCorporateActionSuspectedError(Exception):
    """Raised when a >CORPORATE_ACTION_THRESHOLD_PCT% single-day close-to-close move is
    detected in a fetched PSX series — the signature of an unadjusted split/bonus-share
    issue (see docs/psx_data_audit.md's MARI Sept-2024 finding). The caller must treat
    this ticker's data as unusable and SKIP it; this module never silently returns a
    series once such a break is found."""


class PsxMacroDataUnavailableError(Exception):
    """Raised when a PSX macro proxy series cannot be fetched from any source. Never
    falls back to synthetic/fabricated data."""


@dataclass(frozen=True)
class CorporateActionFlag:
    date: pd.Timestamp
    prior_close: float
    close: float
    pct_change: float


def detect_corporate_action_breaks(
    prices: pd.DataFrame, threshold_pct: float = CORPORATE_ACTION_THRESHOLD_PCT
) -> list[CorporateActionFlag]:
    """Flags every close-to-close move exceeding `threshold_pct` (default 40%) in
    absolute value. A liquid PSX blue-chip's normal trading does not produce a >40%
    single-day move; either it's an unadjusted split/bonus-share issue (the confirmed
    MARI case) or a data error — either way this module must not hand it back as a
    tradeable price series."""
    if prices.empty or len(prices) < 2:
        return []
    ordered = prices.sort_values("close_time").reset_index(drop=True)
    pct_change = ordered["close"].pct_change() * 100.0
    flags: list[CorporateActionFlag] = []
    for i in range(1, len(ordered)):
        change = pct_change.iloc[i]
        if pd.isna(change) or abs(change) <= threshold_pct:
            continue
        flags.append(
            CorporateActionFlag(
                date=ordered["date"].iloc[i],
                prior_close=float(ordered["close"].iloc[i - 1]),
                close=float(ordered["close"].iloc[i]),
                pct_change=float(change),
            )
        )
    return flags


def fetch_psx_stock_ohlcv(
    symbol: str,
    start=None,
    end=None,
    sleep_fn=time.sleep,
    threshold_pct: float = CORPORATE_ACTION_THRESHOLD_PCT,
) -> StockDataResult:
    """Daily OHLCV for a PSX blue-chip via yfinance's `.KA` suffix (see
    PSX_YFINANCE_TICKERS for supported symbols — an unlisted symbol raises ValueError,
    never a guessed suffix). Runs `detect_corporate_action_breaks` on the result before
    returning it: if any >threshold_pct% single-day break is found, raises
    PsxCorporateActionSuspectedError rather than returning the corrupted series."""
    yf_ticker = PSX_YFINANCE_TICKERS.get(symbol.upper())
    if yf_ticker is None:
        raise ValueError(f"unknown PSX symbol: {symbol!r} (known: {sorted(PSX_YFINANCE_TICKERS)})")

    result = fetch_stock_ohlcv(yf_ticker, "1day", start=start, end=end, sleep_fn=sleep_fn)
    flags = detect_corporate_action_breaks(result.prices, threshold_pct)
    if flags:
        worst = max(flags, key=lambda f: abs(f.pct_change))
        raise PsxCorporateActionSuspectedError(
            f"{symbol} ({yf_ticker}): {len(flags)} suspected corporate-action break(s) "
            f"detected (>|{threshold_pct}|% single-day close move) — worst: "
            f"{worst.date.date()} {worst.prior_close:.2f} -> {worst.close:.2f} "
            f"({worst.pct_change:+.1f}%). Data halted, not returned. See "
            f"docs/psx_data_audit.md's MARI Sept-2024 finding."
        )
    return result


def _parse_dps_month(symbol: str, year: int, month: int, session: requests.Session, timeout: int = 15) -> pd.DataFrame:
    response = session.post(DPS_HISTORICAL_URL, data={"month": month, "year": year, "symbol": symbol}, timeout=timeout)
    response.raise_for_status()
    try:
        tables = pd.read_html(io.StringIO(response.text))
    except ValueError:
        return pd.DataFrame()
    if not tables:
        return pd.DataFrame()
    return tables[0]


def fetch_kse100_daily(start_year: int, end_year: int, sleep_fn=time.sleep, sleep_seconds: float = 0.25) -> StockDataResult:
    """KSE-100 index daily OHLCV via PSX's own dps.psx.com.pk portal (the ONLY source
    with index-level history — yfinance has none, see docs/psx_data_audit.md).
    Fetches one month at a time (the endpoint's own granularity), `start_year`/
    `end_year` inclusive. Raises StockDataUnavailableError if the entire requested
    range returns zero rows (bad symbol, endpoint outage) — never fabricates a
    placeholder series."""
    session = requests.Session()
    now = pd.Timestamp.now(tz="UTC")
    rows: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if year > now.year or (year == now.year and month > now.month):
                break
            frame = _parse_dps_month(KSE100_SYMBOL, year, month, session)
            if not frame.empty:
                rows.append(frame)
            sleep_fn(sleep_seconds)

    if not rows:
        raise StockDataUnavailableError(f"KSE100: dps.psx.com.pk returned zero rows for {start_year}-{end_year}")

    combined = pd.concat(rows, ignore_index=True)
    combined = combined.rename(
        columns={"DATE": "date_str", "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close", "VOLUME": "volume"}
    )
    combined["date_str"] = combined["date_str"].str.strip()
    combined["date"] = pd.to_datetime(combined["date_str"], format="%b %d, %Y", utc=True)
    combined = combined.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    combined["close_time"] = combined["date"].dt.as_unit("ms").astype("int64")
    combined["open_time"] = combined["close_time"] - 86_400_000
    combined[["open", "high", "low", "close", "volume"]] = combined[["open", "high", "low", "close", "volume"]].astype(float)
    frame = combined[CANDLE_COLUMNS].reset_index(drop=True)

    return StockDataResult(
        prices=frame, source=f"NATIVE: dps.psx.com.pk historical, symbol={KSE100_SYMBOL}", symbol="KSE100", timeframe="1day"
    )


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.csv"


def _read_cache(name: str) -> pd.Series | None:
    path = _cache_path(name)
    if not path.exists():
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    if frame.empty:
        return None
    return frame.set_index("date")["value"].sort_index()


def _write_cache(name: str, series: pd.Series) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame = series.rename("value").rename_axis("date").reset_index()
    frame.to_csv(_cache_path(name), index=False)


def _fetch_yfinance_close_series(yf_symbol: str, sleep_fn=time.sleep) -> pd.Series:
    history = None
    last_error: Exception | None = None
    for attempt, delay in enumerate((0.0, 2.0, 5.0, 10.0)):
        if delay:
            sleep_fn(delay)
        try:
            history = yf.Ticker(yf_symbol).history(period="max")
        except Exception as exc:  # noqa: BLE001 - yfinance raises varied types; retry regardless
            last_error = exc
            history = None
        if history is not None and not history.empty:
            break
    if history is None or history.empty:
        reason = f": {last_error.__class__.__name__}: {last_error}" if last_error is not None else ""
        raise PsxMacroDataUnavailableError(f"{yf_symbol!r} returned no data{reason}")
    series = history["Close"].copy()
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series.sort_index()


def fetch_usd_pkr_daily(use_cache: bool = True, sleep_fn=time.sleep) -> tuple[pd.Series, str]:
    """USD/PKR spot rate (yfinance "PKR=X"). Rising = PKR weakening. Market-quoted,
    same t+1 lag class as macro_data's dollar proxy — no FRED-style reporting lag."""
    if use_cache:
        cached = _read_cache("usd_pkr")
        if cached is not None:
            return cached, "CACHED: USD/PKR (source recorded at fetch time; see data/macro_cache/usd_pkr.csv)"
    series = _fetch_yfinance_close_series("PKR=X", sleep_fn=sleep_fn)
    _write_cache("usd_pkr", series)
    return series, "NATIVE: yfinance PKR=X daily close"


def fetch_oil_price_daily(use_cache: bool = True, sleep_fn=time.sleep) -> tuple[pd.Series, str]:
    """WTI crude (yfinance "CL=F") — OGDC's direct revenue driver. Market-quoted, same
    t+1 lag class as USD/PKR."""
    if use_cache:
        cached = _read_cache("oil_wti")
        if cached is not None:
            return cached, "CACHED: WTI crude (source recorded at fetch time; see data/macro_cache/oil_wti.csv)"
    series = _fetch_yfinance_close_series("CL=F", sleep_fn=sleep_fn)
    _write_cache("oil_wti", series)
    return series, "NATIVE: yfinance CL=F (WTI crude) daily close"


def fetch_sbp_policy_rate() -> tuple[pd.Series, str]:
    """SBP (State Bank of Pakistan) policy rate — NOT available from this module.
    Checked directly during this batch: FRED's Pakistan discount-rate series
    (the INTDSRPKM193N-class annual "Interest Rates, Discount Rate for Pakistan"
    series) last observation is 2017, and was itself superseded by SBP's own Policy
    Rate regime in May 2015 — an annual, 9-years-stale series is unusable for any
    daily-bar strategy signal. SBP's own website publishes policy decisions as PDF/
    HTML press releases, not a machine-readable time series, so no scrape target
    exists either. Per this task's own documented fallback: PSX macro research uses
    USD/PKR as its sole policy-adjacent proxy; this function always raises so no
    caller can silently assume a working feed exists."""
    raise PsxMacroDataUnavailableError(
        "SBP policy rate: no free programmatic source found (FRED's Pakistan discount-rate "
        "series is annual, last observation 2017, superseded by SBP's own Policy Rate since "
        "2015; SBP's own site has no machine-readable feed). Falling back to USD/PKR as the "
        "sole macro proxy, per task specification."
    )


def build_psx_regime_frame_oil_and_currency(candles: pd.DataFrame, usdpkr_series: pd.Series, oil_series: pd.Series) -> pd.DataFrame:
    """OGDC's Pakistan-adapted MACRO_RISK_ON regime: risk_on = (USD/PKR rising, i.e.
    PKR weakening) AND (oil rising) — an oil-revenue tailwind combined with currency
    stress, per this batch's task spec. Both legs use the identical lag/align
    machinery as nero_core.data_sources.macro_data (20-day change on each series' own
    native business-day index, THEN a 1-business-day lag, THEN forward-fill onto the
    candle grid) — only the underlying series and the boolean direction differ from
    the original BTC/GOLD dollar+DFII10 regime.

    COLUMN-NAME REUSE (deliberate, not an error): output columns are named
    "dollar_change_20d" (= USD/PKR's own 20-day change) and "dfii10_change_20d" (= oil's
    own 20-day change) so this frame plugs directly into
    nero_core.strategies.macro_risk_on's UNCHANGED add_indicators /
    run_macro_risk_on_backtest (which key on those exact column names) and into
    tools.backtest_metals_phase_a_sweep's existing _macro_half_stats, without
    modifying either — the strategy code never needs to know its regime came from
    Pakistan-specific data."""
    usdpkr_change = compute_lagged_change(usdpkr_series, PSX_MACRO_CHANGE_WINDOW_DAYS, PSX_MACRO_LAG_BUSINESS_DAYS)
    oil_change = compute_lagged_change(oil_series, PSX_MACRO_CHANGE_WINDOW_DAYS, PSX_MACRO_LAG_BUSINESS_DAYS)
    frame = align_macro_to_daily_candles(candles, usdpkr_change, "dollar_change_20d")
    frame = align_macro_to_daily_candles(frame, oil_change, "dfii10_change_20d")
    frame["risk_on"] = (frame["dollar_change_20d"] > 0) & (frame["dfii10_change_20d"] > 0)
    return frame


def build_psx_regime_frame_currency_only(candles: pd.DataFrame, usdpkr_series: pd.Series) -> pd.DataFrame:
    """LUCK/HBL's Pakistan-adapted MACRO_RISK_ON regime: USD/PKR alone (currency-
    sensitive sectors — cement import costs, banking-sector currency exposure).
    risk_on = USD/PKR rising (PKR weakening). Same column-name-reuse rationale as
    build_psx_regime_frame_oil_and_currency; the unused "dfii10_change_20d" leg is set
    to a constant 0.0 (neutral, never NaN) rather than left absent, so it doesn't
    interact with the shared machinery's dropna-based warmup logic in a
    currency-only variant that has no second leg at all."""
    usdpkr_change = compute_lagged_change(usdpkr_series, PSX_MACRO_CHANGE_WINDOW_DAYS, PSX_MACRO_LAG_BUSINESS_DAYS)
    frame = align_macro_to_daily_candles(candles, usdpkr_change, "dollar_change_20d")
    frame["dfii10_change_20d"] = 0.0
    frame["risk_on"] = frame["dollar_change_20d"] > 0
    return frame
