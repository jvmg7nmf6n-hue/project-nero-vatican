import type { CorrelationPair, VolatilityRegimeEntry } from "./types";

export interface HeatmapCell {
  value: number | null; // null = self, no shared timeframe, or insufficient data -- never fabricated
  isSelf: boolean;
}

// Builds an assets.length x assets.length grid. `assets` should already be in the
// desired display order (this project's convention: ASSET_CLASS_ORDER then name --
// see lib/marketsOverview.ts's buildMarketAssetList, reused by the /quant page for
// exactly this ordering). A pair absent from `pairs` (different timeframes, or the
// same timeframe but zero overlapping calendar dates -- see nero_core.quant.
// cross_asset's own module docstring) renders as an "N/A" cell, never a guessed
// value.
export function buildCorrelationGrid(assets: string[], pairs: CorrelationPair[]): HeatmapCell[][] {
  const lookup = new Map<string, number | null>();
  for (const pair of pairs) {
    lookup.set(`${pair.asset_a}|${pair.asset_b}`, pair.correlation);
    lookup.set(`${pair.asset_b}|${pair.asset_a}`, pair.correlation);
  }

  return assets.map((rowAsset) =>
    assets.map((colAsset) => {
      if (rowAsset === colAsset) {
        return { value: null, isSelf: true };
      }
      const key = `${rowAsset}|${colAsset}`;
      return { value: lookup.has(key) ? lookup.get(key)! : null, isSelf: false };
    })
  );
}

const LOSS_RGB: [number, number, number] = [212, 122, 106]; // loss-red, correlation -1
const NEUTRAL_RGB: [number, number, number] = [138, 148, 173]; // muted gray, correlation 0
const TEAL_RGB: [number, number, number] = [46, 196, 182]; // teal, correlation +1

function lerp(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  return [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * clamped)) as [number, number, number];
}

// Continuous loss-red (-1) -> neutral gray (0) -> teal (+1) interpolation, the
// same three design-system anchor colors lib/assetHeatmap.ts's win-rate heatmap
// already uses, just over a [-1, 1] domain instead of [0, 1]. `null` (N/A / self)
// gets a faint, distinctly different neutral -- never interpolated as if it were a
// real zero correlation.
export function correlationColor(value: number | null, alpha: number = 1): string {
  if (value === null) {
    return `rgba(${NEUTRAL_RGB[0]}, ${NEUTRAL_RGB[1]}, ${NEUTRAL_RGB[2]}, ${alpha * 0.25})`;
  }
  const t = (Math.max(-1, Math.min(1, value)) + 1) / 2;
  const [r, g, b] = t < 0.5 ? lerp(LOSS_RGB, NEUTRAL_RGB, t * 2) : lerp(NEUTRAL_RGB, TEAL_RGB, (t - 0.5) * 2);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export const REGIME_COLOR: Record<VolatilityRegimeEntry["regime"], string> = {
  LOW: "#2ec4b6", // teal/green -- calm
  NORMAL: "#8a94ad", // muted gray
  HIGH: "#d4af37", // gold/amber
  EXTREME: "#d47a6a", // loss-red
  NO_DATA: "#8a94ad",
};

// Matches by (asset, timeframe) -- not asset alone -- since GOLD/SILVER each have
// two regime entries (one per timeframe) that can genuinely differ; a tile always
// displays one SPECIFIC timeframe's price data, so its badge must reflect that same
// timeframe's regime, never a different one that happens to share the asset name.
export function findVolatilityRegime(
  regimes: VolatilityRegimeEntry[],
  asset: string,
  timeframe: string
): VolatilityRegimeEntry | null {
  return regimes.find((r) => r.asset === asset && r.timeframe === timeframe) ?? null;
}
