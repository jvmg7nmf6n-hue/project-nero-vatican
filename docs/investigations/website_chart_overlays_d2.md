# Website D2 — Chart overlays

Date: 2026-08-07. CC-1 comprehensive directive, Part D2.

## Finding: both named vendor packages are incompatible with this project's `lightweight-charts` version — confirmed, not assumed

The directive named two packages: `lightweight-charts-indicators` (MA/EMA/
Bollinger Bands) and `lightweight-charts-drawing` (FibRetracement +
TrendLine). Both are real, MIT-licensed, real packages by the same author
(deepentropy). Checked via `npm view <pkg>@<version> peerDependencies`
across every published version before installing anything:

- `lightweight-charts-indicators` (0.1.0 through 0.5.0) peer-depends on
  `oakscriptjs`.
- Every published version of `oakscriptjs` (0.1.5 through 0.5.0) peer-
  depends on `lightweight-charts@^5.0.0`.
- `lightweight-charts-drawing@0.1.1` peer-depends on
  `lightweight-charts@^5.0.0` directly.

This project's own `package.json` pins `lightweight-charts@^4.2.0`
(4.2.3 installed) — there is no published version of either named package
compatible with it. `npm install` confirms this with a real `ERESOLVE`
error, not a guess.

**Forcing it with `--legacy-peer-deps` was rejected, not just avoided as a
convenience.** `lightweight-charts` v5 changed series creation
(`chart.addSeries(CandlestickSeries, opts)` replaces v4's
`chart.addCandlestickSeries(opts)`) and moved markers out of the series API
into a separate `createSeriesMarkers` plugin primitive. Using either named
package would mean either (a) feeding v5-oriented code a v4 chart instance
(a real runtime mismatch, not a lint warning), or (b) upgrading the whole
project's `lightweight-charts` to v5 — which would require rewriting
`CandlestickChart.tsx`'s `series.setMarkers(...)` call, the exact mechanism
this directive explicitly protects ("`setMarkers` already exists — don't
rebuild it").

**Resolution: hand-roll every overlay**, extending the SAME reasoning the
directive already applied to VWAP ("write it as a custom ~10-line
utility... don't pull it from the indicators package — it's not confirmed
to export VWAP") to MA/EMA/Bollinger Bands/Fibonacci/TrendLine too, since
every one of them is a well-known, small formula. `setMarkers` is untouched
— still `lightweight-charts@4.2.3`, still the original v4 API, still the
exact call the existing `CandlestickChart.tsx` already made.

## What shipped

- `website/lib/indicators.ts` — pure functions `computeSMA`, `computeEMA`,
  `computeBollingerBands`, `computeVWAP`. VWAP follows the directive's own
  formula (`cumsum(price*volume)/cumsum(volume)`, using typical price
  `(H+L+C)/3`) and returns `[]` (never a fabricated line) the moment any
  candle's `volume` is `null` — matching this codebase's own "VOLUME
  HONESTY" convention (`nero_core/execution/export_candle_data.py`) that a
  null volume means the source genuinely doesn't provide real volume.
- `website/lib/fibonacci.ts` — `computeFibRetracementLevels` (standard
  0/0.236/0.382/0.5/0.618/0.786/1 ratios between a swing high/low) and
  `makeTrendLine` (a two-point line struct). Not yet wired into the chart UI
  this pass (no swing-detection UI exists yet to pick the two points from)
  — the computation is real and tested, the interactive picker is a
  reasonable follow-up, not attempted here to avoid inventing UI beyond
  what was asked.
- `website/components/CandlestickChart.tsx` — new optional `overlays` prop
  (`{ ma?, ema?, bollinger?, vwap? }`), each rendered as a `lightweight-
  charts` v4 `addLineSeries` (unchanged API, unchanged `setMarkers` call).
  MA/EMA use a 20-period lookback, matching this codebase's own existing
  `ma_period=20` standard (e.g. `orderflow_imbalance.py`'s MA20 gate) —
  not invented for this chart. Bollinger Bands: 20-period, 2 stdev.
- `website/components/ChartTabs.tsx` — 4 checkboxes (MA20/EMA20/Bollinger
  Bands/VWAP), off by default, opt-in.
- Apache-2.0 attribution: confirmed there was NO visible link anywhere on
  the site before this pass (checked `layout.tsx`, `Logo.tsx`, and grepped
  for "TradingView"/"Apache" — none). Added one to the site footer
  (`app/layout.tsx`), linking to the real upstream repo.
- `website/__mocks__/lightweight-charts.ts` extended with `addLineSeries`
  (same minimal jest-mock shape as the existing `addCandlestickSeries`
  mock).

## Verification

- 10 new unit tests for the indicator/fibonacci math
  (`__tests__/indicators.test.ts`, `__tests__/fibonacci.test.ts`), each
  checked against a hand-computed expected value.
- 4 new `CandlestickChart` tests: no overlay series added when none
  requested; one line series per requested overlay with distinct colors;
  Bollinger Bands adds exactly two series (upper+lower); VWAP adds zero
  series when any candle has null volume (never fabricates).
- Real Playwright screenshots, dev server:
  - `ORDERFLOW_IMBALANCE/BTC` — confirmed it has **no price chart at all**
    ("Price chart coming soon"), a structural fact (order-book snapshots
    have no OHLCV/candle series to render), not a markers bug. Overlay
    toggles correctly don't render either, since there's no price chart to
    toggle them on.
  - `PEAD/AAPL` — confirmed all 4 overlays render correctly and are
    visually distinct (MA20 gold, EMA20 teal, Bollinger Bands muted upper/
    lower, VWAP parchment), and the existing `ENTRY` marker (`setMarkers`,
    untouched) renders correctly alongside them. This directly answers the
    directive's own question: markers DO render correctly for a strategy
    that actually has trades and real candle data.
- `next build` compiles; `npx jest` 644/646 passing (the same 2 pre-
  existing, unrelated `siteDataSchema.test.ts` failures as every prior
  Part D report in this session — a real-data drift issue in
  `docs/site_data/failure_patterns.json`, never touched by this directive).

## Not done, honestly

- Fibonacci/TrendLine have no chart-embedded UI yet (computation only,
  tested). Wiring them onto the chart needs a swing-point picker
  interaction that wasn't specified in enough detail to build without
  inventing UX beyond the directive's own scope — flagged as a follow-up,
  not silently skipped.
