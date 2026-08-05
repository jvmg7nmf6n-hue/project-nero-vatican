import { render, screen } from "@testing-library/react";
import AgentsPage from "@/app/agents/page";
import * as data from "@/lib/data";
import type { AgentPerformanceExport, AgentRunSummary, EveBudgetLedgerEntry, EveHypothesisRecord, EveSessionRegistryExport } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchEveSessionRegistry = jest.mocked(data.fetchEveSessionRegistry);
const mockFetchEveHypotheses = jest.mocked(data.fetchEveHypotheses);
const mockFetchEveBudgetLedger = jest.mocked(data.fetchEveBudgetLedger);
const mockFetchAgentPerformance = jest.mocked(data.fetchAgentPerformance);
const mockFetchAgentRunSummaries = jest.mocked(data.fetchAgentRunSummaries);

function registry(overrides: Partial<EveSessionRegistryExport> = {}): EveSessionRegistryExport {
  return {
    pre_registration: {
      sessions_budgeted: "8 Eve sessions + 8 Adam runs (~$14)",
      eve_must_clear: "5% OOS survival, FDR-corrected PER SESSION",
      kill_criterion: "if Eve does not clear 5% after 8 (countable) sessions...",
    },
    sessions: [
      {
        session_id: "eve-20260803T074058Z-df7df0f9",
        counts_toward_pre_registered_8: false,
        classification: "crashed_before_completion",
        reason: "ReadTimeout at the old 60s ceiling.",
      },
      {
        session_id: "eve-20260804T020749Z-4cf6e4c9",
        counts_toward_pre_registered_8: true,
        classification: "session_1_of_8",
        reason: "Ran to completion.",
      },
    ],
    next_countable_session_number: 2,
    ...overrides,
  };
}

function performance(overrides: Partial<AgentPerformanceExport["cumulative"]> = {}): AgentPerformanceExport {
  return {
    schema_version: 1,
    last_updated: "2026-08-04T11:10:43+00:00",
    cumulative: {
      hypotheses_generated: 2,
      duplicates_skipped: 0,
      too_slow_rejected: 2,
      unmeasurable_rejected: 0,
      tested: 0,
      survived: 0,
      promising_watchlist: 0,
      died: 0,
      untestable: 0,
      no_candles_available: 0,
      llm_calls_made: 9,
      total_llm_cost_usd: 0.55804,
      survival_rate: null,
      calls_with_unknown_cost: 4,
      ...overrides,
    },
    runs: [],
  };
}

async function setupAndRender(options: {
  registry?: EveSessionRegistryExport | null;
  hypotheses?: EveHypothesisRecord[] | null;
  ledger?: EveBudgetLedgerEntry[] | null;
  performance?: AgentPerformanceExport | null;
  runSummaries?: AgentRunSummary[] | null;
}) {
  mockFetchEveSessionRegistry.mockResolvedValue("registry" in options ? options.registry! : registry());
  mockFetchEveHypotheses.mockResolvedValue("hypotheses" in options ? options.hypotheses! : []);
  mockFetchEveBudgetLedger.mockResolvedValue("ledger" in options ? options.ledger! : []);
  mockFetchAgentPerformance.mockResolvedValue("performance" in options ? options.performance! : performance());
  mockFetchAgentRunSummaries.mockResolvedValue("runSummaries" in options ? options.runSummaries! : []);
  render(await AgentsPage());
}

describe("AgentsPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("shows pre-registration progress with real counts", async () => {
    await setupAndRender({});
    const progress = screen.getByTestId("pre-registration-progress");
    expect(progress).toHaveTextContent("Session 1 of 8");
    expect(progress).toHaveTextContent("7 remaining");
    expect(progress).toHaveTextContent("0 SURVIVED");
  });

  it("shows both agents' funnels", async () => {
    await setupAndRender({});
    expect(screen.getAllByText("Eve").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Adam").length).toBeGreaterThan(0);
  });

  it("shows crashed sessions -- never hides a failure", async () => {
    await setupAndRender({});
    const rows = screen.getAllByTestId("session-health-row");
    expect(rows.length).toBe(2);
    const crashedRow = rows.find((r) => r.getAttribute("data-crashed") === "true");
    expect(crashedRow).toHaveTextContent("eve-20260803T074058Z-df7df0f9");
  });

  it("shows an unknown-cost note for both agents when unknown calls exist", async () => {
    await setupAndRender({
      ledger: [
        { session_id: "s", status: "reserved", actual_cost_usd: null, projected_cost_usd: 1.27371, month: "2026-08" },
      ],
    });
    expect(screen.getByTestId("eve-unknown-cost-note")).toHaveTextContent("1 call of unknown cost");
    expect(screen.getByTestId("adam-unknown-cost-note")).toHaveTextContent("4 calls of unknown cost");
  });

  it("shows real frequency claims when run summaries carry them", async () => {
    await setupAndRender({
      runSummaries: [
        {
          run_at: "2026-08-04T11:19:56.922724+00:00",
          too_slow: [
            { hypothesis_name: "RSI2_TREND_PULLBACK_PAXG_4H", measured_trades_per_year: 0.498181404864742, llm_claimed_trades_per_year: 35.0 },
          ],
        },
      ],
    });
    const row = screen.getByTestId("frequency-claim-row");
    expect(row).toHaveTextContent("RSI2_TREND_PULLBACK_PAXG_4H");
    expect(row).toHaveTextContent("claimed 35.0/yr, measured 0.5/yr");
  });

  it("shows honest empty states, never a fabricated zero, when nothing has run", async () => {
    await setupAndRender({
      registry: null,
      hypotheses: [],
      ledger: [],
      performance: null,
      runSummaries: [],
    });
    expect(screen.getByTestId("session-health-empty")).toBeInTheDocument();
    expect(screen.getByTestId("frequency-claims-empty")).toBeInTheDocument();
    expect(screen.getAllByText(/not yet reporting/).length).toBeGreaterThan(0);
  });
});
