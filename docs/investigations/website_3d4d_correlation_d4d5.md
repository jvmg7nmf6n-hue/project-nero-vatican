# Website D4/D5 — 3D/4D correlation surface

Date: 2026-08-07. CC-1 comprehensive directive, Parts D4/D5.

## Finding: the directive names `/heatmap`, but the real x/y/z data lives on `/quant`

`app/heatmap/page.tsx` shows one value PER ASSET (aggregate win rate) — a
1D tile view, with no pairwise x/y relationship to put on a surface at all.
The actual "x/y = asset pairs, z = correlation coefficient" data the
directive describes is `app/quant/page.tsx`'s existing `CorrelationHeatmap`
(a flat 2D grid). This is a stale/confused page reference in the original
directive, corrected here rather than building a surface for `/heatmap`
that its own data can't support. The 3D/4D surface ships on `/quant`,
alongside the existing 2D matrix (which stays, unchanged — this is an
addition, not a replacement).

## Real data plumbing (reported first, per the directive's own ask)

- The 2D matrix's data (`docs/site_data/quant_cross_asset.json`'s
  `correlation_matrix`) is a single most-recent-value snapshot — confirmed
  in `nero_core/quant/cross_asset.py::rolling_correlation_matrix`, which
  reads `docs/site_data/candles/*.json`, inner-joins each pair on REAL
  shared timestamps (never positional alignment — the module's own
  docstring documents a real, confirmed case where SILVER's business-days
  futures grid shares zero timestamps with BTC/GOLD's 24/7 grid despite
  sharing a "24h" label), and returns only `series_corr.iloc[-1]`.
- For a real, non-fabricated TIME dimension (D5), no historical multi-frame
  export exists. Per the directive's own instruction ("every frame from
  real correlation computations already available or CHEAPLY DERIVABLE
  FROM EXPORTED CANDLE DATA") and the "Website-layer only" ground rule
  (no `nero_core` changes for Part D), additional frames are computed
  ENTIRELY in the website layer, in TypeScript, from the same
  `docs/site_data/candles/*.json` files the page already has access to via
  `fetchCandleData` — `website/lib/rollingCorrelation.ts`.
- **Which assets**: checked `quant_cross_asset.json` directly for which
  group of assets has the most REAL (non-null) pairwise correlations —
  the 7 mega-cap tech equities (AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA)
  at `1day` all have real, non-null pairwise correlations (59 of 131 total
  pairs project-wide are real; every single one among these 7 is real).
  Confirmed their candle files share the EXACT same 200 timestamps
  (`1760673600` to `1785902400`) — a fully-overlapping real calendar grid,
  unlike most cross-asset-class pairs. This is the one group where a
  surface has zero N/A gaps to render.

## Why the website-layer computation isn't a diverging reimplementation

`lib/rollingCorrelation.ts` mirrors `cross_asset.py`'s own method precisely
(log returns, inner-join alignment on real timestamps — never positional,
30-observation window) rather than inventing a different statistic, so a
reader comparing the /quant page's existing 2D matrix against the new
surface isn't looking at two different definitions of "correlation." It
does NOT import `nero_core` (website-layer only, confirmed via `grep` —
zero Python imports anywhere in `website/`).

## What shipped

- `lib/rollingCorrelation.ts`: `computeLogReturns`, `pearsonCorrelation`,
  `alignAndComputeReturns` (inner-join on shared timestamps across an
  arbitrary number of assets, generalizing the pairwise case),
  `computeCorrelationFrames` (evenly-spaced frames across the real
  available aligned history — `null` cells wherever fewer than `window`
  aligned observations exist yet, never fabricated or interpolated).
- `components/Correlation3DSurface.tsx`: client component, dynamically
  imports `plotly.js-dist` (not SSR-safe — touches the DOM/canvas
  directly), renders a `type: "surface"` trace with the site's own loss-
  red/muted/teal colorscale (matching `lib/quantCrossAsset.ts`'s existing
  2D heatmap color anchors, same -1..+1 domain), plus a real Plotly slider
  wired to `Plotly.addFrames`/the slider's `animate` steps — each step
  label is the frame's own real end-date (`YYYY-MM-DD`), never a fabricated
  or interpolated one.
- Wired into `/quant` as a new section, directly below the existing 2D
  matrix (which is unchanged).

## Verification

- 9 new unit tests (`__tests__/rollingCorrelation.test.ts`): log returns,
  Pearson correlation (including the zero-variance null case), timestamp-
  based alignment (confirmed NOT positional — a deliberately staggered
  test case would silently pass with positional alignment and fail with
  the real timestamp-join, and this test catches exactly that), frame
  count/spacing, and the "not enough history" empty-array case.
- `next build` compiles clean (fixed one real `react-hooks/exhaustive-deps`
  lint warning: copied `containerRef.current` to a local variable before
  the cleanup closure, the same pattern React's own lint rule recommends).
- `npx jest`: existing `quantPage.test.tsx` needed one addition — its
  `jest.mock("@/lib/data")` auto-mock left the new `fetchCandleData` calls
  returning `undefined` instead of a Promise, crashing 4 pre-existing
  tests. Fixed with a `beforeEach` default (`mockResolvedValue({status:
  "not_found"})`), which is also the honest simulated behavior for tests
  that predate this section. 653/655 passing after (2 pre-existing,
  unrelated `siteDataSchema.test.ts` failures, same as every other Part D
  report this session).
- Real Playwright screenshot of `/quant`: the 3D surface renders correctly
  with the real colorscale, a working time slider (`Window ending:
  2025-12-01` through `2026-08-05`, matching the real candle date range),
  and the D2 footer attribution link is visible in the same screenshot.

## Package added

`plotly.js-dist@3.7.0` (MIT) + `@types/plotly.js@3.0.13` (dev, MIT) — see
`THIRD_PARTY_LICENSES.md`. A small type shim
(`website/types/plotly-js-dist.d.ts`) re-exports `@types/plotly.js`'s
declarations under the `plotly.js-dist` import specifier actually used,
since `plotly.js-dist` ships no bundled types and the types package
declares a different module name (the two packages are otherwise the
identical runtime API — `plotly.js-dist` is `plotly.js` pre-bundled for
the browser).
