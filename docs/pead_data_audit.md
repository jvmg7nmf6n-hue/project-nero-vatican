# PEAD — Data Audit (Hard Gate)

**Result: ALL CLEAR.** 7/7 tickers have resolved (estimate + actual) EPS history
with confirmed lookahead-safe entry timing. New infrastructure built for this
audit: `nero_core/data_sources/earnings_data.py` (no earnings-surprise fetcher
existed anywhere in this codebase before this batch) — required adding `lxml` to
`requirements.txt` (a new dependency; `yf.Ticker.get_earnings_dates()` fails
without it).

## SURVIVOR-BIAS CAVEAT (attached to every report derived from this data)

The 7-ticker universe (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META) consists of
large, currently-successful companies by construction. Any result here says
nothing about the same effect in companies that failed, were delisted, or were
acquired before becoming famous today.

## (a) Earnings dates + history depth

| Ticker | Resolved observations | Oldest | Newest |
|---|---|---|---|
| AAPL | 86 | 2005-01-12 | 2026-04-30 |
| MSFT | 99 | 2001-10-18 | 2026-04-29 |
| GOOGL | 86 | 2005-02-01 | 2026-04-29 |
| TSLA | 57 | 2010-11-09 | 2026-04-22 |
| AMZN | 82 | 2002-04-23 | 2026-04-29 |
| NVDA | 65 | 2007-02-13 | 2026-05-20 |
| META | 56 | 2012-07-26 | 2026-04-29 |

Depth varies by each company's own history on the exchange (META IPO'd 2012;
AAPL/GOOGL data starts 2005 — yfinance's own earnings-history depth limit, not
this company's actual IPO date).

## (b) Actual vs estimate EPS

Every ticker resolves cleanly — `fetch_earnings_surprises` drops any row missing
either `EPS Estimate` or `Reported EPS` (future/pending announcements), and doing
so left 56-99 usable observations per ticker out of up to 100 requested (Yahoo's
own cap). **No ticker is blocked on this basis.**

## (c) Lookahead safety

**0 unresolvable events across all 7 tickers** — every single announcement in
each ticker's full available history has a next-trading-day candle available in
that ticker's own daily OHLCV (confirmed directly, not assumed), so
`entry_idx = first candle with date > announcement_time` always resolves to a
real, future candle.

**A genuine timing nuance, documented honestly rather than glossed over**: most
announcements cluster at 16:00-17:00 ET (after market close, "AMC") — but MSFT
and TSLA specifically show some announcements as early as 06:00-09:00 ET
("BMO" — before market open). For a BMO release, the economically "tightest"
entry would be THAT SAME trading day's own open (9:30 ET), not the following
day's. This strategy's entry rule (`first candle with date STRICTLY AFTER the
announcement timestamp`) instead pushes a BMO case to the FOLLOWING day's open —
one day later than the fastest theoretically possible entry. **This is a
conservative simplification, not a lookahead violation**: the following day's
open is still safely, unambiguously after the announcement in every case. It
means the strategy may be a day late capturing the very front of the drift for
BMO releases specifically (MSFT, TSLA) — worth remembering when reading MSFT/
TSLA's own results, not a reason to block anything.

## (d) Benchmark

**SPY confirmed to have no earnings data of its own** — `fetch_earnings_surprises
("SPY")` raises `EarningsDataUnavailableError` ("no earnings dates returned").
This matches the task's own framing: SPY is a benchmark for comparison, never a
PEAD signal ticker.

**Verdict: not blocked. Proceeding to strategy build (6 configs: {3%, 5%, 8%}
surprise thresholds x {5, 10} session holding windows).**
