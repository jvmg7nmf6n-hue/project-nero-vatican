import { fireEvent, render, screen } from "@testing-library/react";
import StrategyDetailPage from "@/app/strategy/[id]/page";
import * as data from "@/lib/data";
import type { CandleFetchResult } from "@/lib/data";
import type {
  LedgerExport,
  LedgerRow,
  QuantMetricsExport,
  StatsExport,
  StrategiesExport,
  StrategyDescriptions,
  StrategyStats,
} from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchStrategies = jest.mocked(data.fetchStrategies);
const mockFetchStats = jest.mocked(data.fetchStats);
const mockFetchLedgerFull = jest.mocked(data.fetchLedgerFull);
const mockFetchLedgerRecent = jest.mocked(data.fetchLedgerRecent);
const mockFetchStrategyDescriptions = jest.mocked(data.fetchStrategyDescriptions);
const mockFetchCandleData = jest.mocked(data.fetchCandleData);
const mockFetchQuantMetrics = jest.mocked(data.fetchQuantMetrics);

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
const DEFAULT_DESCRIPTIONS: StrategyDescriptions = {
  BREAKOUT_MOMENTUM: { mechanism: "Test mechanism description.", verification_note: "Test verification note." },
};

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
  ledgerRecent?: LedgerExport | null;
  descriptions?: StrategyDescriptions | null;
  candle?: CandleFetchResult;
  quantMetrics?: QuantMetricsExport | null;
} = {}) {
  mockFetchStrategies.mockResolvedValue(
    overrides.strategies ?? { schema_version: 1, last_updated: "x", strategies: [ROSTER_ENTRY] }
  );
  mockFetchStats.mockResolvedValue(overrides.stats ?? EMPTY_STATS_EXPORT);
  mockFetchLedgerFull.mockResolvedValue(overrides.ledger ?? EMPTY_LEDGER_EXPORT);
  // Default: no recent-signal rows -- matches every test that predates Day 7 and
  // never intended to exercise the Live Market Status Widget's signal pill.
  mockFetchLedgerRecent.mockResolvedValue(overrides.ledgerRecent !== undefined ? overrides.ledgerRecent : EMPTY_LEDGER_EXPORT);
  mockFetchStrategyDescriptions.mockResolvedValue(
    overrides.descriptions !== undefined ? overrides.descriptions : DEFAULT_DESCRIPTIONS
  );
  // Default: no candle file provisioned for this test roster -- matches most
  // existing tests, which predate Day 2 and never intended to exercise the chart.
  mockFetchCandleData.mockResolvedValue(overrides.candle ?? { status: "not_found" });
  // Default: no quant_metrics.json entry -- matches every test that predates Day 4
  // and never intended to exercise the Quant Panel.
  mockFetchQuantMetrics.mockResolvedValue(overrides.quantMetrics !== undefined ? overrides.quantMetrics : null);
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
    expect(screen.getByTestId("strategy-description")).toBeInTheDocument();
    expect(screen.getByText("Test mechanism description.")).toBeInTheDocument();
    expect(screen.getByText("Test verification note.")).toBeInTheDocument();
  });

  it("shows the awaiting-first-signal state when resolved_trades is 0", async () => {
    setupMocks({ stats: { schema_version: 1, last_updated: "x", strategies: [statsRow({ resolved_trades: 0 })] } });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("performance-awaiting")).toBeInTheDocument();
    expect(screen.queryByTestId("performance-summary")).not.toBeInTheDocument();
    expect(screen.getByTestId("trade-history-empty")).toBeInTheDocument();
    expect(screen.getByTestId("equity-curve-awaiting")).toBeInTheDocument();
    expect(screen.queryByTestId("equity-curve-chart")).not.toBeInTheDocument();
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
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("equity-curve-awaiting")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("equity-curve-point")).toHaveLength(1);
  });

  it("falls back to a generic message when strategy_descriptions.json has no entry for this family", async () => {
    setupMocks({ descriptions: {} });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("strategy-description-fallback")).toBeInTheDocument();
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

describe("StrategyDetailPage candlestick chart (Day 2)", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("shows the chart/equity-curve tab toggle and defaults to Price Chart when a candle file exists", async () => {
    setupMocks({
      candle: {
        status: "ok",
        data: {
          schema_version: 1,
          asset: "GOLD",
          timeframe: "1week",
          last_updated: "x",
          candles: [{ time: 1700000000, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 }],
        },
      },
    });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByText("Charts")).toBeInTheDocument();
    expect(screen.getByTestId("chart-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("tab-price-chart")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
  });

  it("shows 'Price chart coming soon' when no candle file exists for this asset/timeframe", async () => {
    setupMocks({ candle: { status: "not_found" } });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    fireEvent.click(screen.getByTestId("tab-price-chart"));
    expect(screen.getByTestId("price-chart-unavailable")).toHaveTextContent("Price chart coming soon.");
  });

  it("shows 'Price data temporarily unavailable' when the candle fetch fails", async () => {
    setupMocks({ candle: { status: "error" } });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    fireEvent.click(screen.getByTestId("tab-price-chart"));
    expect(screen.getByTestId("price-chart-unavailable")).toHaveTextContent("Price data temporarily unavailable.");
  });

  it("renders the chart with no markers when there are zero resolved trades but candle data exists", async () => {
    setupMocks({
      candle: {
        status: "ok",
        data: {
          schema_version: 1,
          asset: "GOLD",
          timeframe: "1week",
          last_updated: "x",
          candles: [{ time: 1700000000, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 }],
        },
      },
      stats: { schema_version: 1, last_updated: "x", strategies: [statsRow({ resolved_trades: 0 })] },
    });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
  });

  it("shows equity-curve-only with no chart tab for a pair strategy (BTC-ETH/GOLD-SILVER)", async () => {
    setupMocks({
      strategies: {
        schema_version: 1,
        last_updated: "x",
        strategies: [
          {
            name: "COINTEGRATION_PAIRS",
            version: "cointegration-pairs-v1.0.0",
            asset: "BTC-ETH",
            timeframe: "12h",
            verification_status: "verified — weakest, live-proving",
            source_report: null,
          },
        ],
      },
    });

    const jsx = await StrategyDetailPage({
      params: { id: "cointegration-pairs--btc-eth--cointegration-pairs-v1-0-0" },
    });
    render(jsx);

    expect(screen.getByText("Equity curve")).toBeInTheDocument();
    expect(screen.queryByTestId("chart-tabs")).not.toBeInTheDocument();
    expect(screen.queryByTestId("candlestick-chart")).not.toBeInTheDocument();
    // fetchCandleData must never even be called for a pair asset.
    expect(mockFetchCandleData).not.toHaveBeenCalled();
  });

  it("switches to the Equity Curve tab on click, keeping both views accessible", async () => {
    setupMocks({
      candle: {
        status: "ok",
        data: {
          schema_version: 1,
          asset: "GOLD",
          timeframe: "1week",
          last_updated: "x",
          candles: [{ time: 1700000000, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 }],
        },
      },
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

    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tab-equity-curve"));
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("candlestick-chart")).not.toBeInTheDocument();
  });
});

describe("StrategyDetailPage Quant Panel (Day 4)", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders the Quant Panel with real metrics when a matching quant_metrics.json entry exists", async () => {
    setupMocks({
      quantMetrics: {
        schema_version: 1,
        last_updated: "x",
        metrics: [
          {
            asset: "GOLD",
            timeframe: "1week",
            periods_per_year: 52,
            window_used: 199,
            rf_annual: 0.0363,
            rf_source: "fred_dff",
            log_return_annualized: 0.2335,
            zscore_current: -1.43,
            realized_vol_annualized: 17.18,
            sharpe: 1.15,
            sortino: 1.8,
            computed_at: "2026-07-27T00:00:00+00:00",
          },
        ],
      },
    });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByText("Quant Panel")).toBeInTheDocument();
    expect(screen.getByTestId("quant-panel-grid")).toBeInTheDocument();
    expect(screen.getByTestId("quant-card-sharpe-value")).toHaveTextContent("1.15");
  });

  it("shows the graceful unavailable message when quant_metrics.json has no entry for this asset/timeframe", async () => {
    setupMocks(); // default: quantMetrics null
    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("quant-panel-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("quant-panel-grid")).not.toBeInTheDocument();
  });

  it("does not match a quant_metrics entry for a different asset or timeframe", async () => {
    setupMocks({
      quantMetrics: {
        schema_version: 1,
        last_updated: "x",
        metrics: [
          {
            asset: "GOLD",
            timeframe: "24h", // this strategy is 1week -- must not match
            periods_per_year: 365,
            window_used: 199,
            rf_annual: 0.0363,
            rf_source: "fred_dff",
            log_return_annualized: -0.17,
            zscore_current: 0.08,
            realized_vol_annualized: 29.9,
            sharpe: -0.69,
            sortino: -0.91,
            computed_at: "2026-07-27T00:00:00+00:00",
          },
        ],
      },
    });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("quant-panel-unavailable")).toBeInTheDocument();
  });
});

