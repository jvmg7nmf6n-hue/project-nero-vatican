import { fireEvent, render, screen } from "@testing-library/react";
import AgentsPage from "@/app/agents/page";
import * as data from "@/lib/data";
import type { AgentPerformanceExport, AgentRunSummary, EveBudgetLedgerEntry, EveHypothesisRecord, EveSessionRegistryExport } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchEveSessionRegistry = jest.mocked(data.fetchEveSessionRegistry);
const mockFetchEveHypotheses = jest.mocked(data.fetchEveHypotheses);
const mockFetchEveBudgetLedger = jest.mocked(data.fetchEveBudgetLedger);
const mockFetchAgentPerformance = jest.mocked(data.fetchAgentPerformance);
const mockFetchAgentRunSummaries = jest.mocked(data.fetchAgentRunSummaries);
const mockFetchEveSessionRecord = jest.mocked(data.fetchEveSessionRecord);
const mockFetchForwardTrial = jest.mocked(data.fetchForwardTrial);

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
  sessionRecordFor?: (sessionId: string) => { session_id: string; terminated_because: string; partial?: boolean } | null;
}) {
  mockFetchEveSessionRegistry.mockResolvedValue("registry" in options ? options.registry! : registry());
  mockFetchEveHypotheses.mockResolvedValue("hypotheses" in options ? options.hypotheses! : []);
  mockFetchEveBudgetLedger.mockResolvedValue("ledger" in options ? options.ledger! : []);
  mockFetchAgentPerformance.mockResolvedValue("performance" in options ? options.performance! : performance());
  mockFetchAgentRunSummaries.mockResolvedValue("runSummaries" in options ? options.runSummaries! : []);
  mockFetchEveSessionRecord.mockImplementation(async (sessionId: string) =>
    options.sessionRecordFor ? options.sessionRecordFor(sessionId) : { session_id: sessionId, terminated_because: "end_session_called" }
  );
  mockFetchForwardTrial.mockResolvedValue(null);
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

  it("shows the kill criterion verbatim, not just the sessions-budgeted/must-clear text", async () => {
    // CC-1 directive item 5d: kill_criterion was typed (lib/types.ts) and
    // fetched but never actually rendered anywhere on this page -- a real,
    // confirmed gap this test closes.
    await setupAndRender({});
    expect(screen.getByTestId("kill-criterion")).toHaveTextContent(
      "if Eve does not clear 5% after 8 (countable) sessions",
    );
  });

  it("shows the random baseline panel with the real 0-survived headline", async () => {
    // CC-1 directive item 5a: the strongest evidence in the project,
    // static (not live-fetched) but must always be present and correct.
    await setupAndRender({});
    const panel = screen.getByTestId("random-baseline-panel");
    expect(panel).toHaveTextContent("0 SURVIVED out of 1000 random hypotheses");
    expect(panel).toHaveTextContent("PAXG");
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

  it("shows how-it-works and measured-characteristics sections", async () => {
    await setupAndRender({});
    expect(screen.getByTestId("how-it-works")).toBeInTheDocument();
    expect(screen.getByTestId("measured-characteristics")).toBeInTheDocument();
  });

  // CC-1 follow-up directive, "make every Agents-page number live, not
  // hardcoded": deliberately uses numbers that do NOT match production
  // (2 of 5 UNTESTABLE_BY_DSL = 40%, 3 of 4 crashed, a single $0.30
  // completed session) -- if a future edit hardcodes the real production
  // figures (19.0%, 6 of 10, $0.5160) into the JSX instead of reading the
  // computed props, this test fails because the rendered page would show
  // the WRONG (real-looking but stale) numbers against this mock data.
  it("computes measured-characteristics numbers from injected data, not hardcoded literals", async () => {
    function hyp(testability: string): EveHypothesisRecord {
      return {
        session_id: "s",
        raw_hypothesis: { hypothesis_name: "X" },
        testability,
        verdict_combined: null,
        frequency_classification: null,
        measured_trades_per_year: null,
        contamination_tags: [],
      };
    }
    await setupAndRender({
      hypotheses: [hyp("UNTESTABLE_BY_DSL"), hyp("UNTESTABLE_BY_DSL"), hyp("TESTABLE"), hyp("TESTABLE"), hyp("TESTABLE")],
      registry: registry({
        sessions: [
          { session_id: "eve-crash-1", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
          { session_id: "eve-crash-2", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
          { session_id: "eve-crash-3", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
          { session_id: "eve-done-1", counts_toward_pre_registered_8: true, classification: "session_1_of_8", reason: "x" },
        ],
      }),
      ledger: [
        { session_id: "eve-done-1", status: "actual", actual_cost_usd: 0.3, projected_cost_usd: 0.3, month: "2026-08" },
      ],
    });
    const section = screen.getByTestId("measured-characteristics");
    expect(section).toHaveTextContent("2 of 5 hypotheses on file (40.0%)");
    expect(section).toHaveTextContent("3 of 4 recorded session attempts crashed");
    expect(section).toHaveTextContent("$0.3000 across 1 completed session");
    expect(section).not.toHaveTextContent("19.0%");
    expect(section).not.toHaveTextContent("6 of 10");
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

  // CC-1 overnight directive, Part 1.1: the Reliability chart must read a
  // completed session's real crash/clean status from its own auto-written
  // eve_sessions/<id>.json file (fetchEveSessionRecord), NOT the manually-
  // curated registry classification -- this test injects a session file
  // showing a real crash (terminated_because != end_session_called) for a
  // session the REGISTRY itself classifies as a normal completion, and
  // asserts the page reflects the FILE's real status, proving it actually
  // reads from there and doesn't just trust the registry.
  it("Learning Curve Reliability chart reads crash/clean status from the real auto-written session file, not the registry", async () => {
    await setupAndRender({
      registry: registry({
        sessions: [
          {
            session_id: "eve-20260804T020749Z-4cf6e4c9",
            counts_toward_pre_registered_8: true,
            classification: "session_1_of_8", // registry says this completed normally...
            reason: "Ran to completion.",
          },
        ],
      }),
      sessionRecordFor: (sessionId) => ({ session_id: sessionId, terminated_because: "crashed_mid_session", partial: true }),
    });

    const dots = screen.getByTestId("reliability-dots-eve").querySelectorAll("div[title]");
    expect(dots.length).toBe(1);
    // ...but the real session file says it crashed -- the chart must show that, not the registry's claim.
    expect(dots[0].getAttribute("title")).toContain("crashed");
    expect(dots[0].className).toContain("bg-loss");
  });

  it("Learning Curve shows real reliability, quality, and near-miss data end to end", async () => {
    await setupAndRender({
      registry: registry({
        sessions: [
          { session_id: "eve-crash-1", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
          { session_id: "eve-done-1", counts_toward_pre_registered_8: true, classification: "session_1_of_8", reason: "x" },
        ],
      }),
      hypotheses: [
        {
          session_id: "eve-done-1", raw_hypothesis: { hypothesis_name: "A" }, testability: "UNTESTABLE_BY_DSL",
          verdict_combined: null, frequency_classification: null, measured_trades_per_year: null, contamination_tags: [],
        },
        {
          session_id: "eve-done-1", raw_hypothesis: { hypothesis_name: "B" }, testability: "TESTABLE",
          verdict_combined: "DIED", frequency_classification: "VIABLE", measured_trades_per_year: 10, contamination_tags: [],
        },
      ],
    });

    expect(screen.getByTestId("learning-curve-section")).toBeInTheDocument();
    expect(screen.getByText(/not a claim that either agent is getting/)).toBeInTheDocument();
    expect(screen.getByTestId("reliability-dots-eve").children.length).toBe(2);

    fireEvent.click(screen.getByTestId("learning-curve-tab-quality"));
    expect(screen.getByTestId("learning-curve-quality")).toHaveTextContent("1 of 2 DSL-invalid");

    fireEvent.click(screen.getByTestId("learning-curve-tab-near-miss"));
    expect(screen.getByTestId("learning-curve-near-miss")).toBeInTheDocument();
  });
});
