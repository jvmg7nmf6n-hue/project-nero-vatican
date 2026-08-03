import { render, screen } from "@testing-library/react";
import StrategyCard from "@/components/StrategyCard";
import type { BacktestEvaluation, LedgerRow, StrategyRosterEntry, StrategyStats } from "@/lib/types";

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
    source_report: "docs/statistical_harness_upgrade.md",
    source_report_written_at: "2026-07-18",
    backtest_evaluation: makeBacktestEvaluation(),
    ...overrides,
  };
}

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-26T00:00:00Z",
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    asset: "GOLD",
    signal_type: "ENTRY",
    entry_price: 100,
    exit_price: null,
    reasoning: "",
    candle_timestamp: "1000",
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

describe("StrategyCard: research status and current signal are two separate elements", () => {
  it("renders a research-status block and a current-signal block independently", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);

    expect(screen.getByTestId("research-status")).toBeInTheDocument();
    expect(screen.getByTestId("current-signal")).toBeInTheDocument();
  });

  it("shows the tier badge inside research-status, not inside current-signal", () => {
    render(<StrategyCard entry={makeEntry({ verification_status: "triple-verified" })} recentRows={[]} stats={[]} />);

    const researchStatus = screen.getByTestId("research-status");
    const currentSignal = screen.getByTestId("current-signal");

    expect(researchStatus).toHaveTextContent("Verified");
    expect(researchStatus).toHaveTextContent("Research status");
    expect(currentSignal).not.toHaveTextContent("Verified");
    expect(currentSignal).not.toHaveTextContent("Research status");
  });

  it("shows the 'Current signal:' prefix inside current-signal, not inside research-status", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);

    const researchStatus = screen.getByTestId("research-status");
    const currentSignal = screen.getByTestId("current-signal");

    expect(currentSignal).toHaveTextContent("Current signal:");
    expect(researchStatus).not.toHaveTextContent("Current signal:");
  });

  it("keeps tier styling and signal styling on separate elements (no blending)", () => {
    render(
      <StrategyCard
        entry={makeEntry({ verification_status: "watchlist — forward-testing, not verified" })}
        recentRows={[makeRow({ signal_type: "EXIT" })]}
        stats={[]}
      />
    );

    const card = screen.getByTestId("strategy-card");
    const currentSignal = screen.getByTestId("current-signal");

    // The card's own border reflects the tier (watchlist = gold dashed)...
    expect(card.className).toContain("border-gold/60");
    expect(card.className).toContain("border-dashed");
    // ...while the signal's color (EXIT = amber) lives only on the signal row,
    // never merged into the card-level tier border classes.
    expect(card.className).not.toContain("amber");
    expect(currentSignal.innerHTML).toContain("amber");
  });
});

describe("StrategyCard current-signal color per state", () => {
  // Assert on the state-label span's own className (not innerHTML substring
  // matching) -- the "Current signal:" prefix always carries text-muted, so a
  // loose innerHTML.includes("text-muted") check would pass even for a broken
  // no_signal_yet state.
  it("colors ENTRY teal", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "ENTRY" })]} stats={[]} />);
    expect(screen.getByText("ENTRY").className).toContain("text-teal");
  });

  it("colors EXIT amber", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "EXIT" })]} stats={[]} />);
    expect(screen.getByText("EXIT").className).toContain("text-amber-400");
  });

  it("colors WATCH as neutral-gray WATCHING", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "WATCH" })]} stats={[]} />);
    expect(screen.getByText("WATCHING").className).toContain("text-gray-300");
  });

  it("colors NO_TRADE as neutral-gray WATCHING too", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "NO_TRADE" })]} stats={[]} />);
    expect(screen.getByText("WATCHING").className).toContain("text-gray-300");
  });

  it("colors an unlogged strategy muted NO SIGNAL YET", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);
    const label = screen.getByText("NO SIGNAL YET");
    expect(label.className).toContain("text-muted");
    expect(label.className).not.toContain("text-teal");
    expect(label.className).not.toContain("text-amber-400");
    expect(label.className).not.toContain("text-gray-300");
  });

  it("gives each of the 4 signal states a visually distinct label color class", () => {
    const cases: Array<[LedgerRow[], string, string]> = [
      [[makeRow({ signal_type: "ENTRY" })], "ENTRY", "text-teal"],
      [[makeRow({ signal_type: "EXIT" })], "EXIT", "text-amber-400"],
      [[makeRow({ signal_type: "WATCH" })], "WATCHING", "text-gray-300"],
      [[], "NO SIGNAL YET", "text-muted"],
    ];
    const seenClasses = new Set<string>();
    cases.forEach(([rows, expectedLabel, expectedClass]) => {
      const { unmount } = render(<StrategyCard entry={makeEntry()} recentRows={rows} stats={[]} />);
      const label = screen.getByText(expectedLabel);
      expect(label.className).toContain(expectedClass);
      seenClasses.add(expectedClass);
      unmount();
    });
    expect(seenClasses.size).toBe(4);
  });
});

