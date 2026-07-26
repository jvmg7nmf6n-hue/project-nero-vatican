import { ASSET_CLASS_ORDER, classifyAsset } from "./assetClass";
import { candleFileTimeframe } from "./candleData";
import type { CandleFetchResult } from "./data";
import type { StrategyRosterEntry } from "./types";

export interface MarketAssetSpec {
  asset: string;
  timeframe: string; // the roster timeframe string to pass to fetchCandleData
}

// Duration of each candle-FILE timeframe token, in hours -- used only to pick the
// SHORTEST available timeframe when one asset trades at more than one (e.g. GOLD:
// both 1week and 24h across different strategies). Unrecognized tokens (currently
// just "snapshot", ORDERFLOW_IMBALANCE's order-book cadence -- no OHLCV concept, no
// candle file ever) sort last via Infinity, never crash the comparison.
const TIMEFRAME_DURATION_HOURS: Record<string, number> = {
  "12h": 12,
  "24h": 24,
  "1day": 24,
  "1week": 168,
};

function timeframeDurationHours(rosterTimeframe: string): number {
  const fileTimeframe = candleFileTimeframe(rosterTimeframe);
  return TIMEFRAME_DURATION_HOURS[fileTimeframe] ?? Number.POSITIVE_INFINITY;
}

// One spec per distinct single asset in the roster (pairs like "BTC-ETH" excluded --
// same "-" convention lib/assetHeatmap.ts's buildAssetHeatmap already uses, since a
// tile showing one price series doesn't map onto a two-leg pair). Sorted by
// ASSET_CLASS_ORDER then name, matching the heatmap's own reading order.
export function buildMarketAssetList(roster: StrategyRosterEntry[]): MarketAssetSpec[] {
  const shortestTimeframeByAsset = new Map<string, string>();
  for (const entry of roster) {
    if (entry.asset.includes("-")) continue;
    const current = shortestTimeframeByAsset.get(entry.asset);
    if (!current || timeframeDurationHours(entry.timeframe) < timeframeDurationHours(current)) {
      shortestTimeframeByAsset.set(entry.asset, entry.timeframe);
    }
  }

  const classRank = new Map(ASSET_CLASS_ORDER.map((cls, i) => [cls, i]));
  return Array.from(shortestTimeframeByAsset.entries())
    .map(([asset, timeframe]) => ({ asset, timeframe }))
    .sort((a, b) => {
      const rankA = classRank.get(classifyAsset(a.asset).assetClass) ?? ASSET_CLASS_ORDER.length;
      const rankB = classRank.get(classifyAsset(b.asset).assetClass) ?? ASSET_CLASS_ORDER.length;
      return rankA !== rankB ? rankA - rankB : a.asset.localeCompare(b.asset);
    });
}

export function strategyCountForAsset(roster: StrategyRosterEntry[], asset: string): number {
  return roster.filter((entry) => entry.asset === asset).length;
}

export interface SparklineResult {
  path: string; // SVG "d" path attribute, viewBox "0 0 width height"
  trend: "up" | "down"; // net change over the window: last close vs first close
}

export const SPARKLINE_WIDTH = 100;
export const SPARKLINE_HEIGHT = 32;
export const SPARKLINE_CANDLE_COUNT = 50;

// Pure SVG path generator -- no chart library. Normalizes closes into the
// [0, height] range (flipped, since SVG y grows downward) and spaces them evenly
// across [0, width]. A perfectly flat price series (min === max) still produces a
// valid flat line down the middle rather than dividing by zero.
export function buildSparkline(
  closes: number[],
  width: number = SPARKLINE_WIDTH,
  height: number = SPARKLINE_HEIGHT
): SparklineResult | null {
  if (closes.length < 2) {
    return null;
  }
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const stepX = width / (closes.length - 1);
  const points = closes.map((close, i) => {
    const x = i * stepX;
    const y = height - ((close - min) / range) * height;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const net = closes[closes.length - 1] - closes[0];
  return { path: `M ${points.join(" L ")}`, trend: net >= 0 ? "up" : "down" };
}

export interface PriceChange {
  price: number;
  changePct: number | null; // null when fewer than 2 closes are available to compare
}

export function computePriceChange(closes: number[]): PriceChange | null {
  if (closes.length === 0) {
    return null;
  }
  const price = closes[closes.length - 1];
  if (closes.length < 2) {
    return { price, changePct: null };
  }
  const previous = closes[closes.length - 2];
  const changePct = previous !== 0 ? ((price - previous) / previous) * 100 : null;
  return { price, changePct };
}

export type MarketTile =
  | {
      status: "ok";
      asset: string;
      price: number;
      changePct: number | null;
      sparklinePath: string;
      trend: "up" | "down";
      strategyCount: number;
    }
  | { status: "placeholder"; asset: string; strategyCount: number };

// Ties fetch results back to their specs by ARRAY POSITION (same order/length,
// exactly how Promise.all(specs.map(...)) produces them) rather than by asset name,
// since two specs never share an asset. A single failed/missing fetch degrades only
// that one tile to "placeholder" -- neighboring tiles are built independently and are
// never affected by another asset's failure.
export function buildMarketTiles(
  specs: MarketAssetSpec[],
  results: CandleFetchResult[],
  roster: StrategyRosterEntry[]
): MarketTile[] {
  return specs.map((spec, i) => {
    const strategyCount = strategyCountForAsset(roster, spec.asset);
    const result = results[i];
    if (!result || result.status !== "ok") {
      return { status: "placeholder", asset: spec.asset, strategyCount };
    }
    const closes = result.data.candles.slice(-SPARKLINE_CANDLE_COUNT).map((c) => c.close);
    const sparkline = buildSparkline(closes);
    const priceChange = computePriceChange(closes);
    if (!sparkline || !priceChange) {
      return { status: "placeholder", asset: spec.asset, strategyCount };
    }
    return {
      status: "ok",
      asset: spec.asset,
      price: priceChange.price,
      changePct: priceChange.changePct,
      sparklinePath: sparkline.path,
      trend: sparkline.trend,
      strategyCount,
    };
  });
}