const SAMPLE_CANDLES = [
  { time: 1700000000, open: 3200, high: 3210, low: 3190, close: 3200, volume: 1000 },
  { time: 1700604800, open: 3200, high: 3300, low: 3195, close: 3287.5, volume: 1200 },
];

function candleResultOk(candles = SAMPLE_CANDLES): CandleFetchResult {
  return {
    status: "ok",
    data: { schema_version: 1, asset: "GOLD", timeframe: "1week", last_updated: "x", candles },
  };
}

describe("StrategyDetailPage Chart Description (Day 7)", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders the collapsible chart description when a candle file exists", async () => {
    setupMocks({ candle: candleResultOk() });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("chart-description")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.getByTestId("chart-description-timeframe")).toHaveTextContent("1 week");
    expect(screen.getByTestId("chart-description-status")).toHaveTextContent("No completed trades yet");
  });

  it("does not render the chart description when no candle data exists", async () => {
    setupMocks({ candle: { status: "not_found" } });

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.queryByTestId("chart-description")).not.toBeInTheDocument();
  });

  it("does not render the chart description for a pair-asset strategy", async () => {
    setupMocks({
      strategies: {
        schema_version: 1,
        last_updated: "x",
        strategies: [
          {
            name: "COINTEGRATION_PAIRS",
            version: "cointegration-pairs-v1.0.0",
            asset: "BTC-ETH",
            timeframe: "12h",
            verification_status: "verified — weakest, live-proving",
            source_report: null,
          },
        ],
      },
    });

    const jsx = await StrategyDetailPage({
      params: { id: "cointegration-pairs--btc-eth--cointegration-pairs-v1-0-0" },
    });
    render(jsx);

    expect(screen.queryByTestId("chart-description")).not.toBeInTheDocument();
  });
});

