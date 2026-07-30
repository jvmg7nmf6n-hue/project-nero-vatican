import { render, screen } from "@testing-library/react";
import ResearchAgentPanel from "@/components/ResearchAgentPanel";
import type { AgentHypothesis, AgentPerformanceExport, AgentTestResult } from "@/lib/types";

function hypothesis(overrides: Partial<AgentHypothesis> = {}): AgentHypothesis {
  return {
    scan_finding: "BTC/1h zscore_current=3.10 (|z|>2.0)",
    scan_finding_type: "extreme_zscore",
    hypothesis_name: "ZSCORE_REVERSION_BTC_1H",
    mechanism: "Mean reversion after an extreme dislocation.",
    entry_rule: "zscore20 < -2",
    structured_entry_rule: { conditions: [{ field: "zscore20", op: "lt", value: -2 }] },
    exit_rule: "zscore20 crosses back above 0",
    stop_rule: "2x ATR",
    structured_exit_plan: { stop_atr_multiple: 1.5, target_r_multiple: 2, max_holding_hours: 24 },
    asset: "BTC",
    timeframe: "1h",
    differs_from_graveyard: "Uses a frequent 1h trigger, not the rare daily one already tested.",
    expected_frequency_claim: 80,
    generated_at: "2026-07-29T00:00:00+00:00",
    cost_usd: 0.012,
    source: "claude",
    ...overrides,
  };
}

function testResult(overrides: Partial<AgentTestResult> = {}): AgentTestResult {
  return {
    hypothesis_name: "ZSCORE_REVERSION_BTC_1H",
    asset: "BTC",
    timeframe: "1h",
    verdict: "PROMISING-WATCHLIST",
    review_status: "pending_human_approval",
    frequency_classification: "FAST",
    measured_trades_per_year: 182.5,
    expected_time_to_30_trades_months: 2.0,
    reason: "train: N=40 ExpR=0.219; test: N=18 ExpR=0.120 -> PROMISING-WATCHLIST",
    train: { trades: 40, expectancy_r: 0.219, bootstrap_ci: null, random_baseline: null },
    test: { trades: 18, expectancy_r: 0.12, bootstrap_ci: null, random_baseline: null },
    tested_at: "2026-07-29T01:00:00+00:00",
    ...overrides,
  };
}

function performance(overrides: Partial<AgentPerformanceExport> = {}): AgentPerformanceExport {
  return {
    schema_version: 1,
    last_updated: "2026-07-29T01:00:00+00:00",
    cumulative: {
      hypotheses_generated: 10,
      duplicates_skipped: 3,
      too_slow_rejected: 4,
      unmeasurable_rejected: 1,
      tested: 5,
      survived: 1,
      promising_watchlist: 2,
      died: 2,
      untestable: 0,
      no_candles_available: 0,
      llm_calls_made: 10,
      total_llm_cost_usd: 0.15,
      survival_rate: 0.6,
    },
    runs: [],
    ...overrides,
  };
}

describe("ResearchAgentPanel", () => {
  it("shows an empty state when nothing has ever run", () => {
    render(<ResearchAgentPanel hypotheses={[]} testResults={[]} performance={null} />);
    expect(screen.getByTestId("agent-performance-empty")).toBeInTheDocument();
    expect(screen.getByTestId("agent-hypotheses-empty")).toBeInTheDocument();
    expect(screen.getByTestId("agent-too-slow-empty")).toBeInTheDocument();
  });

  it("renders cumulative performance stats including a null-safe survival rate", () => {
    render(<ResearchAgentPanel hypotheses={[]} testResults={[]} performance={performance()} />);
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("$0.15")).toBeInTheDocument();
  });

  it("renders 'n/a' survival rate when cumulative tested count is zero", () => {
    render(
      <ResearchAgentPanel
        hypotheses={[]}
        testResults={[]}
        performance={performance({ cumulative: { ...performance().cumulative, tested: 0, survival_rate: null } })}
      />
    );
    expect(screen.getByText("n/a")).toBeInTheDocument();
  });

  it("renders a hypothesis card joined with its test result by hypothesis_name", () => {
    render(<ResearchAgentPanel hypotheses={[hypothesis()]} testResults={[testResult()]} performance={null} />);

    const card = screen.getByTestId("agent-hypothesis-card");
    expect(card).toHaveAttribute("data-verdict", "PROMISING-WATCHLIST");
    expect(screen.getByText("ZSCORE_REVERSION_BTC_1H")).toBeInTheDocument();
    expect(screen.getByText(/Frequency: FAST \(182.5\/yr\)/)).toBeInTheDocument();
    expect(screen.getByText(/Verdict: Promising — Watchlist/)).toBeInTheDocument();
    expect(screen.getByText("pending_human_approval")).toBeInTheDocument();
  });

  it("shows 'not yet tested' when a hypothesis has no matching test result", () => {
    render(<ResearchAgentPanel hypotheses={[hypothesis()]} testResults={[]} performance={null} />);
    expect(screen.getByTestId("agent-hypothesis-not-tested")).toBeInTheDocument();
  });

  it("lists TOO_SLOW rejections as a graveyard extension, separate from tested hypotheses", () => {
    const rejected = testResult({
      hypothesis_name: "RARE_EVENT_HYPOTHESIS",
      verdict: "SKIPPED",
      frequency_classification: "TOO_SLOW",
      review_status: "rejected_too_slow",
      measured_trades_per_year: 1.8,
      reason: "Measured 1 trigger(s) over 199 eligible days (1.83 trades/year) -> ~196.7 months to 30 resolved trades -> TOO_SLOW.",
    });
    render(<ResearchAgentPanel hypotheses={[]} testResults={[rejected]} performance={null} />);

    const row = screen.getByTestId("agent-too-slow-row");
    expect(row).toHaveTextContent("RARE_EVENT_HYPOTHESIS");
    expect(row).toHaveTextContent("196.7 months");
  });

  it("does not render any approval button anywhere -- read-only per spec", () => {
    render(
      <ResearchAgentPanel
        hypotheses={[hypothesis()]}
        testResults={[testResult({ verdict: "SURVIVED", review_status: "pending_human_approval" })]}
        performance={performance()}
      />
    );
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
