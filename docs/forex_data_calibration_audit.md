# Comprehensive Asset Expansion, Part B: Forex — Task B1 Data Audit

Tool: `tools/forex_data_calibration_audit.py`. Fetches all 10 standard forex pairs at
all 4 standard forex timeframes (1h/4h/1day/1week) via
`nero_core.data_sources.forex_data.fetch_forex_ohlcv` — a new module built as part of
this task. Full raw output in `docs/forex_audit_raw_output.txt`.

## Headline result

**40 of 40 configs (10 pairs x 4 timeframes) are ADEQUATE.** Zero pairs failed to
resolve. All 10 proceed to Task B2 with no exclusions.

## Data source: Twelve Data (already integrated) — unlike SILVER/PLATINUM, no 404s

Confirmed directly: all 10 pairs (EUR/USD, GBP/USD, USD/JPY, USD/CHF, EUR/GBP,
EUR/JPY, GBP/JPY, AUD/USD, NZD/USD, USD/CAD) resolve on the current Twelve Data
free-tier plan, with **native 1h, 4h, 1day, and 1week intervals for every pair** — no
resampling needed anywhere in this module, unlike stocks (session-aware 4h) or
metals (yfinance-futures resampling). This is a materially better outcome than
metals: SILVER/PLATINUM's spot symbols (XAG/USD, XPT/USD) 404 on this same plan
("available starting with the Grow or Venture plan"); forex pairs are not gated the
same way.

## Depth cap — confirmed directly, and it's an OUTPUTSIZE cap, not a real history limit

Every pair's 1h fetch returns almost exactly 5000 candles (Twelve Data's own
per-request row cap), spanning ~219 days (2025-12-12 -> 2026-07-19). 4h similarly caps
at ~4998 candles, spanning further back (~3.2 years, 2023-08 onward) since 4h candles
accumulate more slowly. **This is confirmed to be a pagination limit, not a true data
cutoff**: requesting the same pair/interval with an explicit `end_date` further back
(e.g. 2024-06-01) still returns real, non-empty 1h data — Twelve Data has intraday
history well beyond what a single 5000-row call can return. This module deliberately
does **not** paginate, matching the same single-call convention every other Twelve
Data asset in this project uses (GOLD included) — the practical depth available
through the existing fetch pattern is what's reported here, not the pair's true full
history.

Daily and weekly depth are far beyond this cap for every pair: 1day reaches the full
5000-row cap at ~18+ years for every pair (back to 2007 for most), and 1week reaches
back to 1971-1986 depending on the pair (EUR/USD's 1week series oddly extends to
1974 — pre-dating the Euro currency itself, evidently a legacy/synthetic series
Twelve Data maintains for historical continuity; noted here as a curiosity, not
something Task B2 needs to resolve since only recent history is used in practice).

## 24/5 market gap

Forex trades continuously from Monday open to Friday close — the only real gap is
Friday close -> Sunday/Monday open. This module does not need to handle that specially
(Twelve Data simply never emits candles during the closed window), but Task B3's
mandatory grid-shift verification must not shift a candle-grid boundary across that
gap, the same "don't shift across a real market closure" principle already
established for metals' daily settlement gap in Asset Expansion Phase A.

## Data module built

`nero_core/data_sources/forex_data.py`: `fetch_forex_ohlcv(pair, timeframe, api_key,
outputsize, sleep_fn, timeout_seconds)`, `ForexDataResult`,
`ForexDataUnavailableError`. Reuses the exact `.dt.as_unit("ms")` timestamp-precision
pattern established for GOLD/SILVER/PLATINUM (see
`nero_core/data_sources/market_data.py`'s `_load_twelve_data`) and a rate-limit
retry-with-backoff loop for 429/"out of API credits" responses (confirmed directly:
Twelve Data's free plan throttles aggressively under back-to-back requests, similar
to yfinance's own behavior observed for metals).
