import { ASSET_CLASS_ORDER, classifyAsset } from "./assetClass";
import type { StrategyRosterEntry, StrategyStats } from "./types";

export interface AssetHeatmapTile {
  asset: string;
  strategyCount: number;
  resolvedTrades: number;
  winRate: number | null; // null = no resolved trades yet -- never fabricated
}

// One tile per single asset (BTC, GOLD, EUR/USD, AAPL, ...) -- pair assets
// (BTC-ETH, GOLD-SILVER) are excluded, same "-" convention lib/assetClass.ts's
// own classifyAsset uses to detect them, since a heatmap cell answering
// "how well does this ONE asset perform" doesn't map cleanly onto a two-leg
// pair. Sorted by the same ASSET_CLASS_ORDER (Crypto/Gold/Silver/Forex/Stocks)
// the rest of the site uses, so the grid reads in a consistent order.
export function buildAssetHeatmap(
  roster: StrategyRosterEntry[],
  stats: StrategyStats[]
): AssetHeatmapTile[] {
  const singleAssetNames = Array.from(
    new Set(roster.filter((entry) => !entry.asset.includes("-")).map((entry) => entry.asset))
  );

  const tiles = singleAssetNames.map((asset) => {
    const configs = roster.filter((entry) => entry.asset === asset);
    const statsForAsset = stats.filter((s) => s.asset === asset);
    const resolvedTrades = statsForAsset.reduce((sum, s) => sum + s.resolved_trades, 0);
    // Weighted by each config's own resolved_trades, so a 40-trade survivor
    // isn't drowned out by a 1-trade config sharing the same asset.
    const winRate =
      resolvedTrades > 0
        ? statsForAsset.reduce((sum, s) => sum + (s.win_rate ?? 0) * s.resolved_trades, 0) / resolvedTrades
        : null;
    return { asset, strategyCount: configs.length, resolvedTrades, winRate };
  });

  const classRank = new Map(ASSET_CLASS_ORDER.map((cls, i) => [cls, i]));
  return tiles.sort((a, b) => {
    const rankA = classRank.get(classifyAsset(a.asset).assetClass) ?? ASSET_CLASS_ORDER.length;
    const rankB = classRank.get(classifyAsset(b.asset).assetClass) ?? ASSET_CLASS_ORDER.length;
    return rankA !== rankB ? rankA - rankB : a.asset.localeCompare(b.asset);
  });
}

const NEUTRAL_GRAY: [number, number, number] = [138, 148, 173]; // muted
const LOSS_RGB: [number, number, number] = [212, 122, 106]; // loss-red, 0% win rate
const WIN_RGB: [number, number, number] = [46, 196, 182]; // teal, 100% win rate

// Continuous loss-red -> teal interpolation by win rate; fixed neutral gray
// (not an interpolated color) when there's no data at all -- a zero-trade
// asset must never render as if it had a 0% win rate.
export function heatmapTileColor(winRate: number | null, alpha: number = 1): string {
  const [r, g, b] = winRate === null ? NEUTRAL_GRAY : interpolate(winRate);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function interpolate(winRate: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, winRate));
  const channel = (i: 0 | 1 | 2) => Math.round(LOSS_RGB[i] + (WIN_RGB[i] - LOSS_RGB[i]) * t);
  return [channel(0), channel(1), channel(2)];
}
