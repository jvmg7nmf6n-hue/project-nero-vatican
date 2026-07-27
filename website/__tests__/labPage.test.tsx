import { render, screen } from "@testing-library/react";
import LabPage from "@/app/lab/page";
import * as data from "@/lib/data";
import type {
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
    setupMocks({ graveyard: null, failurePatterns: null, repairCandidates: null });
    mockFetchStrategies.mockResolvedValue(null);
    mockFetchStats.mockResolvedValue(null);
    render(await LabPage());

    expect(screen.getByText("No research history recorded yet.")).toBeInTheDocument();
    expect(screen.getByTestId("repair-candidates-empty")).toBeInTheDocument();
  });
});