describe("StrategyCard backtest evaluation indicator", () => {
  it("shows no evaluation indicator when nothing has been structurally evaluated", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);
    expect(screen.queryByTestId("card-backtest-verdict")).not.toBeInTheDocument();
    expect(screen.queryByTestId("card-backtest-untestable")).not.toBeInTheDocument();
  });

  it("shows the DIED/INSUFFICIENT_SAMPLE verdict on the card, not just the tier badge", () => {
    render(
      <StrategyCard
        entry={makeEntry({
          backtest_evaluation: makeBacktestEvaluation({ verdict_is: "DIED", verdict_oos: "INSUFFICIENT_SAMPLE" }),
        })}
        recentRows={[]}
        stats={[]}
      />
    );
    const verdict = screen.getByTestId("card-backtest-verdict");
    expect(verdict).toHaveTextContent("DIED");
    expect(verdict).toHaveTextContent("INSUFFICIENT_SAMPLE");
  });

  it("shows an untestable-by-standard-harness badge, never blank, for a two-asset strategy", () => {
    render(
      <StrategyCard
        entry={makeEntry({
          backtest_evaluation: makeBacktestEvaluation({
            untestable_reason: "Not compatible with the single-asset rule_dsl/auto_tester harness.",
            is_trades: 61,
          }),
        })}
        recentRows={[]}
        stats={[]}
      />
    );
    expect(screen.getByTestId("card-backtest-untestable")).toHaveTextContent("Untestable by standard harness");
  });
});

describe("StrategyCard badge provenance", () => {
  it("shows the backtest-evidence provenance line under the tier badge, written date included", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);
    expect(screen.getByTestId("provenance-line")).toHaveTextContent(
      "Verified — backtest evidence, written 2026-07-18, not re-evaluated since."
    );
  });

  it("shows the unbacktestable provenance line verbatim for a permanently-unbacktestable strategy", () => {
    render(
      <StrategyCard
        entry={makeEntry({
          verification_status: "experimental — snapshot-based, forward-testing only, no backtest exists",
          source_report: null,
          source_report_written_at: null,
          backtest_evaluation: makeBacktestEvaluation({ permanently_unbacktestable: true }),
        })}
        recentRows={[]}
        stats={[]}
      />
    );
    expect(screen.getByTestId("provenance-line")).toHaveTextContent(
      "Unbacktestable — live evidence only (no historical data source)."
    );
  });

  it("shows the live-resolved-trades provenance line when there is no backtest evidence at all", () => {
    render(
      <StrategyCard
        entry={makeEntry({ source_report: null, source_report_written_at: null })}
        recentRows={[]}
        stats={[makeStats({ resolved_trades: 14, win_rate: 0.5 })]}
      />
    );
    expect(screen.getByTestId("provenance-line")).toHaveTextContent(
      "Verified — 14 live resolved trades, updated automatically."
    );
  });
});

describe("StrategyCard trade-context detail (ENTRY/EXIT)", () => {
  it("shows entry price and timestamp for an ENTRY signal", () => {
    render(
      <StrategyCard
        entry={makeEntry()}
        recentRows={[makeRow({ signal_type: "ENTRY", entry_price: 2450.5 })]}
        stats={[]}
      />
    );
    const detail = screen.getByTestId("signal-detail");
    expect(detail).toHaveTextContent("Entered");
    expect(detail).toHaveTextContent("2450.5");
  });

  it("shows exit price and resolved P&L for an EXIT signal", () => {
    render(
      <StrategyCard
        entry={makeEntry()}
        recentRows={[
          makeRow({ signal_type: "EXIT", exit_price: 2500, timestamp: "2026-07-27T00:00:00Z" }),
          makeRow({ signal_type: "ENTRY", entry_price: 2400, timestamp: "2026-07-20T00:00:00Z" }),
        ]}
        stats={[makeStats({ resolved_trades: 4, avg_return_pct: 3.25 })]}
      />
    );
    const detail = screen.getByTestId("signal-detail");
    expect(detail).toHaveTextContent("Exited");
    expect(detail).toHaveTextContent("2500");
    expect(detail).toHaveTextContent("entered @ 2400");
    expect(detail).toHaveTextContent("P&L: 3.25%");
  });

  it("shows 'P&L pending' for an EXIT signal with zero resolved trades in stats.json", () => {
    render(
      <StrategyCard
        entry={makeEntry()}
        recentRows={[makeRow({ signal_type: "EXIT", exit_price: 2500 })]}
        stats={[makeStats({ resolved_trades: 0 })]}
      />
    );
    expect(screen.getByTestId("signal-detail")).toHaveTextContent("P&L pending");
  });

  it("never shows a bare EXIT label without context: falls back to NO SIGNAL YET when the version doesn't match", () => {
    render(
      <StrategyCard
        entry={makeEntry()}
        recentRows={[
          makeRow({ signal_type: "EXIT", exit_price: 2500, strategy_version: "breakout-momentum-v9.9.9-different" }),
        ]}
        stats={[]}
      />
    );
    expect(screen.getByText("NO SIGNAL YET")).toBeInTheDocument();
    expect(screen.queryByText("EXIT")).not.toBeInTheDocument();
    expect(screen.queryByTestId("signal-detail")).not.toBeInTheDocument();
  });

  it("shows no detail block for WATCHING or NO SIGNAL YET states", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "WATCH" })]} stats={[]} />);
    expect(screen.queryByTestId("signal-detail")).not.toBeInTheDocument();
  });
});
