import { render, screen } from "@testing-library/react";
import FactoryLoopPage from "@/app/factory-loop/page";
import * as data from "@/lib/data";
import type { AgentHypothesis, AgentPerformanceExport, FactoryLoopStatusExport, ForwardTrialRecord, GraveyardEntry, TrialEntry } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchGraveyard = jest.mocked(data.fetchGraveyard);
const mockFetchFactoryLoopStatus = jest.mocked(data.fetchFactoryLoopStatus);
const mockFetchAgentPerformance = jest.mocked(data.fetchAgentPerformance);
const mockFetchForwardTrial = jest.mocked(data.fetchForwardTrial);
const mockFetchTrialEntries = jest.mocked(data.fetchTrialEntries);
const mockFetchAgentHypotheses = jest.mocked(data.fetchAgentHypotheses);
const mockFetchEveHypotheses = jest.mocked(data.fetchEveHypotheses);

function trialEntry(overrides: Partial<TrialEntry> = {}): TrialEntry {
  return {
    execution_log_id: 1,
    trial_id: "774476ca-8a12-453d-955b-52b8abfc294a",
    hypothesis_name: "RSI2_TREND_PULLBACK_PAXG_4H",
    origin_agent: "adam",
    asset: "ETH",
    timeframe: "4h",
    direction: "SHORT",
    entry_price: 1916.646594,
    stop_loss: 1951.9973082857143,
    target: 1881.2958797142858,
    timestamp: "2026-08-05T23:07:36.307597+00:00",
    candle_timestamp: 1785959999999,
    ...overrides,
  };
}

