import { render, screen } from "@testing-library/react";
import QuantPage from "@/app/quant/page";
import * as data from "@/lib/data";
import type { QuantCrossAssetExport, StrategiesExport } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchStrategies = jest.mocked(data.fetchStrategies);
const mockFetchQuantCrossAsset = jest.mocked(data.fetchQuantCrossAsset);

const ROSTER: StrategiesExport = {
  schema_version: 1,
  last_updated: "x",
  strategies: [
    { name: "A", version: "v1", asset: "BTC", timeframe: "24h", verification_status: "verified", source_report: null },
    { name: "B", version: "v1", asset: "GOLD", timeframe: "24h", verification_status: "verified", source_report: null },
  ],
};

const CROSS_ASSET: QuantCrossAssetExport = {
  schema_version: 1,
  last_updated: "x",
  correlation_matrix: [
    { asset_a: "BTC", asset_b: "GOLD", timeframe: "24h", correlation: 0.42, window_used: 30, computed_at: "x" },
  ],
  volatility_regimes: [],
  cointegration: [
    {
      asset_a: "GOLD", asset_b: "SILVER", timeframe_a: "24h", timeframe_b: "24h",
      pvalue: 0.5064, cointegrated: false, window_used: 200,
      note: "Not cointegrated at 95% confidence over this window. Descriptive statistic, not a trading signal.",
      computed_at: "x",
    },
  ],
  lead_lag: [
    { asset: "BNB", benchmark: "BTC", timeframe: "12h", best_lag: null, correlation: null, window_used: 0, note: "No BTC candle file shares this asset's timeframe (12h).", computed_at: "x" },
  ],
};

describe("QuantPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("renders the correlation heatmap with mock data", async () => {
    mockFetchStrategies.mockResolvedValue(ROSTER);
    mockFetchQuantCrossAsset.mockResolvedValue(CROSS_ASSET);

    const jsx = await QuantPage();
    render(jsx);

    expect(screen.getByTestId("correlation-heatmap")).toBeInTheDocument();
    const cells = screen.getAllByTestId("heatmap-cell");
    const btcGold = cells.find((c) => c.getAttribute("data-row") === "BTC" && c.getAttribute("data-col") === "GOLD");
    expect(btcGold).toHaveTextContent("0.42");
  });

  it("renders the cointegration table", async () => {
    mockFetchStrategies.mockResolvedValue(ROSTER);
    mockFetchQuantCrossAsset.mockResolvedValue(CROSS_ASSET);

    const jsx = await QuantPage();
    render(jsx);

    expect(screen.getByTestId("cointegration-table")).toBeInTheDocument();
    expect(screen.getByText("0.5064")).toBeInTheDocument();
    expect(screen.getByText(/GOLD \(24h\) \/ SILVER \(24h\)/)).toBeInTheDocument();
  });

  it("renders the lead-lag table", async () => {
    mockFetchStrategies.mockResolvedValue(ROSTER);
    mockFetchQuantCrossAsset.mockResolvedValue(CROSS_ASSET);

    const jsx = await QuantPage();
    render(jsx);

    expect(screen.getByTestId("lead-lag-table")).toBeInTheDocument();
    expect(screen.getByText("BNB")).toBeInTheDocument();
  });

  it("shows a graceful unavailable message when quant_cross_asset.json hasn't been exported yet", async () => {
    mockFetchStrategies.mockResolvedValue(ROSTER);
    mockFetchQuantCrossAsset.mockResolvedValue(null);

    const jsx = await QuantPage();
    render(jsx);

    expect(screen.getByTestId("quant-page-unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("cointegration-empty")).toBeInTheDocument();
    expect(screen.getByTestId("lead-lag-empty")).toBeInTheDocument();
  });

  it("never renders a composite/overall score anywhere on the page", async () => {
    mockFetchStrategies.mockResolvedValue(ROSTER);
    mockFetchQuantCrossAsset.mockResolvedValue(CROSS_ASSET);

    const jsx = await QuantPage();
    const { container } = render(jsx);

    expect(screen.queryByText(/overall score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/composite/i)).not.toBeInTheDocument();
    expect(container.innerHTML.toLowerCase()).not.toContain("quantconsensus");
  });
});
