import {
  buildMarketAssetList,
  buildMarketTiles,
  buildSparkline,
  computePriceChange,
  strategyCountForAsset,
} from "@/lib/marketsOverview";
import type { CandleFetchResult } from "@/lib/data";
import type { StrategyRosterEntry } from "@/lib/types";

function entry(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "v1",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "verified",
    source_report: null,
    ...overrides,
  };
}

describe("buildMarketAssetList", () => {
  it("excludes pair assets (contain a hyphen)", () => {
    const roster = [
      entry({ asset: "BTC-ETH", timeframe: "12h" }),
      entry({ asset: "GOLD-SILVER", timeframe: "24h" }),
      entry({ asset: "BTC", timeframe: "24h" }),
    ];
    const specs = buildMarketAssetList(roster);
    expect(specs.map((s) => s.asset)).toEqual(["BTC"]);
  });

  it("returns one spec per distinct single asset", () => {
    const roster = [entry({ asset: "BTC" }), entry({ asset: "BTC" }), entry({ asset: "GOLD" })];
    const specs = buildMarketAssetList(roster);
    expect(specs.map((s) => s.asset).sort()).toEqual(["BTC", "GOLD"]);
  });

  it("picks the SHORTEST available timeframe when an asset trades at more than one", () => {
    const roster = [
      entry({ asset: "GOLD", timeframe: "1week" }),
      entry({ asset: "GOLD", timeframe: "daily" }), // aliases to the 24h candle file -- shorter than 1week
    ];
    const specs = buildMarketAssetList(roster);
    expect(specs).toEqual([{ asset: "GOLD", timeframe: "daily" }]);
  });

  it("keeps the only timeframe available when there is just one", () => {
    const roster = [entry({ asset: "BNB", timeframe: "12h" })];
    const specs = buildMarketAssetList(roster);
    expect(specs).toEqual([{ asset: "BNB", timeframe: "12h" }]);
  });

  it("an unrecognized timeframe (e.g. ORDERFLOW_IMBALANCE's snapshot) never crashes and is never preferred over a real one", () => {
    const roster = [
      entry({ asset: "ETH", timeframe: "snapshot" }),
      entry({ asset: "ETH", timeframe: "24h" }),
    ];
    const specs = buildMarketAssetList(roster);
    expect(specs).toEqual([{ asset: "ETH", timeframe: "24h" }]);
  });
});

describe("strategyCountForAsset", () => {
  it("counts only exact asset matches, excluding pairs that merely involve it", () => {
    const roster = [
      entry({ asset: "BTC" }),
      entry({ asset: "BTC" }),
      entry({ asset: "BTC-ETH" }),
      entry({ asset: "GOLD" }),
    ];
    expect(strategyCountForAsset(roster, "BTC")).toBe(2);
    expect(strategyCountForAsset(roster, "GOLD")).toBe(1);
  });
});

describe("buildSparkline", () => {
  it("produces the expected path for a known small input", () => {
    // closes [10, 20, 10] over width=100, height=32: min=10, max=20, range=10.
    // x steps: 0, 50, 100. y = height - ((close-min)/range)*height.
    const result = buildSparkline([10, 20, 10], 100, 32);
    expect(result).not.toBeNull();
    expect(result!.path).toBe("M 0.00,32.00 L 50.00,0.00 L 100.00,32.00");
  });

  it("marks trend 'up' when the last close is >= the first", () => {
    expect(buildSparkline([10, 12, 15])!.trend).toBe("up");
    expect(buildSparkline([10, 8, 10])!.trend).toBe("up"); // net 0 -- ties go to "up"
  });

  it("marks trend 'down' when the last close is below the first", () => {
    expect(buildSparkline([15, 12, 10])!.trend).toBe("down");
  });

  it("never divides by zero on a perfectly flat price series", () => {
    const result = buildSparkline([100, 100, 100]);
    expect(result).not.toBeNull();
    expect(result!.path).not.toMatch(/NaN/);
  });

  it("returns null with fewer than 2 closes", () => {
    expect(buildSparkline([])).toBeNull();
    expect(buildSparkline([100])).toBeNull();
  });
});

describe("computePriceChange", () => {
  it("computes price and change% from the last two closes", () => {
    const result = computePriceChange([100, 90, 110]);
    expect(result).toEqual({ price: 110, changePct: (110 - 90) / 90 * 100 });
  });

  it("returns changePct null with exactly one close", () => {
    expect(computePriceChange([100])).toEqual({ price: 100, changePct: null });
  });

  it("returns null with zero closes", () => {
    expect(computePriceChange([])).toBeNull();
  });
});

describe("buildMarketTiles", () => {
  const roster = [entry({ asset: "BTC" }), entry({ asset: "BTC" }), entry({ asset: "GOLD" })];

  function okResult(closes: number[]): CandleFetchResult {
    return {
      status: "ok",
      data: {
        schema_version: 1,
        asset: "X",
        timeframe: "24h",
        last_updated: "x",
        candles: closes.map((close, i) => ({ time: i, open: close, high: close, low: close, close, volume: null })),
      },
    };
  }

  it("builds an 'ok' tile with price/change/sparkline/strategyCount from a successful fetch", () => {
    const specs = [{ asset: "BTC", timeframe: "24h" }];
    const results: CandleFetchResult[] = [okResult([100, 105, 110])];
    const tiles = buildMarketTiles(specs, results, roster);

    expect(tiles).toHaveLength(1);
    expect(tiles[0]).toMatchObject({ status: "ok", asset: "BTC", price: 110, strategyCount: 2 });
  });

  it("builds a 'placeholder' tile when the fetch result is not_found", () => {
    const specs = [{ asset: "GOLD", timeframe: "24h" }];
    const results: CandleFetchResult[] = [{ status: "not_found" }];
    const tiles = buildMarketTiles(specs, results, roster);
    expect(tiles[0]).toEqual({ status: "placeholder", asset: "GOLD", strategyCount: 1 });
  });

  it("builds a 'placeholder' tile when the fetch result is an error", () => {
    const specs = [{ asset: "GOLD", timeframe: "24h" }];
    const results: CandleFetchResult[] = [{ status: "error" }];
    const tiles = buildMarketTiles(specs, results, roster);
    expect(tiles[0].status).toBe("placeholder");
  });

  it("isolates one asset's failure from another asset's success (order preserved)", () => {
    const specs = [
      { asset: "BTC", timeframe: "24h" },
      { asset: "GOLD", timeframe: "24h" },
    ];
    const results: CandleFetchResult[] = [{ status: "error" }, okResult([50, 55])];
    const tiles = buildMarketTiles(specs, results, roster);

    expect(tiles[0]).toEqual({ status: "placeholder", asset: "BTC", strategyCount: 2 });
    expect(tiles[1]).toMatchObject({ status: "ok", asset: "GOLD", price: 55 });
  });

  it("falls back to a placeholder if the candle file has fewer than 2 candles (can't compute a sparkline)", () => {
    const specs = [{ asset: "BTC", timeframe: "24h" }];
    const results: CandleFetchResult[] = [okResult([100])];
    const tiles = buildMarketTiles(specs, results, roster);
    expect(tiles[0].status).toBe("placeholder");
  });
});
