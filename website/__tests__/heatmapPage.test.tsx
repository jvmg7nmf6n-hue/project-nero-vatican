import { render, screen } from "@testing-library/react";
import HeatmapPage from "@/app/heatmap/page";
import * as data from "@/lib/data";
import type { StatsExport, StrategiesExport, StrategyRosterEntry, StrategyStats } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchStrategies = jest.mocked(data.fetchStrategies);
const mockFetchStats = jest.mocked(data.fetchStats);

function entry(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
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

function stats(overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.0.0",
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

function setupMocks(roster: StrategyRosterEntry[], statsRows: StrategyStats[]) {
  const strategiesExport: StrategiesExport = { schema_version: 1, last_updated: "x", strategies: roster };
  const statsExport: StatsExport = { schema_version: 1, last_updated: "x", strategies: statsRows };
  mockFetchStrategies.mockResolvedValue(strategiesExport);
  mockFetchStats.mockResolvedValue(statsExport);
}

describe("HeatmapPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders a no-assets message when the roster is empty", async () => {
    setupMocks([], []);
    render(await HeatmapPage());
    expect(screen.getByText("No assets registered yet.")).toBeInTheDocument();
  });

  it("renders one tile per asset with mixed win-rate data", async () => {
    setupMocks(
      [entry({ asset: "GOLD" }), entry({ asset: "BTC", name: "COINTEGRATION_PAIRS" })],
      [
        stats({ asset: "GOLD", resolved_trades: 20, win_rate: 0.7 }),
        stats({ asset: "BTC", strategy: "COINTEGRATION_PAIRS", resolved_trades: 15, win_rate: 0.3 }),
      ]
    );
    render(await HeatmapPage());

    const tiles = screen.getAllByTestId("heatmap-tile");
    expect(tiles).toHaveLength(2);
    expect(screen.getByText("70% win")).toBeInTheDocument();
    expect(screen.getByText("30% win")).toBeInTheDocument();
  });

  it("shows a neutral 'no data yet' state for an asset with zero resolved trades", async () => {
    setupMocks([entry({ asset: "GOLD" })], [stats({ asset: "GOLD", resolved_trades: 0 })]);
    render(await HeatmapPage());

    const tile = screen.getByTestId("heatmap-tile");
    expect(tile).toHaveAttribute("data-has-data", "false");
    expect(screen.getByText("no data yet")).toBeInTheDocument();
  });

  it("links each tile to the dashboard filtered to that asset", async () => {
    setupMocks([entry({ asset: "EUR/USD", name: "DONCHIAN_TREND" })], []);
    render(await HeatmapPage());

    const tile = screen.getByTestId("heatmap-tile");
    expect(tile).toHaveAttribute("href", "/?asset=EUR%2FUSD");
  });
});
