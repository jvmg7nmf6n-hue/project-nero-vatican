import { deriveProvenanceLine } from "@/lib/provenance";
import type { BacktestEvaluation, StrategyRosterEntry, StrategyStats } from "@/lib/types";

function makeBacktestEvaluation(overrides: Partial<BacktestEvaluation> = {}): BacktestEvaluation {
  return {
    verdict_is: null,
    verdict_oos: null,
    is_trades: null,
    oos_trades: null,
    is_expectancy_r: null,
    oos_expectancy_r: null,
    evaluated_at: null,
    data_source: null,
    method: null,
    untestable_reason: null,
    note: "Not yet evaluated with this structured format.",
    permanently_unbacktestable: false,
    ...overrides,
  };
}

function makeEntry(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "triple-verified",
    source_report: null,
    source_report_written_at: null,
    backtest_evaluation: makeBacktestEvaluation(),
    ...overrides,
  };
}

function makeStats(overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
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

describe("deriveProvenanceLine", () => {
  it("states the permanently-unbacktestable case in exactly those words, regardless of tier", () => {
    const entry = makeEntry({
      verification_status: "experimental — snapshot-based, forward-testing only, no backtest exists",
      backtest_evaluation: makeBacktestEvaluation({ permanently_unbacktestable: true }),
    });
    expect(deriveProvenanceLine(entry, [])).toBe(
      "Unbacktestable — live evidence only (no historical data source)."
    );
  });

  it("cites the structured evaluation's own evaluated_at date when a real backtest_evaluation entry exists", () => {
    const entry = makeEntry({
      backtest_evaluation: makeBacktestEvaluation({ verdict_is: "DIED", verdict_oos: "INSUFFICIENT_SAMPLE", evaluated_at: "2026-08-02" }),
    });
    expect(deriveProvenanceLine(entry, [])).toBe(
      "Verified — backtest evidence, written 2026-08-02, not re-evaluated since."
    );
  });

  it("falls back to the narrative source report's written-at date when no structured entry exists", () => {
    const entry = makeEntry({
      source_report: "docs/statistical_harness_upgrade.md",
      source_report_written_at: "2026-07-18",
    });
    expect(deriveProvenanceLine(entry, [])).toBe(
      "Verified — backtest evidence, written 2026-07-18, not re-evaluated since."
    );
  });

  it("prefers the structured evaluated_at date over the source-report date when both exist", () => {
    const entry = makeEntry({
      source_report: "docs/statistical_harness_upgrade.md",
      source_report_written_at: "2026-07-18",
      backtest_evaluation: makeBacktestEvaluation({ is_trades: 61, evaluated_at: "2026-07-17" }),
    });
    expect(deriveProvenanceLine(entry, [])).toBe(
      "Verified — backtest evidence, written 2026-07-17, not re-evaluated since."
    );
  });

  it("uses the hand-authored two-leg conservative framing for COINTEGRATION_PAIRS, overriding the generic priority logic entirely", () => {
    const entry = makeEntry({
      name: "COINTEGRATION_PAIRS",
      version: "cointegration-pairs-v1.0.0",
      asset: "BTC-ETH",
      verification_status: "verified — weakest, live-proving",
      backtest_evaluation: makeBacktestEvaluation({ is_trades: 61, oos_trades: 22, evaluated_at: "2026-07-17" }),
    });
    const line = deriveProvenanceLine(entry, []);
    expect(line).toContain("Verified — two-leg funding-costed backtest, edge survives but basis/liquidation risk still unmodeled.");
    expect(line).toContain("OOS expectancy (+0.0025R) is thin enough that a different live data pull could flip its sign");
    expect(line).toContain("grid-shift audits fetch live vendor data that isn't pinned");
    expect(line).toContain(
      "Its R is net_pnl/notional, not a stop-distance risk multiple, so it is not comparable to other strategies' R on this page."
    );
    // Never the generic "written <date>" phrasing -- this is a hand-authored override, not derived from evaluated_at.
    expect(line).not.toContain("not re-evaluated since");
  });

  it("uses the same COINTEGRATION_PAIRS framing regardless of backtest_evaluation/stats content -- it's a fixed override, not derived", () => {
    const entry = makeEntry({
      name: "COINTEGRATION_PAIRS",
      version: "cointegration-pairs-v1.0.0",
      asset: "BTC-ETH",
      verification_status: "verified — weakest, live-proving",
      backtest_evaluation: makeBacktestEvaluation(),
      source_report: null,
      source_report_written_at: null,
    });
    expect(deriveProvenanceLine(entry, [])).toContain("two-leg funding-costed backtest");
  });

  it("does not append the COINTEGRATION_PAIRS caveat to any other strategy", () => {
    const entry = makeEntry({
      backtest_evaluation: makeBacktestEvaluation({ evaluated_at: "2026-08-02", verdict_is: "SURVIVED" }),
    });
    expect(deriveProvenanceLine(entry, [])).not.toContain("net_pnl/notional");
  });

  it("reports live resolved trades, updated automatically, when there is no backtest evidence at all", () => {
    const entry = makeEntry({ source_report: null, source_report_written_at: null });
    const stats = [makeStats({ resolved_trades: 14, win_rate: 0.5 })];
    expect(deriveProvenanceLine(entry, stats)).toBe("Verified — 14 live resolved trades, updated automatically.");
  });

  it("uses singular 'trade' for exactly 1 live resolved trade", () => {
    const entry = makeEntry({ source_report: null, source_report_written_at: null });
    const stats = [makeStats({ resolved_trades: 1, win_rate: 1 })];
    expect(deriveProvenanceLine(entry, stats)).toBe("Verified — 1 live resolved trade, updated automatically.");
  });

  it("never matches a stats row for a different strategy_version (RMR two-version-same-asset discipline)", () => {
    const entry = makeEntry({ source_report: null, source_report_written_at: null });
    const stats = [makeStats({ strategy_version: "breakout-momentum-v9.9.9-different", resolved_trades: 40 })];
    expect(deriveProvenanceLine(entry, stats)).toBe(
      "Verified — this status is a hand-written note only; no structured backtest or live-trade evidence is recorded yet."
    );
  });

  it("states plainly when a tier rests on nothing but the hand-written verification_status string", () => {
    const entry = makeEntry({
      verification_status: "watchlist — forward-testing, not verified",
      source_report: null,
      source_report_written_at: null,
    });
    expect(deriveProvenanceLine(entry, [])).toBe(
      "Watchlist — this status is a hand-written note only; no structured backtest or live-trade evidence is recorded yet."
    );
  });

  it("uses the actual tier label, not a hardcoded 'Verified', for a non-verified strategy with backtest evidence", () => {
    const entry = makeEntry({
      verification_status: "watchlist — DIED in-sample, promising out-of-sample",
      backtest_evaluation: makeBacktestEvaluation({ verdict_is: "DIED", evaluated_at: "2026-08-02" }),
    });
    expect(deriveProvenanceLine(entry, [])).toBe(
      "Watchlist — backtest evidence, written 2026-08-02, not re-evaluated since."
    );
  });

  it("treats a missing permanently_unbacktestable field (older cached export) as false", () => {
    const entry = makeEntry();
    delete (entry.backtest_evaluation as { permanently_unbacktestable?: boolean }).permanently_unbacktestable;
    expect(deriveProvenanceLine(entry, [])).not.toContain("Unbacktestable");
  });
});
