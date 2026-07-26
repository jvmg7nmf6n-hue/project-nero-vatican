# Candle Data Export Pipeline — Day 1 of 7 Closing Report

Foundation for Day 2's candlestick charts. Full Stage 0 investigation, implementation,
one real bug found and fixed in a shared data-source module, and a real bootstrap
export against live data.

## Stage 0 design, as built

Confirmed the real function names by reading the code, not assuming them:

- Crypto (BTC, BNB) + GOLD/SILVER: `tools.timeframe_data.fetch_timeframe_candles`
  (the same dispatcher `process_single_asset` already uses for live strategy
  evaluation) — internally routes to `MarketDataClient.load_daily`/`load_intraday`.
- Forex: `nero_core.data_sources.forex_data.fetch_forex_ohlcv` — confirmed
  `MarketDataClient` genuinely has no forex routing; this is a separate module, Twelve
  Data only.
- Stocks: `nero_core.data_sources.stock_data.fetch_stock_ohlcv`, yfinance only.

**Binance US-IP endpoint rule (constraint #4):** confirmed the `data-api.binance.vision`
-first rule currently lives ONLY in `nero_core/data_sources/orderbook_data.py`
(ORDERFLOW_IMBALANCE's order-book depth fetch) — `MarketDataClient`'s own klines fetch
(`_fetch_binance_page`) still calls `api.binance.com` directly. Since live strategy
evaluation already runs successfully against that path today, and hardening
`MarketDataClient` itself is a change to the shared live-trading data path unrelated to
this feature, this candle-export module reuses `MarketDataClient`/`fetch_timeframe_
candles` as-is rather than writing a new direct Binance call — it doesn't introduce
any NEW un-mirrored Binance request. Flagging the gap as a worthwhile follow-up
hardening task, not silently fixing it as a side effect here.

**Scheduler pattern confirmed:** heartbeat.py is NOT a separate workflow step (it's
called inline inside `live_scheduler.main()`) — the real precedent for a standalone,
fail-independent module is `notify_ntfy.py`/`export_site_data.py`: a separate
`continue-on-error: true` step, run in sequence after "Export site data." `docs/
site_data/` is already `git add -f`'d recursively, so `candles/` needed no workflow
change there — just the new step itself, plus its own `TWELVE_DATA_API_KEY` in `env:`
(step-scoped; doesn't inherit from an earlier step).

## In-scope (asset, timeframe) pairs — 16 total

Derived directly from `docs/site_data/strategies.json`'s actual roster (21 raw
distinct pairs), not a guessed list:

| Class | Pairs (asset/timeframe) |
|---|---|
| Crypto | BTC/24h, BNB/12h |
| Metals | GOLD/1week, GOLD/24h, SILVER/1week, SILVER/24h |
| Forex | EUR/USD/1week, GBP/USD/1week, USD/JPY/1week |
| Stocks | AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META (all 1day) |

**What was excluded, and why:**
- `BTC-ETH` (COINTEGRATION_PAIRS) and `GOLD-SILVER` (GOLD_SILVER_RATIO_MR) — per
  constraint #3, no single price series exists for a two-leg pair.
- `BTC`/`ETH` at `"snapshot"` (ORDERFLOW_IMBALANCE) — an order-book depth snapshot has
  no OHLCV concept at all.
- NEWS_SENTIMENT's `"daily"` timeframe label — normalized onto the same real candle
  series as `"24h"` (same data, different label in that module's own roster metadata).
  This dedupes BTC's entry (already covered via other 24h configs) but GOLD's `"daily"`
  is a genuinely NEW fetch, since every other live GOLD config uses 1week, never 24h.

**Correction to the task's own assumption:** constraint #3 states BTC/ETH/GOLD/SILVER
"are already covered as standalone assets" to justify skipping the pairs. Checked
directly: true for BTC/GOLD/SILVER, but **ETH has no standalone roster entry at all**
— only inside the excluded pair and the OHLCV-meaningless snapshot entry. Per "derive
from the actual roster, not a guessed list," ETH is deliberately not included. Add it
later if a standalone ETH config is ever wired live.

## Cadence rule and API-budget estimate

Reuses `candle_boundary_due` exactly as-is (no changes to that shared function): 1week
pairs gated on `"1week"`, the 24h-equivalent pairs (BTC, GOLD's daily series, SILVER,
all 7 stocks) on `"24h"`, BNB on `"12h"`. An additional freshness check (compares the
existing file's own `last_updated` against the current cadence bucket — same
week/day/12h-window) prevents two scheduler ticks inside one ~40-minute gate window
from double-fetching the same unchanged data.

**Twelve Data daily call estimate** (the binding constraint — everything else is
Binance/yfinance, which don't touch this budget):

| Source | Cadence | Calls |
|---|---|---|
| GOLD/24h | once/day | 1/day |
| GOLD/1week | once/week | ~0.14/day |
| EUR/USD, GBP/USD, USD/JPY (1week each) | once/week each | ~0.43/day |
| **Average** | | **~1.6 calls/day** |
| **Peak** (the one day/week all weekly boundaries fire together) | | **5 calls that day** |

Against a ~800/day, ~8/min free-tier budget, this is well under 1% of the daily quota
even on the peak day, and the peak day's 5 calls land within one ~40-minute window —
nowhere near the ~8/min rate limit either. **Confirmed: ample headroom left for live
strategy evaluation**, which already spends the bulk of this project's Twelve Data
budget today.

## A real bug found and fixed while bootstrapping real data

Ran a real (non-mocked) export against live data sources to populate `docs/site_data/
candles/` for the first time and get genuine output-size/schema numbers. All 7 stock
files (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META) came back with exactly one `NaN` row
each — always the most recent one.

**Root cause:** `nero_core/data_sources/stock_data.py`'s `_drop_unclosed` only checked
`close_time < now` — a timing check, not a data-validity check. yfinance sometimes
appends a trailing "today" row with `NaN` open/high/low/close (a placeholder for a
session that hasn't fully formed yet) whose `close_time` still reads as already-past by
this check, so it slipped through to every caller, including PEAD (which happens to
tolerate it downstream via its own ATR `dropna`, which is why this had never been
visibly noticed before). Serializing `NaN` to JSON produces an invalid, non-spec token
that a strict parser — including JavaScript's `JSON.parse`, which Day 2's charting code
will use — throws on.

**Fix:** `_drop_unclosed` now also drops any row with a `NaN` OHLC value, regardless of
its timestamp. This is a root-cause fix in the shared data-source module (benefits
PEAD and any other future caller too), not a band-aid filter inside the export module
alone. One new regression test in `tests/test_stock_data.py` proving a trailing NaN
row is dropped even when its `close_time` is already in the past. Re-ran the real
bootstrap export after the fix: 16/16 files exported, 0 errors, 0 `NaN` values
anywhere, all 16 files confirmed to parse as strictly valid JSON.

## Output

- 16 files in `docs/site_data/candles/`, 200 candles each (the full requested count —
  no source came back thinner than that).
- Total size: **~628 KB**.
- Volume is `null` (never the source layer's placeholder `0.0`) for GOLD and all 3
  forex pairs — confirmed both `market_data.py` and `forex_data.py` fill missing
  volume with `0.0` at the source layer for exactly these; SILVER (yfinance futures),
  crypto (Binance), and all 7 stocks (yfinance) carry genuine trade volume and are
  passed through unchanged.
- Filenames sanitize forex's `/` (`EUR/USD` -> `EURUSD_1week.json`) using the same
  rule already established in `tools/backtest_forex_task_b2_sweep.py`.

## Tests

19 new tests: 18 in `tests/test_export_candle_data.py` (per-asset-class fetch with
mocked responses, filename sanitization including the forex slash case,
fail-independent behavior, cadence gating including the "not refetched the same week"
and "force bypasses gating" cases, output shape/schema, pair-asset exclusion, and the
`ETH`-not-included correction) and 1 new regression test in `tests/test_stock_data.py`
for the NaN-row bug. No test hits a real network or a real `time.sleep` — every fetch
function is mocked at the module-attribute level. Full suite: 1337 tests, passing.
