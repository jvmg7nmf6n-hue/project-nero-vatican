# Third-party packages added for the CC-1 Part D website work

Utility/display code only — never judgment/verdict logic. Each entry below
is a pinned exact version, license-verified before use.

| Package | Version | License | Used for | Notes |
|---|---|---|---|---|
| `lightweight-charts` | 4.2.3 (already present) | Apache-2.0 | Candlestick charts | Pre-existing dependency, listed here for completeness of the license inventory. |
| `@xyflow/react` | 12.11.2 | MIT | Factory Loop pipeline diagram (D3) | Free core package only — no `@xyflow/react-pro` or any Pro-tier import anywhere in this repo. `proOptions.hideAttribution` is used, which the MIT license permits (attribution is a courtesy watermark, not a license term). |

`npm audit` (run after adding `@xyflow/react`) reports 6 pre-existing high-
severity advisories, all in `next`/`eslint-config-next`'s own transitive
dependency tree (`glob`, `js-yaml`, `postcss`, `next` itself) — none
introduced by `@xyflow/react`, confirmed via `npm ls @xyflow/react` showing
it as a dependency-free leaf. Fixing them requires an `eslint-config-
next`/`next` major-version bump, out of scope for this directive (a
CSS/diagramming/chart pass, not a framework upgrade).

## Packages evaluated and NOT added

| Package | License | Why not |
|---|---|---|
| `lightweight-charts-indicators` | MIT | Every published version (0.1.0-0.5.0) requires `oakscriptjs`, which requires `lightweight-charts@^5.0.0` for every version. Incompatible with this project's `lightweight-charts@^4.2.0` pin — confirmed via `npm view <pkg>@<version> peerDependencies`, not assumed. See `docs/investigations/website_chart_overlays_d2.md` for the full reasoning; MA/EMA/Bollinger Bands/VWAP were hand-rolled instead (`website/lib/indicators.ts`). |
| `lightweight-charts-drawing` | MIT | Same root cause — `0.1.1` peer-depends on `lightweight-charts@^5.0.0` directly. FibRetracement/TrendLine math hand-rolled instead (`website/lib/fibonacci.ts`). |
