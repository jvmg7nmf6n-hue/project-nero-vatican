# RANGE_MEAN_REVERSION — Task 2 Data Audit

Tool: `tools/range_mean_reversion_data_audit.py`. Every check is a real, live fetch
through the existing data pipelines (`nero_core.data_sources.forex_data` for forex,
`tools.timeframe_data.fetch_timeframe_candles` for metals/crypto — no new data
pipeline was built for this task). Full raw output in
`docs/range_mean_reversion_data_audit_raw_output.txt`.

## Headline result: 28 of 28 configs ADEQUATE — no exclusions

| Tier | Asset | Timeframe | Candles | Range |
|---|---|---|---|---|
| 1 (forex) | EUR/USD | 1h | 4990 | 2025-12-13 -> 2026-07-19 |
| 1 (forex) | EUR/USD | 4h | 4997 | 2023-08-03 -> 2026-07-19 |
| 1 (forex) | EUR/USD | 1day | 4999 | 2007-08-02 -> 2026-07-19 |
| 1 (forex) | USD/JPY | 1h/4h/1day | 4990/4997/4999 | same pattern |
| 1 (forex) | GBP/USD | 1h/4h/1day | 4990/4997/4999 | same pattern |
| 1 (forex) | USD/CHF | 1h/4h/1day | 4990/4997/4999 | same pattern |
| 1 (metals) | GOLD | 4h | 4997 | 2023-09-14 -> 2026-07-19 |
| 1 (metals) | GOLD | 1day | 4999 | 2007-11-19 -> 2026-07-19 |
| 1 (metals) | GOLD | 1week | 1999 | 1988-03-28 -> 2026-07-13 |
| 1 (metals) | SILVER | 4h | 3428 | 2024-02-26 -> 2026-07-17 |
| 1 (metals) | SILVER | 1day | 6495 | 2000-08-31 -> 2026-07-18 |
| 1 (metals) | SILVER | 1week | 1350 | 2000-09-04 -> 2026-07-13 |
| 2 (crypto) | BTC | 4h/12h/1day | 19536/6516/3258 | 2017-08-17 -> 2026-07-19 |
| 2 (crypto) | ETH | 4h/12h/1day | 19536/6516/3258 | 2017-08-17 -> 2026-07-19 |
| 3 (stress) | SOL | 4h/12h | 13012/4337 | 2020-08-11 -> 2026-07-19 |
| 3 (stress) | NEAR | 4h/12h | 12628/4209 | 2020-10-14 -> 2026-07-19 |

**No config was SKIPPED. Task 2's full sweep proceeds across the entire 3-tier grid
with no exclusions.**

## Both "known constraints" checked directly — neither materialized here

**GOLD's historical ~210-day intraday cap**: confirmed this applies specifically to
**1h** intraday history on Twelve Data's free plan (the ~210-day figure referenced
throughout this project's earlier phases). This task's metals timeframe set is
4h/1day/1week — no 1h — and 4h candles accumulate 4x more slowly than 1h under the
same 5000-row-per-request cap, so GOLD's 4h naturally covers ~2.9 years (4997
candles), comfortably past the old 1h-specific constraint. The constraint is real,
but simply doesn't apply to the timeframes this task actually tests.

**NEAR's historical ~300-candle Coinbase cap**: NEAR resolves through this pipeline's
Binance-first cascade (`BINANCE_SYMBOLS` includes NEAR directly), not the Coinbase
fallback path that previously hit that cap — confirmed directly by the returned
depth (12,628 4h candles / 4,209 12h candles, dating to 2020-10-14, essentially
matching SOL's own depth). **NEAR is NOT marked SKIPPED** — the stress-test proceeds
on genuinely adequate data, which is exactly the precondition the task itself
required before trusting a "Tier 3 should fail" result as meaningful.

## Data pipelines used (no new pipeline built for this task)

- Forex: `nero_core.data_sources.forex_data.fetch_forex_ohlcv` (Task B1, already built).
- Metals/crypto: `tools.timeframe_data.fetch_timeframe_candles` (existing shared
  pipeline, GOLD/SILVER via their established Twelve-Data/yfinance-futures routing
  from Asset Expansion Phase A, BTC/ETH/SOL/NEAR via the Binance-first exchange
  cascade).
