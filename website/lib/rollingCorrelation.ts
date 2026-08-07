import type { Candle } from "./candleData";

/**
 * CC-1 Part D4/D5 — rolling correlation, computed in the website layer from
 * already-exported real candle data (docs/site_data/candles/*.json), for the
 * /quant page's 3D/4D correlation surface.
 *
 * Deliberately mirrors `nero_core/quant/cross_asset.py::rolling_correlation_matrix`'s
 * own method (log returns, inner-join alignment on REAL shared timestamps --
 * never positional alignment, window=30) rather than inventing a different
 * statistic, so a reader comparing the /quant page's existing 2D matrix
 * (server-computed) against this surface's frames isn't looking at two
 * different definitions of "correlation." This file does NOT import or call
 * into nero_core (website-layer only, per the directive's own ground rule) --
 * it's an independent, from-scratch computation over the same public JSON
 * this page already fetches, kept in the same style for consistency, not
 * imported for isolation.
 *
 * NO FABRICATION: a frame's cell is `null` whenever fewer than `window`
 * aligned return observations exist at that point -- never interpolated,
 * never backfilled. Frames are spaced across the REAL available history,
 * never invented between two real points.
 */

const MIN_WINDOW_OBSERVATIONS = 30; // matches cross_asset.py's own MIN_OBSERVATIONS / window default

export function computeLogReturns(closes: number[]): number[] {
  const returns: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    returns.push(Math.log(closes[i] / closes[i - 1]));
  }
  return returns;
}

export function pearsonCorrelation(x: number[], y: number[]): number | null {
  if (x.length !== y.length || x.length === 0) return null;
  const n = x.length;
  const meanX = x.reduce((a, b) => a + b, 0) / n;
  const meanY = y.reduce((a, b) => a + b, 0) / n;
  let cov = 0;
  let varX = 0;
  let varY = 0;
  for (let i = 0; i < n; i++) {
    const dx = x[i] - meanX;
    const dy = y[i] - meanY;
    cov += dx * dy;
    varX += dx * dx;
    varY += dy * dy;
  }
  if (varX === 0 || varY === 0) return null;
  return cov / Math.sqrt(varX * varY);
}

/**
 * Aligns every asset's candles to the timestamps shared by ALL of them (inner
 * join across the full set, generalizing cross_asset.py's own pairwise inner
 * join) -- returns, per asset, the log-return series over that shared grid.
 * Returns {} if there's no common timestamp grid at all.
 */
export function alignAndComputeReturns(
  candlesByAsset: Record<string, Candle[]>
): { times: number[]; returnsByAsset: Record<string, number[]> } {
  const assets = Object.keys(candlesByAsset);
  if (assets.length === 0) return { times: [], returnsByAsset: {} };

  let sharedTimes: number[] | null = null;
  for (const asset of assets) {
    const times: Set<number> = new Set(candlesByAsset[asset].map((c) => c.time));
    sharedTimes = sharedTimes === null ? Array.from(times) : sharedTimes.filter((t) => times.has(t));
  }
  const sortedShared = (sharedTimes ?? []).slice().sort((a, b) => a - b);

  const returnsByAsset: Record<string, number[]> = {};
  for (const asset of assets) {
    const byTime = new Map(candlesByAsset[asset].map((c) => [c.time, c.close]));
    const alignedCloses = sortedShared.map((t) => byTime.get(t) as number);
    returnsByAsset[asset] = computeLogReturns(alignedCloses);
  }
  // computeLogReturns produces one fewer point than its input -- drop the first shared time to match.
  return { times: sortedShared.slice(1), returnsByAsset };
}

export interface CorrelationFrame {
  time: number; // the real timestamp this frame's rolling window ends at
  matrix: (number | null)[][]; // assets.length x assets.length
}

/**
 * Computes `frameCount` correlation matrices for `assets`, spaced evenly
 * across the real available aligned-return history (never more frames than
 * there are genuinely distinct windows to compute). Each frame's matrix cell
 * is a `window`-period trailing Pearson correlation of log returns ending at
 * that frame's own real timestamp -- `null` where fewer than `window`
 * observations exist yet (e.g. every frame before enough history has
 * accumulated).
 */
export function computeCorrelationFrames(
  candlesByAsset: Record<string, Candle[]>,
  assets: string[],
  window: number = MIN_WINDOW_OBSERVATIONS,
  frameCount: number = 8
): CorrelationFrame[] {
  const { times, returnsByAsset } = alignAndComputeReturns(candlesByAsset);
  const n = times.length;
  if (n < window) return [];

  // Evenly-spaced END indices across [window-1, n-1], deduplicated -- real
  // spacing across real history, never fabricated in between.
  const lastValidIndex = n - 1;
  const firstValidIndex = window - 1;
  const span = lastValidIndex - firstValidIndex;
  const stepCount = Math.min(frameCount, span + 1);
  const indices = Array.from(new Set(
    Array.from({ length: stepCount }, (_, i) =>
      firstValidIndex + Math.round((i * span) / Math.max(1, stepCount - 1))
    )
  )).sort((a, b) => a - b);

  return indices.map((endIndex) => {
    const matrix: (number | null)[][] = assets.map((rowAsset) =>
      assets.map((colAsset) => {
        if (rowAsset === colAsset) return 1;
        const x = returnsByAsset[rowAsset]?.slice(endIndex - window + 1, endIndex + 1);
        const y = returnsByAsset[colAsset]?.slice(endIndex - window + 1, endIndex + 1);
        if (!x || !y || x.length < window || y.length < window) return null;
        return pearsonCorrelation(x, y);
      })
    );
    return { time: times[endIndex], matrix };
  });
}
