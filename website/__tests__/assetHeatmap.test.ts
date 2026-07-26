import { buildAssetHeatmap, heatmapTileColor } from "@/lib/assetHeatmap";
import type { StrategyRosterEntry, StrategyStats } from "@/lib/types";

function makeEntry(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "verified",
    source_report: null,
    ...overrides,
  };
}

function makeStats(overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    resolved_trades: 0,
    win_rate: null,
    expectancy_r: null,
    avg_return_pct: null,
    signal_counts: { ENTRY: 0, EXIT: 0, WATCH: 0, NO_TRADE: 0 },
    open_position: null,
    ...overrides,
  };
}

describe("buildAssetHeatmap", () => {
  it("returns one tile per distinct single asset", () => {
    const roster = [makeEntry({ asset: "GOLD" }), makeEntry({ asset: "BTC" }), makeEntry({ asset: "GOLD" })];
    const tiles = buildAssetHeatmap(roster, []);
    expect(tiles.map((t) => t.asset).sort()).toEqual(["BTC", "GOLD"]);
  });

  it("excludes pair assets (containing a hyphen)", () => {
    const roster = [makeEntry({ asset: "GOLD" }), makeEntry({ asset: "BTC-ETH", name: "COINTEGRATION_PAIRS" })];
    const tiles = buildAssetHeatmap(roster, []);
    expect(tiles.map((t) => t.asset)).toEqual(["GOLD"]);
  });

  it("gives a null win rate (not zero) when an asset has zero resolved trades", () => {
    const roster = [makeEntry({ asset: "GOLD" })];
    const stats = [makeStats({ asset: "GOLD", resolved_trades: 0 })];
    const tiles = buildAssetHeatmap(roster, stats);
    expect(tiles[0].winRate).toBeNull();
    expect(tiles[0].resolvedTrades).toBe(0);
  });

  it("computes a weighted-average win rate across multiple configs sharing an asset", () => {
    const roster = [
      makeEntry({ asset: "SILVER", name: "TREND_PULLBACK" }),
      makeEntry({ asset: "SILVER", name: "VOLATILITY_SQUEEZE" }),
    ];
    const stats = [
      makeStats({ asset: "SILVER", strategy: "TREND_PULLBACK", resolved_trades: 10, win_rate: 0.6 }),
      makeStats({ asset: "SILVER", strategy: "VOLATILITY_SQUEEZE", resolved_trades: 40, win_rate: 0.4 }),
    ];
    const tiles = buildAssetHeatmap(roster, stats);
    // (10*0.6 + 40*0.4) / 50 = (6 + 16) / 50 = 0.44
    expect(tiles[0].winRate).toBeCloseTo(0.44);
    expect(tiles[0].resolvedTrades).toBe(50);
  });

  it("sorts tiles by the site's standard asset-class order (Crypto, Gold, Silver, Forex, Stocks)", () => {
    const roster = [
      makeEntry({ asset: "AAPL" }),
      makeEntry({ asset: "GOLD" }),
      makeEntry({ asset: "BTC" }),
      makeEntry({ asset: "EUR/USD" }),
    ];
    const tiles = buildAssetHeatmap(roster, []);
    expect(tiles.map((t) => t.asset)).toEqual(["BTC", "GOLD", "EUR/USD", "AAPL"]);
  });
});

describe("heatmapTileColor", () => {
  it("returns a neutral gray for null (no data), not an interpolated color", () => {
    expect(heatmapTileColor(null)).toBe("rgba(138, 148, 173, 1)");
  });

  it("returns the loss-red end of the scale at 0% win rate", () => {
    expect(heatmapTileColor(0)).toBe("rgba(212, 122, 106, 1)");
  });

  it("returns the teal end of the scale at 100% win rate", () => {
    expect(heatmapTileColor(1)).toBe("rgba(46, 196, 182, 1)");
  });

  it("respects the alpha parameter", () => {
    expect(heatmapTileColor(1, 0.12)).toBe("rgba(46, 196, 182, 0.12)");
  });

  it("clamps out-of-range win rates rather than producing invalid colors", () => {
    expect(heatmapTileColor(1.5)).toBe(heatmapTileColor(1));
    expect(heatmapTileColor(-0.5)).toBe(heatmapTileColor(0));
  });
});