function forwardTrialRecord(overrides: Partial<ForwardTrialRecord> = {}): ForwardTrialRecord {
  return {
    trial_id: "774476ca-8a12-453d-955b-52b8abfc294a",
    source_hypothesis_ref: {
      origin: "fresh",
      origin_agent: "adam",
      hypothesis_name: "RSI2_TREND_PULLBACK_PAXG_4H",
      session_id_or_run_ref: null,
    },
    entry_verdict: { verdict: "SKIPPED" },
    measured_trades_per_year: 0.498181404864742,
    projected_time_to_min_sample_years: 40.14601870864704,
    projected_time_to_min_sample_label:
      "40.1 years at the currently measured rate (0.50 trades/year) -- EXCEEDS the 2-year visibility horizon (item 4b)",
    opened_at: "2026-08-05T23:04:59.453963+00:00",
    status: "OPEN",
    attribution: "Explored by Adam, our research agent.",
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

function performanceExport(overrides: Partial<AgentPerformanceExport["cumulative"]> = {}): AgentPerformanceExport {
  return {
    schema_version: 1,
    last_updated: "2026-08-05T00:00:00+00:00",
    cumulative: {
      hypotheses_generated: 2,
      duplicates_skipped: 0,
      too_slow_rejected: 1,
      unmeasurable_rejected: 0,
      tested: 0,
      survived: 0,
      promising_watchlist: 0,
      died: 0,
      untestable: 0,
      no_candles_available: 0,
      llm_calls_made: 2,
      total_llm_cost_usd: 0.01,
      survival_rate: null,
      ...overrides,
    },
    runs: [],
  };
}

function statusExport(overrides: Partial<FactoryLoopStatusExport> = {}): FactoryLoopStatusExport {
  return {
    schema_version: 1,
    last_updated: "2026-08-05T00:00:00+00:00",
    forward_trial: { count: 0, by_origin: { adam: 0, eve: 0, repaired: 0 }, unmeasurable_count: 0 },
    graveyard: { count: 21, distilled_this_period: 0, pending_review: 0 },
    repair: { count: 0, open_chains: 0, resolved_chains: 0 },
    ...overrides,
  };
}

describe("FactoryLoopPage", () => {
  beforeEach(() => {
    mockFetchForwardTrial.mockResolvedValue(null);
    mockFetchTrialEntries.mockResolvedValue(null);
    mockFetchAgentHypotheses.mockResolvedValue(null);
    mockFetchEveHypotheses.mockResolvedValue(null);
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders the real graveyard count from fetchGraveyard, never a fetch call itself", async () => {
    mockFetchGraveyard.mockResolvedValue([graveyardEntry(), graveyardEntry({ name: "REGIME_TRANSITION" })]);
    mockFetchFactoryLoopStatus.mockResolvedValue(null);
    mockFetchAgentPerformance.mockResolvedValue(null);

    render(await FactoryLoopPage());

    expect(screen.getByText("Factory Loop")).toBeInTheDocument();
    expect(screen.getByText("2", { exact: false })).toBeInTheDocument();
  });

  it("shows an honest not-yet-reporting fallback when factory_loop_status.json is null", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(null);
    mockFetchAgentPerformance.mockResolvedValue(null);

    render(await FactoryLoopPage());

    expect(screen.getByText(/has not started reporting yet/)).toBeInTheDocument();
  });

  it("renders real forward trial and repair counts when the status export is live", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({
        forward_trial: { count: 3, by_origin: { adam: 2, eve: 1, repaired: 0 }, unmeasurable_count: 1 },
        repair: { count: 1, open_chains: 1, resolved_chains: 0 },
      })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);

    render(await FactoryLoopPage());

    expect(screen.getAllByText("3").length).toBeGreaterThan(0);
    expect(screen.getByText(/2 from Adam/)).toBeInTheDocument();
  });

  it("never claims a blanket 'zero ever' -- states real SURVIVED/PROMISING-WATCHLIST numbers from live data", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(null);
    mockFetchAgentPerformance.mockResolvedValue(performanceExport({ survived: 0, promising_watchlist: 0 }));

    render(await FactoryLoopPage());

    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/zero hypotheses have ever reached/i);
  });

  it("introduces both Adam and Eve by name -- first public Eve mention on the site", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(null);
    mockFetchAgentPerformance.mockResolvedValue(null);

    render(await FactoryLoopPage());

    expect(screen.getAllByText(/Adam and Eve/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Eve/).length).toBeGreaterThan(0);
  });

  it("uses 'Forward Trial' naming, distinct from the existing 'Under Trial' roster tier", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(null);
    mockFetchAgentPerformance.mockResolvedValue(null);

    render(await FactoryLoopPage());

    expect(screen.getAllByText(/Forward Trial/).length).toBeGreaterThan(0);
    expect(screen.getByText(/unrelated to/)).toBeInTheDocument();
  });

  it("renders the loop diagram", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(null);
    mockFetchAgentPerformance.mockResolvedValue(null);

    render(await FactoryLoopPage());

    expect(screen.getByRole("img", { name: /Factory Loop/ })).toBeInTheDocument();
  });

  it("shows the unmeasurable_count honestly when a Trial entry projects beyond the 2-year horizon", async () => {
    // CC-1 directive item 1c: this field was already computed by
    // factory_loop_status_summary.py but never rendered anywhere -- real,
    // confirmed gap this test closes.
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({ forward_trial: { count: 8, by_origin: { adam: 2, eve: 6, repaired: 0 }, unmeasurable_count: 1 } })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);

    render(await FactoryLoopPage());

    expect(screen.getByTestId("unmeasurable-count")).toHaveTextContent("1");
    expect(screen.getByTestId("unmeasurable-count")).toHaveTextContent("not a bug or a joke");
  });

  it("shows the real per-hypothesis Forward Trial table when records exist", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({ forward_trial: { count: 1, by_origin: { adam: 1, eve: 0, repaired: 0 }, unmeasurable_count: 1 } })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);
    mockFetchForwardTrial.mockResolvedValue([forwardTrialRecord()]);

    render(await FactoryLoopPage());

    const row = screen.getByTestId("forward-trial-row");
    expect(row).toHaveTextContent("RSI2_TREND_PULLBACK_PAXG_4H");
    expect(row).toHaveTextContent("40.1 years");
  });

  it("never shows a resolved (non-OPEN) Trial record in the open-records table", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(statusExport({ forward_trial: { count: 1, by_origin: { adam: 0, eve: 1, repaired: 0 }, unmeasurable_count: 0 } }));
    mockFetchAgentPerformance.mockResolvedValue(null);
    mockFetchForwardTrial.mockResolvedValue([forwardTrialRecord({ status: "SURVIVED_TRIAL", source_hypothesis_ref: { origin: "fresh", origin_agent: "eve", hypothesis_name: "RESOLVED_ONE", session_id_or_run_ref: null } })]);

    render(await FactoryLoopPage());

    expect(screen.queryByTestId("forward-trial-table")).not.toBeInTheDocument();
  });

  // CC-1 directive, "Show real trial-entry activity on /factory-loop": a
  // Trial ADMISSION (status=="OPEN") is not the same real fact as a
  // genuine ENTRY (trial_entries.json, /signals' own real data) --
  // reusing fetchTrialEntries here, not a second read of the same file.
  it("shows a real OPEN position, not just admission status, when a matching trial_entries.json record exists", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({ forward_trial: { count: 1, by_origin: { adam: 1, eve: 0, repaired: 0 }, unmeasurable_count: 0 } })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);
    mockFetchForwardTrial.mockResolvedValue([forwardTrialRecord()]);
    mockFetchTrialEntries.mockResolvedValue({
      schema_version: 1,
      last_updated: "2026-08-05T23:10:08+00:00",
      entries: [trialEntry({ trial_id: "774476ca-8a12-453d-955b-52b8abfc294a", direction: "SHORT", entry_price: 1916.646594 })],
    });

    render(await FactoryLoopPage());

    const row = screen.getByTestId("forward-trial-row");
    const position = screen.getByTestId("forward-trial-position");
    expect(position).toHaveTextContent("OPEN SHORT @ 1916.6466");
    // The pre-existing projection column must stay visible alongside it,
    // not be replaced (item 1c).
    expect(row).toHaveTextContent("40.1 years");
  });

  it("shows 'waiting' for an admission with no matching trial_entries.json record, never fabricating a position", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({ forward_trial: { count: 1, by_origin: { adam: 1, eve: 0, repaired: 0 }, unmeasurable_count: 0 } })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);
    mockFetchForwardTrial.mockResolvedValue([forwardTrialRecord()]);
    mockFetchTrialEntries.mockResolvedValue({ schema_version: 1, last_updated: "x", entries: [] });

    render(await FactoryLoopPage());

    expect(screen.getByTestId("forward-trial-position")).toHaveTextContent("Waiting");
  });

  it("never lets a DIFFERENT trial's real entry bleed onto an unrelated admission's row", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({ forward_trial: { count: 1, by_origin: { adam: 1, eve: 0, repaired: 0 }, unmeasurable_count: 0 } })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);
    mockFetchForwardTrial.mockResolvedValue([forwardTrialRecord({ trial_id: "AAAA" })]);
    mockFetchTrialEntries.mockResolvedValue({
      schema_version: 1,
      last_updated: "x",
      entries: [trialEntry({ trial_id: "BBBB-different-trial" })],
    });

    render(await FactoryLoopPage());

    expect(screen.getByTestId("forward-trial-position")).toHaveTextContent("Waiting");
  });

  // CC-1 directive, "every strategy page must show entry/exit rules and
  // trade frequency", item 3c: a real structured_entry_rule/
  // structured_exit_plan, cross-referenced from agent_hypotheses.json by
  // hypothesis name, must render its real human-readable translation.
  it("shows the real translated entry/exit rule for a Forward Trial hypothesis, cross-referenced by name", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({ forward_trial: { count: 1, by_origin: { adam: 1, eve: 0, repaired: 0 }, unmeasurable_count: 0 } })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);
    mockFetchForwardTrial.mockResolvedValue([forwardTrialRecord({ trial_id: "T1", source_hypothesis_ref: { origin: "fresh", origin_agent: "adam", hypothesis_name: "RSI2_TREND_PULLBACK_PAXG_4H", session_id_or_run_ref: null } })]);
    const hyp: AgentHypothesis = {
      scan_finding: "x", scan_finding_type: "x", hypothesis_name: "RSI2_TREND_PULLBACK_PAXG_4H", mechanism: "x",
      entry_rule: "x", exit_rule: "x", stop_rule: "x", asset: "PAXG", timeframe: "4h",
      differs_from_graveyard: "x", expected_frequency_claim: null, generated_at: "x", cost_usd: 0, source: "scanner",
      structured_entry_rule: { conditions: [{ field: "rsi14", op: "lt", value: 30 }] },
      structured_exit_plan: { stop_atr_multiple: 1.5, target_r_multiple: 2.0 },
    };
    mockFetchAgentHypotheses.mockResolvedValue([hyp]);

    render(await FactoryLoopPage());

    const rulesRow = screen.getByTestId("forward-trial-rules-row");
    expect(rulesRow).toHaveTextContent("Enter when 14-period RSI is below 30.");
    expect(rulesRow).toHaveTextContent("a stop-loss 1.5x ATR(14) from entry");
  });

  it("shows an honest 'no rule available' note, never a fabricated one, when no matching hypothesis record exists", async () => {
    mockFetchGraveyard.mockResolvedValue([]);
    mockFetchFactoryLoopStatus.mockResolvedValue(
      statusExport({ forward_trial: { count: 1, by_origin: { adam: 1, eve: 0, repaired: 0 }, unmeasurable_count: 0 } })
    );
    mockFetchAgentPerformance.mockResolvedValue(null);
    mockFetchForwardTrial.mockResolvedValue([forwardTrialRecord()]);
    mockFetchAgentHypotheses.mockResolvedValue([]);
    mockFetchEveHypotheses.mockResolvedValue([]);

    render(await FactoryLoopPage());

    expect(screen.getByTestId("forward-trial-rules-row")).toHaveTextContent("No machine-checkable entry/exit rule available");
  });
});