describe("StrategyDetailPage ChatBot (Day 7)", () => {
  const originalApiKey = process.env.ANTHROPIC_API_KEY;

  afterEach(() => {
    jest.resetAllMocks();
    process.env.ANTHROPIC_API_KEY = originalApiKey;
  });

  it("renders the collapsed ChatBot toggle on every strategy page", async () => {
    delete process.env.ANTHROPIC_API_KEY;
    setupMocks();

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    expect(screen.getByTestId("chatbot-toggle-open")).toBeInTheDocument();
  });

  it("shows FAQ chips (with real strategy data) but hides live chat input when ANTHROPIC_API_KEY is unset", async () => {
    delete process.env.ANTHROPIC_API_KEY;
    setupMocks();

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    fireEvent.click(screen.getByTestId("chatbot-toggle-open"));
    expect(screen.getByTestId("faq-chip-0")).toHaveTextContent("What does this strategy do?");
    expect(screen.queryByTestId("chat-input")).not.toBeInTheDocument();
  });

  it("shows the live chat input when ANTHROPIC_API_KEY is set", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    setupMocks();

    const jsx = await StrategyDetailPage({ params: { id: STRATEGY_ID } });
    render(jsx);

    fireEvent.click(screen.getByTestId("chatbot-toggle-open"));
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });

  it("also renders the ChatBot for a pair-asset strategy (every strategy page, not just non-pair)", async () => {
    delete process.env.ANTHROPIC_API_KEY;
    setupMocks({
      strategies: {
        schema_version: 1,
        last_updated: "x",
        strategies: [
          {
            name: "COINTEGRATION_PAIRS",
            version: "cointegration-pairs-v1.0.0",
            asset: "BTC-ETH",
            timeframe: "12h",
            verification_status: "verified — weakest, live-proving",
            source_report: null,
          },
        ],
      },
    });

    const jsx = await StrategyDetailPage({
      params: { id: "cointegration-pairs--btc-eth--cointegration-pairs-v1-0-0" },
    });
    render(jsx);

    expect(screen.getByTestId("chatbot-toggle-open")).toBeInTheDocument();
  });
});
