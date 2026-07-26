import { buildStrategyId, findEntryByStrategyId } from "@/lib/strategyId";
import type { StrategyRosterEntry } from "@/lib/types";

function makeEntry(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "triple-verified",
    source_report: "docs/statistical_harness_upgrade.md",
    ...overrides,
  };
}

describe("buildStrategyId", () => {
  it("is a lowercase, hyphenated slug embedding name, asset, and version", () => {
    const id = buildStrategyId(makeEntry());
    expect(id).toBe("breakout-momentum--gold--breakout-momentum-v1-2-0-gold-calibrated-1week");
  });

  it("handles slash-containing forex assets safely", () => {
    const id = buildStrategyId(
      makeEntry({ name: "DONCHIAN_TREND", asset: "EUR/USD", version: "donchian-trend-v2.0.0-bracket-eurusd-n20-1week" })
    );
    expect(id).not.toContain("/");
  });

  it("gives two different versions of the same strategy+asset two different ids", () => {
    // The RANGE_MEAN_REVERSION long-only / confirmation precedent: same name, same
    // asset (BTC), different version -- must not collide.
    const longOnly = buildStrategyId(
      makeEntry({ name: "RANGE_MEAN_REVERSION", asset: "BTC", version: "range-mean-reversion-v1.1.0-long-only" })
    );
    const confirmation = buildStrategyId(
      makeEntry({ name: "RANGE_MEAN_REVERSION", asset: "BTC", version: "range-mean-reversion-v1.3.0-confirmation" })
    );
    expect(longOnly).not.toBe(confirmation);
  });
});

describe("findEntryByStrategyId", () => {
  const roster: StrategyRosterEntry[] = [
    makeEntry({ name: "BREAKOUT_MOMENTUM", asset: "GOLD" }),
    makeEntry({ name: "TREND_PULLBACK", asset: "BNB", version: "trend-pullback-v1.0.0" }),
  ];

  it("finds the roster entry whose slug matches the given id", () => {
    const id = buildStrategyId(roster[1]);
    expect(findEntryByStrategyId(roster, id)).toBe(roster[1]);
  });

  it("returns undefined for an id that matches nothing in the roster", () => {
    expect(findEntryByStrategyId(roster, "not-a-real-strategy--xyz--v9")).toBeUndefined();
  });

  it("returns undefined for an empty roster", () => {
    expect(findEntryByStrategyId([], "anything")).toBeUndefined();
  });
});
