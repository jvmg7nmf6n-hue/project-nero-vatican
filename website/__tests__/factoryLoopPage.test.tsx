import { render, screen } from "@testing-library/react";
import FactoryLoopPage from "@/app/factory-loop/page";
import * as data from "@/lib/data";
import type { AgentPerformanceExport, FactoryLoopStatusExport, ForwardTrialRecord, GraveyardEntry } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchGraveyard = jest.mocked(data.fetchGraveyard);
const mockFetchFactoryLoopStatus = jest.mocked(data.fetchFactoryLoopStatus);
const mockFetchAgentPerformance = jest.mocked(data.fetchAgentPerformance);
const mockFetchForwardTrial = jest.mocked(data.fetchForwardTrial);

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
});
