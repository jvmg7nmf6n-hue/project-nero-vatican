import { render, screen } from "@testing-library/react";
import LabPage from "@/app/lab/page";
import * as data from "@/lib/data";
import type {
  AgentHypothesis,
  AgentPerformanceExport,
  AgentRunSummary,
  AgentTestResult,
  FailurePatternEntry,
  GraveyardEntry,
  RepairCandidate,
  StatsExport,
  StrategiesExport,
  StrategyRosterEntry,
  StrategyStats,
} from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchStrategies = jest.mocked(data.fetchStrategies);
const mockFetchStats = jest.mocked(data.fetchStats);
const mockFetchGraveyard = jest.mocked(data.fetchGraveyard);
const mockFetchFailurePatterns = jest.mocked(data.fetchFailurePatterns);
const mockFetchRepairCandidates = jest.mocked(data.fetchRepairCandidates);
const mockFetchAgentHypotheses = jest.mocked(data.fetchAgentHypotheses);
const mockFetchAgentTestResults = jest.mocked(data.fetchAgentTestResults);
const mockFetchAgentPerformance = jest.mocked(data.fetchAgentPerformance);
const mockFetchAgentRunSummaries = jest.mocked(data.fetchAgentRunSummaries);

function roster(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "verified",
    source_report: null,
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

function setupMocks(options: {
  roster?: StrategyRosterEntry[];
  stats?: StrategyStats[];
  graveyard?: GraveyardEntry[] | null;
  failurePatterns?: FailurePatternEntry[] | null;
  repairCandidates?: RepairCandidate[] | null;
  agentHypotheses?: AgentHypothesis[] | null;
  agentTestResults?: AgentTestResult[] | null;
  agentPerformance?: AgentPerformanceExport | null;
  agentRunSummaries?: AgentRunSummary[] | null;
}) {
  const strategiesExport: StrategiesExport = {
    schema_version: 1,
    last_updated: "x",
    strategies: options.roster ?? [],
  };
  const statsExport: StatsExport = { schema_version: 1, last_updated: "x", strategies: options.stats ?? [] };
  mockFetchStrategies.mockResolvedValue(strategiesExport);
  mockFetchStats.mockResolvedValue(statsExport);
  // "options.x ?? []" would silently turn an explicit `null` (testing the
  // "fetch failed" path) back into `[]` -- only fall back when the key was
  // omitted entirely.
  mockFetchGraveyard.mockResolvedValue("graveyard" in options ? (options.graveyard as GraveyardEntry[] | null) : []);
  mockFetchFailurePatterns.mockResolvedValue(
    "failurePatterns" in options ? (options.failurePatterns as FailurePatternEntry[] | null) : []
  );
  mockFetchRepairCandidates.mockResolvedValue(
    "repairCandidates" in options ? (options.repairCandidates as RepairCandidate[] | null) : []
  );
  mockFetchAgentHypotheses.mockResolvedValue(
    "agentHypotheses" in options ? (options.agentHypotheses as AgentHypothesis[] | null) : []
  );
  mockFetchAgentTestResults.mockResolvedValue(
    "agentTestResults" in options ? (options.agentTestResults as AgentTestResult[] | null) : []
  );
  mockFetchAgentPerformance.mockResolvedValue("agentPerformance" in options ? (options.agentPerformance ?? null) : null);
  mockFetchAgentRunSummaries.mockResolvedValue(
    "agentRunSummaries" in options ? (options.agentRunSummaries as AgentRunSummary[] | null) : []
  );
}

describe("LabPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders the scoreboard combining live and killed strategies", async () => {
    setupMocks({ roster: [roster()], graveyard: [graveyardEntry()] });
    render(await LabPage());

    expect(screen.getByText("Research Lab")).toBeInTheDocument();
    const rows = screen.getAllByTestId("scoreboard-row");
    expect(rows).toHaveLength(2);
    expect(rows.some((r) => r.getAttribute("data-status") === "verified")).toBe(true);
    expect(rows.some((r) => r.getAttribute("data-status") === "died")).toBe(true);
  });

  it("renders the repair workbench with the RMR lineage even with no live data", async () => {
    setupMocks({});
    render(await LabPage());

    expect(screen.getByTestId("rmr-lineage")).toBeInTheDocument();
    expect(screen.getByTestId("repair-candidates-empty")).toBeInTheDocument();
  });

  it("renders repair candidate cards when repair_candidates.json has entries", async () => {
    setupMocks({
      repairCandidates: [
        {
          parent_strategy: "LEADLAG_FOLLOW",
          failure_pattern: "grid-shift-artifact",
          diagnosis: "Fixed candle-count lag doesn't survive a grid shift.",
          proposed_fix: "Use a wall-clock time lag instead.",
          hypothesis_name: "LEADLAG_TIME_INVARIANT",
          status: "candidate",
        },
      ],
    });
    render(await LabPage());

    expect(screen.getByText("LEADLAG_TIME_INVARIANT")).toBeInTheDocument();
  });

  it("degrades gracefully to empty sections when every fetch returns null", async () => {
    setupMocks({
      graveyard: null, failurePatterns: null, repairCandidates: null,
      agentHypotheses: null, agentTestResults: null, agentPerformance: null,
    });
    mockFetchStrategies.mockResolvedValue(null);
    mockFetchStats.mockResolvedValue(null);
    render(await LabPage());

    expect(screen.getByText("No research history recorded yet.")).toBeInTheDocument();
    expect(screen.getByTestId("repair-candidates-empty")).toBeInTheDocument();
    expect(screen.getByTestId("agent-hypotheses-empty")).toBeInTheDocument();
    expect(screen.getByTestId("agent-performance-empty")).toBeInTheDocument();
  });

  it("renders the Research Agent section with a hypothesis joined to its test result", async () => {
    setupMocks({
      agentHypotheses: [
        {
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
          differs_from_graveyard: "Frequent 1h trigger, not the rare daily one already tested.",
          expected_frequency_claim: 80,
          generated_at: "2026-07-29T00:00:00+00:00",
          cost_usd: 0.012,
          source: "claude",
        },
      ],
      agentTestResults: [
        {
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
        },
      ],
    });
    render(await LabPage());

    expect(screen.getByText("Research Agent")).toBeInTheDocument();
    expect(screen.getByText("ZSCORE_REVERSION_BTC_1H")).toBeInTheDocument();
    expect(screen.getByText(/Verdict: Promising — Watchlist/)).toBeInTheDocument();
  });

  // CC-1 Factory Loop closeout, item 4a: agent_run_summaries.json IS
  // committed (unlike agent_test_results.json, which currently is not --
  // see this directive's own closing report) and must reach the TOO_SLOW
  // panel through LabPage's real fetch wiring, not just the component in
  // isolation.
  it("wires agent_run_summaries.json's TOO_SLOW names through to the panel", async () => {
    setupMocks({
      agentRunSummaries: [
        {
          run_at: "2026-08-04T11:19:56.922724+00:00",
          too_slow: [
            { hypothesis_name: "RSI2_TREND_PULLBACK_PAXG_4H", measured_trades_per_year: 0.5, llm_claimed_trades_per_year: 35.0 },
          ],
        },
      ],
    });
    render(await LabPage());

    expect(screen.getByTestId("agent-too-slow-row")).toHaveTextContent("RSI2_TREND_PULLBACK_PAXG_4H");
  });
});
