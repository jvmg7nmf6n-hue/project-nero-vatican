import { AWAITING_FIRST_SIGNAL, deriveStatLine } from "@/lib/statLine";
import type { StrategyStats } from "@/lib/types";

function makeEntry() {
  return { name: "BREAKOUT_MOMENTUM", version: "breakout-momentum-v1.0.0", asset: "GOLD" };
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

describe("deriveStatLine", () => {
  it("returns the awaiting-first-signal state when there is no stats match", () => {
    expect(deriveStatLine(makeEntry(), [])).toBe(AWAITING_FIRST_SIGNAL);
  });

  it("returns the awaiting-first-signal state when resolved_trades is 0", () => {
    const stats = [makeStats({ resolved_trades: 0 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe(AWAITING_FIRST_SIGNAL);
  });

  it("never matches a different strategy_version (RMR two-version-same-asset discipline)", () => {
    const stats = [
      makeStats({ strategy_version: "breakout-momentum-v2.0.0", resolved_trades: 40, win_rate: 0.6 }),
    ];
    expect(deriveStatLine(makeEntry(), stats)).toBe(AWAITING_FIRST_SIGNAL);
  });

  it("renders resolved trades and win rate when populated", () => {
    const stats = [makeStats({ resolved_trades: 12, win_rate: 0.5833 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("12 resolved trades · 58.3% win rate");
  });

  it("uses singular 'trade' for exactly 1 resolved trade", () => {
    const stats = [makeStats({ resolved_trades: 1, win_rate: 1 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("1 resolved trade · 100% win rate");
  });

  it("omits the win-rate clause when win_rate is null", () => {
    const stats = [makeStats({ resolved_trades: 5, win_rate: null })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("5 resolved trades");
  });

  it("shows a pending-verification state when trades happened but none are confirmed clean", () => {
    const stats = [makeStats({ resolved_trades: 0, unverified_trades: 3 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("3 trades pending source verification");
  });

  it("uses singular 'trade' for exactly 1 unverified trade", () => {
    const stats = [makeStats({ resolved_trades: 0, unverified_trades: 1 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("1 trade pending source verification");
  });

  it("still returns awaiting-first-signal when both resolved and unverified are 0", () => {
    const stats = [makeStats({ resolved_trades: 0, unverified_trades: 0 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe(AWAITING_FIRST_SIGNAL);
  });

  it("treats a missing unverified_trades field (older cached export) as 0", () => {
    const stats = [makeStats({ resolved_trades: 0 })];
    delete (stats[0] as { unverified_trades?: number }).unverified_trades;
    expect(deriveStatLine(makeEntry(), stats)).toBe(AWAITING_FIRST_SIGNAL);
  });

  it("prefers the resolved-trades line once at least one trade is confirmed clean, even with unverified ones too", () => {
    const stats = [makeStats({ resolved_trades: 2, win_rate: 0.5, unverified_trades: 1 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("2 resolved trades · 50% win rate");
  });
});
