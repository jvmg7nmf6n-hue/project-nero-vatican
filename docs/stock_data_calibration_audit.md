# Comprehensive Asset Expansion, Part A: Stocks — Task A1 Data Audit

Tool: `tools/stock_data_calibration_audit.py`. Fetches every ticker in the Task A2
universe (SPY/QQQ/IWM + 27 liquid stocks) at all 4 standard stock timeframes
(1h/4h/1day/1week) via `nero_core.data_sources.stock_data.fetch_stock_ohlcv` — a new
module built as part of this task. Full raw output in
`docs/stock_audit_raw_output.txt`.

## Headline result

**120 of 120 configs (30 symbols x 4 timeframes) are ADEQUATE.** Zero tickers failed
to resolve. All 30 proceed to Task A2 with no exclusions.

## (a) 1h interval capped at ~730 days — confirmed directly

Every symbol except XYZ returns exactly the same window: **2024-07-19 -> 2026-07-17**
(~729 days), regardless of how far back the company itself has traded (AAPL, listed
since 1980, still only returns the same ~729-day 1h window as DASH, listed in 2020).
This is a Yahoo-side plan limitation on the `1h` interval, not a per-company data gap.

XYZ (formerly SQ — Block Inc renamed the ticker in January 2025) shows a *shorter* 1h
window: 2025-01-21 -> 2026-07-17 (2596 candles vs. ~3471 for everything else).
Confirmed directly (`docs/` scratch probe, not included in the automated tool since it
targets the old ticker on purpose): requesting `SQ` itself now returns a completely
empty response — the old ticker is dead, not silently redirected. This module raises
`StockDataUnavailableError` for `SQ` and would SKIP it if anyone tried to fetch it;
Task A2's universe correctly uses `XYZ` instead, with the caveat that its own
resolvable intraday history only goes back to the rename date, not to Square/Block's
full trading history under the old ticker.

Two symbols (ADBE, CRM) hit yfinance's transient rate-limit ("possibly delisted; no
price data found") on the first attempt during this run and recovered automatically
via the module's built-in retry-with-backoff — both show ADEQUATE, full-depth results
in the final report, confirming the retry logic works against a real rate-limit event,
not just in mocked tests.

## (b) No native 4h — resampled from 1h, market-hours aware

Confirmed directly: yfinance has no `4h` interval for equities. `resample_1h_to_4h_
market_hours_aware` (new, in `stock_data.py`) groups each trading day's OWN 7 hourly
candles (09:30, 10:30, ..., 15:30 America/New_York — a ~6.5h RTH session) into
consecutive chunks of 4, **reset at every session boundary** (never spanning two
different trading days), volume-summed. A 6.5h session yields exactly one complete 4h
bar (09:30-13:30) plus a dropped ~2.5h/3-candle remainder (13:30-16:00) — confirmed
by the numbers: every symbol's 4h count is close to 1/7th its 1h count (SPY: 3470 1h
-> 493 4h). This throws away real information (~40% of each session) rather than
fabricate a 4th candle over an incomplete window — the same never-fabricate
convention `tools.timeframe_data.aggregate_n_consecutive_candles` already uses for
crypto/metals, just reset per session instead of applied globally (globally would
incorrectly merge across the overnight/weekend gap).

## (c) Survivorship bias — permanent caveat, not fixable by an audit

yfinance only ever serves the CURRENTLY-LISTED ticker. Any company that was delisted,
went bankrupt, or was acquired away has no path back into this fetcher — the
27-stock universe this task tests is therefore itself a survivor-selected sample.
**SPY, QQQ, and IWM are the bias-free reference set**: as index funds, they always
hold whatever is CURRENTLY in their index, so constituent turnover (a company being
removed from the S&P 500, for instance) happens invisibly inside the fund rather than
as a visible "delisting" event the ETF itself suffers. Every single-stock
SURVIVED/PROMISING-WATCHLIST result from Task A2 carries this caveat: an edge
measurable only on stocks that happened to survive to today is a fundamentally
weaker claim than an edge on GOLD or BTC, which have no analogous selection filter.
This caveat cannot be removed by more data or a better audit — it is structural to
what yfinance (and any free ticker-based data source) can serve.

## Ticker resolution — logged and skipped, never guessed

Confirmed directly with two probes outside the universe:
- `SQ` (delisted/renamed): yfinance returns an empty DataFrame — 0 rows, no
  exception. `fetch_stock_ohlcv` raises `StockDataUnavailableError`.
- A fully invalid symbol (`NOTAREALTICKERXYZ123`): same empty-response behavior, same
  raised error.

`tools/stock_data_calibration_audit.py`'s `audit_symbol_timeframe` catches
`StockDataUnavailableError` per (symbol, timeframe) and records it as `SKIPPED
(UNRESOLVED)` with the reason — the audit loop never stops, and a failed symbol is
never silently swapped for a different one. Zero symbols hit this path in the actual
Task A2 universe (all 30 resolve).

## 1day/1week depth — comfortably exceeds "3+ years" for every symbol

Ranges from IPO/listing date (AAPL: 1980-12-13, 11,490 daily candles) down to the
newest listings in the universe (COIN: 2021-04-15, 1,321 daily candles; SNOW:
2020-09-17, 1,465 candles) — every single symbol clears "3+ years" of daily/weekly
history with wide margin. Index ETFs go back furthest of all (SPY to 1993).

## Data module built

`nero_core/data_sources/stock_data.py`: `fetch_stock_ohlcv(symbol, timeframe, start,
end)`, `StockDataResult`, `StockDataUnavailableError`, `resample_1h_to_4h_market_
hours_aware`. Reuses the exact `.dt.as_unit("ms")` timestamp-precision pattern
established for GOLD/SILVER/PLATINUM (see `nero_core/data_sources/market_data.py`) —
the same pandas-version resolution bug applies to any datetime-string-based source,
stocks included, and is guarded against from the start here rather than retrofitted.
