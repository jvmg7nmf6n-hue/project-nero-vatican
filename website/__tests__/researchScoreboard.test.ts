import {
  buildResearchScoreboard,
  filterScoreboardByStatus,
  sortScoreboardByWinRate,
  type ScoreboardRow,
} from "@/lib/researchScoreboard";
import type { FailurePatternEntry, GraveyardEntry, StrategyRosterEntry, StrategyStats } from "@/lib/types";

function roster(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "verified",
    source_report: "docs/some_report.md",
    ...overrides,
  };
}

function stats(overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    resolved_trades: 10,
    win_rate: 0.6,
    expectancy_r: null,
    avg_return_pct: null,
    signal_counts: { ENTRY: 0, EXIT: 0, WATCH: 0, NO_TRADE: 0 },
    open_position: null,
    ...overrides,
  };
}

function graveyardEntry(overrides: Partial<GraveyardEntry> = {}): GraveyardEntry {
  return {
    name: "FVG_REVERSION",
    family: "Fair Value Gap",
    what_was_tested: "x",
    why_it_died: "y",
    source_doc: "docs/fvg_reversion_report.md",
    ...overrides,
  };
}

function failurePattern(overrides: Partial<FailurePatternEntry> = {}): FailurePatternEntry {
  return {
    name: "FVG_REVERSION",
    family: "Fair Value Gap",
    failure_pattern: "edge-over-random-negative",
    fixable: false,
    source_doc: "docs/fvg_reversion_report.md",
    ...overrides,
  };
}

describe("buildResearchScoreboard", () => {
  it("maps a verified live roster entry with a matching stats row", () => {
    const rows = buildResearchScoreboard([roster()], [stats()], [], []);
    expect(rows).toEqual<ScoreboardRow[]>([
      {
        name: "BREAKOUT_MOMENTUM",
        family: "BREAKOUT_MOMENTUM",
        asset: "GOLD",
        timeframe: "1week",
        status: "verified",
        winRate: 0.6,
        sourceDoc: "docs/some_report.md",
      },
    ]);
  });

  it("collapses watchlist and experimental verification statuses to 'watchlist'", () => {
    const rows = buildResearchScoreboard(
      [roster({ verification_status: "promising-watchlist" }), roster({ verification_status: "experimental" })],
      [],
      [],
      []
    );
    expect(rows.every((r) => r.status === "watchlist")).toBe(true);
  });

  it("leaves win_rate null when no stats row matches (never fabricated)", () => {
    const rows = buildResearchScoreboard([roster()], [], [], []);
    expect(rows[0].winRate).toBeNull();
  });

  it("maps a killed graveyard entry to status 'died' with null asset/timeframe", () => {
    const rows = buildResearchScoreboard([], [], [graveyardEntry()], [failurePattern()]);
    expect(rows).toEqual<ScoreboardRow[]>([
      {
        name: "FVG_REVERSION",
        family: "Fair Value Gap",
        asset: null,
        timeframe: null,
        status: "died",
        winRate: null,
        sourceDoc: "docs/fvg_reversion_report.md",
      },
    ]);
  });

  it("maps a killed graveyard entry to status 'blocked' when its family's failure_pattern is data-blocked", () => {
    const rows = buildResearchScoreboard(
      [],
      [],
      [graveyardEntry({ name: "LIQUIDATION_PREDICTOR", family: "Order-Book / Liquidation" })],
      [
        failurePattern({
          name: "LIQUIDATION_PREDICTOR",
          family: "Order-Book / Liquidation",
          failure_pattern: "data-blocked",
        }),
      ]
    );
    expect(rows[0].status).toBe("blocked");
  });

  it("defaults to 'died' when no failure_patterns entry matches the graveyard family", () => {
    const rows = buildResearchScoreboard([], [], [graveyardEntry({ family: "Unmapped Family" })], []);
    expect(rows[0].status).toBe("died");
  });

  it("combines live and killed rows in one list", () => {
    const rows = buildResearchScoreboard([roster()], [stats()], [graveyardEntry()], [failurePattern()]);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.status).sort()).toEqual(["died", "verified"]);
  });
});

describe("filterScoreboardByStatus", () => {
  const rows: ScoreboardRow[] = [
    { name: "A", family: "A", asset: "BTC", timeframe: "1d", status: "verified", winRate: 0.5, sourceDoc: null },
    { name: "B", family: "B", asset: null, timeframe: null, status: "died", winRate: null, sourceDoc: null },
    { name: "C", family: "C", asset: null, timeframe: null, status: "blocked", winRate: null, sourceDoc: null },
  ];

  it("returns all rows for 'All'", () => {
    expect(filterScoreboardByStatus(rows, "All")).toHaveLength(3);
  });

  it("returns only rows matching the given status", () => {
    expect(filterScoreboardByStatus(rows, "died")).toEqual([rows[1]]);
  });

  it("returns an empty array when no row matches", () => {
    expect(filterScoreboardByStatus(rows, "watchlist")).toEqual([]);
  });
});

describe("sortScoreboardByWinRate", () => {
  const rows: ScoreboardRow[] = [
    { name: "Low", family: "x", asset: null, timeframe: null, status: "verified", winRate: 0.2, sourceDoc: null },
    { name: "NoData", family: "x", asset: null, timeframe: null, status: "died", winRate: null, sourceDoc: null },
    { name: "High", family: "x", asset: null, timeframe: null, status: "verified", winRate: 0.8, sourceDoc: null },
  ];

  it("sorts descending with null win_rate rows pushed to the end", () => {
    const sorted = sortScoreboardByWinRate(rows, "desc");
    expect(sorted.map((r) => r.name)).toEqual(["High", "Low", "NoData"]);
  });

  it("sorts ascending with null win_rate rows still pushed to the end", () => {
    const sorted = sortScoreboardByWinRate(rows, "asc");
    expect(sorted.map((r) => r.name)).toEqual(["Low", "High", "NoData"]);
  });
});
