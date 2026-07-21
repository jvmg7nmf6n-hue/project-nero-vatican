# PSX Strategy Sweep, Task 3 — PEAD Gate: BLOCKED

Checked yfinance earnings-surprise data availability for OGDC.KA, LUCK.KA, HBL.KA
before attempting to run PEAD (Post-Earnings-Announcement Drift). No PEAD code was
run — this task is a gate check only, and the gate did not open.

## What was checked

- `yfinance.Ticker(symbol).get_earnings_dates(limit=40)` — the exact call
  `nero_core.data_sources.earnings_data.fetch_earnings_surprises` uses in production
  for the existing (US-ticker) PEAD configs — returned **"No earnings dates found,
  symbol may be delisted"** for all three tickers. Zero rows, not partial data.
- `Ticker.calendar` — returned an empty dict (`{}`) for all three.
- `Ticker.earnings` (deprecated fallback) — returned `None`.
- `Ticker.income_stmt` — the only fundamentals data that returned anything at all:
  4 years of **annual** net-income figures, no quarterly EPS, no analyst estimates,
  no surprise percentages, and no precise announcement dates. Not adequate for
  PEAD, which requires EPS actual vs. analyst estimate surprise data tied to a
  specific announcement date (the `t+1` execution anchor every PEAD config in this
  project relies on).

## Verdict: BLOCKED

Yahoo Finance simply does not carry earnings-surprise/analyst-estimate data for
PSX-listed names — this is a data-coverage gap in the vendor itself, not a
ticker-specific issue (all three names failed identically). No lookahead-safety
assessment was possible because no data existed to assess.

**PSX PEAD Phase 2 pending earnings data source.** If PSX research proceeds past
Phase 1, a PEAD gate re-check would need a Pakistan-specific earnings-estimate
source (e.g. PSX's own corporate disclosure filings, a local brokerage research
feed, or a paid data vendor) — none was identified or attempted in this batch, as
that would constitute new data-source discovery work outside this task's gate-check
scope.
