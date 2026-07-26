# Day 2 of 7 — Candlestick Charts Closing Report

## What shipped

Strategy detail pages (`/strategy/[id]`) now show a real TradingView-style
candlestick chart with entry/exit trade markers, wherever Day 1's candle
export pipeline produced a file for that (asset, timeframe). A new tab
toggle — **Price Chart | Equity Curve** — sits above the chart area; both
views stay available, neither replaces the other.

## What was installed

- `lightweight-charts@^4.2.0` (TradingView's Apache-2.0 licensed charting
  library) added to `website/package.json`. No other charting dependency was
  added or considered.

## New/changed files

- `website/lib/candleData.ts` — `Candle`/`CandleFile` types, filename
  sanitization (`asset.replace("/", "")`, byte-identical to Day 1's Python
  `sanitize_asset_for_filename`), and the `daily` → `24h` timeframe alias
  needed for NEWS_SENTIMENT.
- `website/lib/chartMarkers.ts` — pure function `buildChartMarkers(trades,
  candles)` turning `ResolvedTrade[]` (from the existing `lib/tradeHistory.ts`
  pairing logic — not duplicated) into ENTRY/EXIT chart markers, silently
  dropping any trade whose entry or exit timestamp falls outside the fetched
  candle window.
- `website/components/CandlestickChart.tsx` — the `lightweight-charts`
  wrapper: navy background (`#0a0e27`), grid (`#1a2040`), teal up-candles
  (`#2ec4b6`), loss-red down-candles (`#d47a6a`), no watermark configured.
- `website/components/ChartTabs.tsx` — the tab toggle, wrapping both the new
  candlestick chart and the pre-existing `EquityCurveChart` (untouched).
- `website/lib/data.ts` — added `fetchCandleData()`, a dedicated fetch
  function (not a reuse of `fetchJson`) returning a 3-way discriminated
  union (`ok` / `not_found` / `error`) so the page can distinguish "this
  asset/timeframe was never in Day 1's export scope" from "the file exists
  but this fetch failed" — two different honest messages.
- `website/app/strategy/[id]/page.tsx` — wires it together: pair strategies
  (asset contains `-`) skip the fetch entirely and keep the old
  equity-curve-only section; everything else gets the new `ChartTabs`.
- `website/__mocks__/lightweight-charts.ts` — manual Jest mock exporting only
  the real library's own names (`ColorType`, `createChart`), each
  `createChart()` call returning a fresh mock chart/series pair.

## Coverage: which strategies get what

Cross-referencing the current roster (`docs/site_data/strategies.json`)
against Day 1's 16 exported candle files:

**Real candlestick chart** (candle file exists) — all roster entries except
the two below, including: BREAKOUT_MOMENTUM (GOLD, SILVER), TREND_PULLBACK
(BNB, SILVER), VOLATILITY_SQUEEZE (SILVER), RANGE_MEAN_REVERSION (GOLD,
SILVER, BTC), DONCHIAN_TREND (GOLD, EUR/USD, GBP/USD, USD/JPY),
NEWS_SENTIMENT (GOLD, BTC — via the `daily`→`24h` alias), and all 7 PEAD
equities (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META).

**"Price chart coming soon"** (no candle file — out of Day 1's export scope
by design, since an order-book snapshot has no OHLCV concept):
ORDERFLOW_IMBALANCE (BTC, ETH — `snapshot` timeframe).

**Equity-curve only, no Price Chart tab** (pair strategies — no single price
series to plot): COINTEGRATION_PAIRS (BTC-ETH), GOLD_SILVER_RATIO_MR
(GOLD-SILVER).

"Price data temporarily unavailable" is a live-fetch-failure state (network
error, non-404 bad response) — not expected to trigger for any currently
exported asset under normal operation, but every asset above is still
exercised by the corresponding test.

## Tests

37 new tests added across 6 files:

| File | New tests |
|---|---|
| `__tests__/candleData.test.ts` | 5 |
| `__tests__/chartMarkers.test.ts` | 9 |
| `__tests__/CandlestickChart.test.tsx` | 5 |
| `__tests__/ChartTabs.test.tsx` | 7 |
| `__tests__/data.test.ts` (`fetchCandleData` block) | 5 |
| `__tests__/strategyPage.test.tsx` (Day 2 block) | 6 |

Total suite size is now 182 tests. All fetches and candle data are mocked;
no real network calls, no `time.sleep`/timers of any kind.

Since no local Node install is available in this environment, every import
and mock-shape dependency was traced by hand rather than run — see the
per-file cross-checks below.

## Known limitations

- Never executed against a real Jest/Node runtime in this environment — the
  above is a manual trace, not a verified `npm test` pass. Traced explicitly:
  `CandlestickChart.tsx`'s `createChart`/`addCandlestickSeries` call shape
  against `__mocks__/lightweight-charts.ts`'s fresh-object-per-call design;
  `lib/chartMarkers.ts`'s `ResolvedTrade` field names against
  `lib/tradeHistory.ts`'s actual exported type; `lib/candleData.ts`'s
  sanitization/alias rules against Day 1's Python source and real filenames
  on disk; and `app/strategy/[id]/page.tsx`'s new `ChartTabs` usage against
  every testid asserted in `strategyPage.test.tsx`'s Day 2 block.
- Volume is not rendered — only OHLC candles and markers, per the task scope.
- Chart resize only re-applies `width` on window resize; height stays fixed
  at the CSS-driven 300px/400px.

## Next steps (not built this session)

Per the 7-day plan: Day 3+ covers whatever's scoped next (volume overlay,
additional indicator overlays, or moving to macro/ETF-flow work) — no code
for that has been started.
