import {
  ASSET_CLASS_ORDER,
  classifyAsset,
  groupRosterByAssetClass,
} from "@/lib/assetClass";
import type { StrategyRosterEntry } from "@/lib/types";

function makeEntry(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "verified",
    ...overrides,
  };
}

describe("classifyAsset", () => {
  it.each(["BTC", "ETH", "BNB", "SOL"])("classifies %s as Crypto", (asset) => {
    expect(classifyAsset(asset)).toEqual({ assetClass: "Crypto", isPair: false });
  });

  it("classifies GOLD as Gold", () => {
    expect(classifyAsset("GOLD")).toEqual({ assetClass: "Gold", isPair: false });
  });

  it("classifies SILVER as Silver", () => {
    expect(classifyAsset("SILVER")).toEqual({ assetClass: "Silver", isPair: false });
  });

  it.each(["EUR/USD", "GBP/USD", "USD/JPY"])("classifies %s as Forex", (asset) => {
    expect(classifyAsset(asset)).toEqual({ assetClass: "Forex", isPair: false });
  });

  it.each(["AAPL", "MSFT", "NVDA"])("defaults %s to Stocks", (asset) => {
    expect(classifyAsset(asset)).toEqual({ assetClass: "Stocks", isPair: false });
  });

  it("classifies GOLD-SILVER as a Gold pair (dominant leg)", () => {
    expect(classifyAsset("GOLD-SILVER")).toEqual({ assetClass: "Gold", isPair: true });
  });

  it("classifies BTC-ETH as a Crypto pair (dominant leg)", () => {
    expect(classifyAsset("BTC-ETH")).toEqual({ assetClass: "Crypto", isPair: true });
  });
});

describe("groupRosterByAssetClass", () => {
  it("returns one group per asset class, in a fixed order, even when empty", () => {
    const groups = groupRosterByAssetClass([]);
    expect(groups.map((g) => g.assetClass)).toEqual(ASSET_CLASS_ORDER);
    groups.forEach((g) => {
      expect(g.primary).toEqual([]);
      expect(g.pairs).toEqual([]);
    });
  });

  it("buckets single-asset entries into primary and pair entries into pairs", () => {
    const roster = [
      makeEntry({ asset: "BTC" }),
      makeEntry({ asset: "GOLD-SILVER" }),
      makeEntry({ asset: "SILVER" }),
    ];
    const groups = groupRosterByAssetClass(roster);

    const crypto = groups.find((g) => g.assetClass === "Crypto")!;
    expect(crypto.primary).toHaveLength(1);
    expect(crypto.pairs).toHaveLength(0);

    const gold = groups.find((g) => g.assetClass === "Gold")!;
    expect(gold.primary).toHaveLength(0);
    expect(gold.pairs).toHaveLength(1);

    const silver = groups.find((g) => g.assetClass === "Silver")!;
    expect(silver.primary).toHaveLength(1);
  });
});
