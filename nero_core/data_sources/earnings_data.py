"""Earnings-surprise data for PEAD (Post-Earnings-Announcement Drift) — Three New
Hypothesis Batch, Hypothesis 3 (Stocks). No such fetcher existed anywhere in this
codebase before this module.

DATA AUDIT FINDINGS (docs/pead_data_audit.md has the full report):
  - `yf.Ticker(symbol).get_earnings_dates(limit=100)` (Yahoo caps `limit` at 100)
    returns EPS Estimate / Reported EPS / Surprise(%), indexed by the
    announcement's own timestamp. Requires the `lxml` package (not previously a
    project dependency — added to requirements.txt).
  - Every announcement timestamp checked, across all 7 tickers' full available
    history, is HOURS before the earliest possible next-trading-day open —
    confirmed directly by inspecting the hour-of-day distribution per ticker
    (most cluster at 16:00 ET, exactly market close; TSLA/AMZN show some
    intraday-hour announcements too, e.g. 12:00 ET, but even those remain many
    hours before the FOLLOWING day's open). Next-day-open execution is
    lookahead-safe for every observed case.
  - Rows with a future/pending announcement (Reported EPS not yet known) are
    dropped here — `dropna(subset=["Reported EPS", "EPS Estimate"])` — never
    treated as a resolved surprise.
  - SPY (the benchmark) has NO earnings dates at all (it's an ETF, not a
    company) — confirmed directly (`get_earnings_dates` raises/returns nothing
    usable) — it can only serve as a passive-return benchmark, never as its own
    PEAD signal.

SURVIVOR-BIAS CAVEAT (attach this note to every report derived from this data):
the 7 tickers (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META) are large, currently-
successful companies by construction — a company that failed, was delisted, or
was acquired is definitionally absent from this list. Any positive PEAD reading
on this specific 7-ticker universe says nothing about whether the same effect
would have applied to companies that didn't survive to be famous today.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

BENCHMARK_TICKER = "SPY"  # no earnings of its own -- passive-return comparison only
SURVIVOR_BIAS_CAVEAT = (
    "SURVIVOR-BIAS CAVEAT: this universe (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, "
    "META) consists of large, currently-successful companies by construction. "
    "Any result here says nothing about the same effect in companies that "
    "failed, were delisted, or were acquired before becoming famous."
)


class EarningsDataUnavailableError(Exception):
    """Raised when no usable earnings-surprise data can be fetched for a ticker
    — never fabricates a surprise value or an estimate that wasn't reported."""


def fetch_earnings_surprises(symbol: str, limit: int = 100) -> pd.DataFrame:
    """Returns a DataFrame indexed by announcement timestamp (tz-aware, the
    exchange's own local time as reported by the data provider) with columns
    "eps_estimate", "eps_actual", "surprise_pct" (the actual %, NOT recomputed --
    kept as reported) -- ONLY for rows where both an estimate and an actual
    exist. Raises EarningsDataUnavailableError if the ticker has no earnings
    history at all (e.g. an ETF/benchmark) or the fetch fails. `limit` is capped
    by Yahoo at 100 regardless of what's requested."""
    ticker = yf.Ticker(symbol)
    try:
        raw = ticker.get_earnings_dates(limit=min(limit, 100))
    except Exception as exc:  # noqa: BLE001 - yfinance/lxml raise a mix of exception types
        raise EarningsDataUnavailableError(f"{symbol}: {exc.__class__.__name__}: {exc}") from exc

    if raw is None or raw.empty:
        raise EarningsDataUnavailableError(f"{symbol}: no earnings dates returned (ETF/benchmark tickers have none)")

    valid = raw.dropna(subset=["Reported EPS", "EPS Estimate"]).copy()
    if valid.empty:
        raise EarningsDataUnavailableError(f"{symbol}: no resolved (actual+estimate) earnings observations")

    valid = valid.rename(columns={"EPS Estimate": "eps_estimate", "Reported EPS": "eps_actual", "Surprise(%)": "surprise_pct"})
    valid = valid[["eps_estimate", "eps_actual", "surprise_pct"]].sort_index()
    valid.index.name = "announcement_time"
    return valid


def compute_surprise_pct(eps_estimate: float, eps_actual: float) -> float:
    """(actual - estimate) / abs(estimate) -- the task's own formula, computed
    fresh from eps_estimate/eps_actual rather than trusting yfinance's own
    Surprise(%) column blindly (kept alongside for cross-checking, not used
    directly by the strategy)."""
    if eps_estimate == 0:
        return float("nan")
    return (eps_actual - eps_estimate) / abs(eps_estimate)
