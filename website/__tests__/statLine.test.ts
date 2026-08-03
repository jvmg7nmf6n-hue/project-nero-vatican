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

  // Phase 1 Fix A (docs/investigations/phase_a_pead_ledger_anomaly.md): the
  // MSFT/TSLA/META PEAD shape -- an ENTRY fired but its source can't be
  // confirmed, so there's no resolved trade AND no unverified round trip
  // (that field only counts RESOLVED quarantined round trips). Without this
  // fix these silently fell back to AWAITING_FIRST_SIGNAL, which is actively
  // wrong -- a real signal did fire.
  it("shows a pending-verification state for an unverified open entry, not awaiting-first-signal", () => {
    const stats = [makeStats({ resolved_trades: 0, unverified_trades: 0, unverified_open_entries: 1 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("1 entry pending source verification");
  });

  it("treats a missing unverified_open_entries field (older cached export) as 0", () => {
    const stats = [makeStats({ resolved_trades: 0, unverified_trades: 0 })];
    delete (stats[0] as { unverified_open_entries?: number }).unverified_open_entries;
    expect(deriveStatLine(makeEntry(), stats)).toBe(AWAITING_FIRST_SIGNAL);
  });

  it("prefers the unverified-trades (resolved-but-quarantined) message over the open-entry one when both are present", () => {
    const stats = [makeStats({ resolved_trades: 0, unverified_trades: 1, unverified_open_entries: 1 })];
    expect(deriveStatLine(makeEntry(), stats)).toBe("1 trade pending source verification");
  });

  // "Every signal. Every loss." -- win rate alone hides expectancy (e.g. ORDERFLOW
  // ETH: 61.5% wins at only +0.012R). R must show alongside win rate everywhere.
  describe("R multiple alongside win rate", () => {
    it("appends a positive R with an explicit + sign", () => {
      const stats = [makeStats({ resolved_trades: 12, win_rate: 0.5833, expectancy_r: 0.091 })];
      expect(deriveStatLine(makeEntry(), stats)).toBe("12 resolved trades · 58.3% win rate · +0.091R");
    });

    it("appends a negative R with its own minus sign, no double negative", () => {
      const stats = [makeStats({ resolved_trades: 12, win_rate: 0.4167, expectancy_r: -0.228 })];
      expect(deriveStatLine(makeEntry(), stats)).toBe("12 resolved trades · 41.7% win rate · -0.228R");
    });

    it("shows R even when win_rate is null", () => {
      const stats = [makeStats({ resolved_trades: 5, win_rate: null, expectancy_r: 0.012 })];
      expect(deriveStatLine(makeEntry(), stats)).toBe("5 resolved trades · +0.012R");
    });

    it("omits the R clause entirely when expectancy_r is null", () => {
      const stats = [makeStats({ resolved_trades: 5, win_rate: 0.6, expectancy_r: null })];
      expect(deriveStatLine(makeEntry(), stats)).toBe("5 resolved trades · 60% win rate");
    });

    it("shows a zero expectancy explicitly as +0.000R, never omitted", () => {
      const stats = [makeStats({ resolved_trades: 8, win_rate: 0.5, expectancy_r: 0 })];
      expect(deriveStatLine(makeEntry(), stats)).toBe("8 resolved trades · 50% win rate · +0.000R");
    });
  });
});
