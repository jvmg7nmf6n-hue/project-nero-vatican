import { buildCorrelationGrid, correlationColor, findVolatilityRegime, REGIME_COLOR } from "@/lib/quantCrossAsset";
import type { CorrelationPair, VolatilityRegimeEntry } from "@/lib/types";

function pair(overrides: Partial<CorrelationPair> = {}): CorrelationPair {
  return {
    asset_a: "BTC",
    asset_b: "GOLD",
    timeframe: "24h",
    correlation: 0.15,
    window_used: 30,
    computed_at: "2026-07-27T00:00:00+00:00",
    ...overrides,
  };
}

function regime(overrides: Partial<VolatilityRegimeEntry> = {}): VolatilityRegimeEntry {
  return {
    asset: "BTC",
    timeframe: "24h",
    regime: "NORMAL",
    conditional_vol: 0.3,
    vol_ratio: 1.0,
    shock_score: 50,
    model_used: "EWMA fallback",
    computed_at: "2026-07-27T00:00:00+00:00",
    ...overrides,
  };
}

describe("buildCorrelationGrid", () => {
  it("fills a cell from a matching pair, in either row/column order", () => {
    const grid = buildCorrelationGrid(["BTC", "GOLD"], [pair({ asset_a: "BTC", asset_b: "GOLD", correlation: 0.42 })]);
    expect(grid[0][1].value).toBe(0.42);
    expect(grid[1][0].value).toBe(0.42); // symmetric regardless of pair's own asset_a/asset_b order
  });

  it("marks the diagonal as self, never a fabricated 1.0", () => {
    const grid = buildCorrelationGrid(["BTC", "GOLD"], [pair()]);
    expect(grid[0][0].isSelf).toBe(true);
    expect(grid[0][0].value).toBeNull();
  });

  it("marks a missing pair as N/A (null), not zero", () => {
    const grid = buildCorrelationGrid(["BTC", "GOLD", "AAPL"], [pair({ asset_a: "BTC", asset_b: "GOLD" })]);
    const btcAaplCell = grid[0][2];
    expect(btcAaplCell.value).toBeNull();
    expect(btcAaplCell.isSelf).toBe(false);
  });

  it("passes through a null correlation (insufficient overlap) as null, not zero", () => {
    const grid = buildCorrelationGrid(["BTC", "GOLD"], [pair({ correlation: null })]);
    expect(grid[0][1].value).toBeNull();
  });
});

describe("correlationColor", () => {
  it("returns the teal anchor color at +1", () => {
    expect(correlationColor(1)).toBe("rgba(46, 196, 182, 1)");
  });

  it("returns the loss-red anchor color at -1", () => {
    expect(correlationColor(-1)).toBe("rgba(212, 122, 106, 1)");
  });

  it("returns the neutral gray anchor color at 0", () => {
    expect(correlationColor(0)).toBe("rgba(138, 148, 173, 1)");
  });

  it("returns a distinctly faint neutral for null (N/A), never interpolated as zero", () => {
    const nullColor = correlationColor(null);
    const zeroColor = correlationColor(0);
    expect(nullColor).not.toBe(zeroColor);
    expect(nullColor).toContain("0.25");
  });

  it("clamps out-of-range values to the nearest anchor", () => {
    expect(correlationColor(5)).toBe(correlationColor(1));
    expect(correlationColor(-5)).toBe(correlationColor(-1));
  });
});

describe("findVolatilityRegime", () => {
  it("matches on exact (asset, timeframe)", () => {
    const regimes = [regime({ asset: "GOLD", timeframe: "1week" }), regime({ asset: "GOLD", timeframe: "24h" })];
    expect(findVolatilityRegime(regimes, "GOLD", "24h")).toEqual(regimes[1]);
  });

  it("returns null when the asset is absent from the regimes array", () => {
    expect(findVolatilityRegime([regime({ asset: "GOLD" })], "SILVER", "24h")).toBeNull();
  });

  it("returns null when the asset matches but the timeframe doesn't (GOLD/SILVER can genuinely differ by timeframe)", () => {
    const regimes = [regime({ asset: "GOLD", timeframe: "1week", regime: "EXTREME" })];
    expect(findVolatilityRegime(regimes, "GOLD", "24h")).toBeNull();
  });
});

describe("REGIME_COLOR", () => {
  it("has a distinct color for every regime label the badge can render", () => {
    const values = Object.values(REGIME_COLOR);
    expect(new Set(values).size).toBeGreaterThanOrEqual(4);
    expect(REGIME_COLOR.LOW).toBeDefined();
    expect(REGIME_COLOR.NORMAL).toBeDefined();
    expect(REGIME_COLOR.HIGH).toBeDefined();
    expect(REGIME_COLOR.EXTREME).toBeDefined();
  });
});
