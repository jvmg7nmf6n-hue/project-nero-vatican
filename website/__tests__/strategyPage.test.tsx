import { render, screen } from "@testing-library/react";
import StrategyDetailPage from "@/app/strategy/[id]/page";
import * as data from "@/lib/data";
import type {
  LedgerExport,
  LedgerRow,
  StatsExport,
  StrategiesExport,
  StrategyDescriptions,
  StrategyStats,
} from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchStrategies = jest.mocked(data.fetchStrategies);
const mockFetchStats = jest.mocked(data.fetchStats);
const mockFetchLedgerFull = jest.mocked(data.fetchLedgerFull);
const mockFetchStrategyDescriptions = jest.mocked(data.fetchStrategyDescriptions);

const STRATEGY_ID = "breakout-momentum--gold--breakout-momentum-v1-2-0-gold-calibrated-1week";

const ROSTER_ENTRY = {
  name: "BREAKOUT_MOMENTUM",
  version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
  asset: "GOLD",
  timeframe: "1week",
  verification_status: "triple-verified",
  source_report: "docs/statistical_harness_upgrade.md",
};

const EMPTY_STATS_EXPORT: StatsExport = { schema_version: 1, last_updated: "x", strategies: [] };
const EMPTY_LEDGER_EXPORT: LedgerExport = { schema_version: 1, last_updated: "x", rows: [] };
const DEFAULT_DESCRIPTIONS: StrategyDescriptions = { BREAKOUT_MOMENTUM: "Test mechanism description." };

function statsRow(overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy: ROSTER_ENTRY.name,
    strategy_version: ROSTER_ENTRY.version,
    asset: ROSTER_ENTRY.asset,
    resolved_trades: 0,
    win_rate: null,
    expectancy_r: null,
    avg_return_pct: null,
    signal_counts: { ENTRY: 0, EXIT: 0, WATCH: 0, NO_TRADE: 0 },
    open_position: null,
    ...overrides,
  };
}

function ledgerRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-01T00:00:00Z",
    strategy: ROSTER_ENTRY.name,
    strategy_version: ROSTER_ENTRY.version,
    asset: ROSTER_ENTRY.asset,
    signal_type: "ENTRY",
    entry_price: 100,
    exit_price: null,
    reasoning: "",
    candle_timestamp: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function setupMocks(overrides: {
  strategies?: StrategiesExport | null;
  stats?: StatsExport | null;
  ledger?: LedgerExport | null;
  descriptions?: StrategyDescriptions | null;
} = {}) {
  mockFetchStrategies.mockResolvedValue(
    overrides.strategies ?? { schema_version: 1, last_updated: "x", strategies: [ROSTER_ENTRY] }
  );
  mockFetchStats.mockResolvedValue(overrides.stats ?? EMPTY_STATS_EXPORT);
  mockFetchLedgerFull.mockResolvedValue(overrides.ledger ?? EMPTY_LEDGER_EXPORT);
  mockFetchStrategyDescriptions.mockResolvedValue(
    overrides.descriptions !== undefined ? overrides.descriptions : DEFAULT_DESCRIPTIONS
  );
}

describe("StrategyDetailPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders the header, tier badge, and description for a known strategy", async () => {
    setupMocks();

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByText("BREAKOUT_MOMENTUM")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Test mechanism description.")).toBeInTheDocument();
  });

  it("shows the awaiting-first-signal state when resolved_trades is 0", async () => {
    setupMocks({ stats: { schema_version: 1, last_updated: "x", strategies: [statsRow({ resolved_trades: 0 })] } });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("performance-awaiting")).toBeInTheDocument();
    expect(screen.queryByTestId("performance-summary")).not.toBeInTheDocument();
    expect(screen.getByTestId("trade-history-empty")).toBeInTheDocument();
  });

  it("renders the performance summary and trade history table when trades exist", async () => {
    setupMocks({
      stats: {
        schema_version: 1,
        last_updated: "x",
        strategies: [statsRow({ resolved_trades: 1, win_rate: 1, expectancy_r: 1.5, avg_return_pct: 10 })],
      },
      ledger: {
        schema_version: 1,
        last_updated: "x",
        rows: [
          ledgerRow({ signal_type: "ENTRY", entry_price: 100, timestamp: "t1", candle_timestamp: "2026-07-01T00:00:00Z" }),
          ledgerRow({
            signal_type: "EXIT", entry_price: null, exit_price: 110, timestamp: "t2",
            candle_timestamp: "2026-07-02T00:00:00Z", reasoning: "TARGET exit, r_multiple=1.500",
          }),
        ],
      },
    });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("performance-summary")).toBeInTheDocument();
    expect(screen.queryByTestId("performance-awaiting")).not.toBeInTheDocument();
    expect(screen.getByTestId("trade-history-table")).toBeInTheDocument();
    expect(screen.getByText("WIN")).toBeInTheDocument();
    expect(screen.getByText("1.50R")).toBeInTheDocument();
  });

  it("falls back to a generic message when strategy_descriptions.json has no entry for this family", async () => {
    setupMocks({ descriptions: {} });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByText("A written description for this strategy hasn't been added yet.")).toBeInTheDocument();
  });

  it("shows a no-source-report message when source_report is null", async () => {
    setupMocks({
      strategies: {
        schema_version: 1,
        last_updated: "x",
        strategies: [{ ...ROSTER_ENTRY, source_report: null }],
      },
    });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("no-source-report")).toBeInTheDocument();
  });

  it("throws (triggering the 404 boundary) for an id matching no roster entry", async () => {
    setupMocks();

    await expect(
      StrategyDetailPage({ params: { id: "not-a-real-strategy--xyz--v9" } })
    ).rejects.toThrow();
  });
});
