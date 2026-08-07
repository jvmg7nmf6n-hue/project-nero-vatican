import { render, screen } from "@testing-library/react";
import SignalsPage from "@/app/signals/page";
import * as data from "@/lib/data";
import type { CandleFile } from "@/lib/candleData";
import type { TrialEntriesExport, TrialEntry } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchTrialEntries = jest.mocked(data.fetchTrialEntries);
const mockFetchCandleData = jest.mocked(data.fetchCandleData);

function entry(overrides: Partial<TrialEntry> = {}): TrialEntry {
  return {
    execution_log_id: 1,
    trial_id: "abc123",
    hypothesis_name: "ETH_BIDIRECTIONAL_ZSCORE_FADE",
    origin_agent: "eve",
    asset: "ETH",
    timeframe: "4h",
    direction: "SHORT",
    entry_price: 1916.6466,
    stop_loss: 1951.9973,
    target: 1881.2959,
    timestamp: "2026-08-05T23:07:36.307597+00:00",
    candle_timestamp: 1785959999999,
    ...overrides,
  };
}

const CANDLE_FILE: CandleFile = {
  schema_version: 1,
  asset: "ETH",
  timeframe: "4h",
  last_updated: "x",
  candles: [{ time: 1785959999, open: 1900, high: 1920, low: 1890, close: 1916, volume: 100 }],
};

describe("SignalsPage", () => {
  afterEach(() => {
    // clearAllMocks (not resetAllMocks): resetAllMocks would also wipe the
    // lightweight-charts manual mock's default factory implementation
    // (__mocks__/lightweight-charts.ts's createChart jest.fn(() => ({...})),
    // set up once at module load and never re-established per test) --
    // confirmed directly: with resetAllMocks, the 3rd test in this file
    // (the first to actually render a chart) got `createChart(...)` back as
    // `undefined` because the 1st test's afterEach had already reset it.
    jest.clearAllMocks();
  });

  it("shows an honest empty state when no entries exist", async () => {
    mockFetchTrialEntries.mockResolvedValue({ schema_version: 1, last_updated: "x", entries: [] });
    render(await SignalsPage());
    expect(screen.getByTestId("signals-empty")).toBeInTheDocument();
  });

  it("shows an honest empty state when the export hasn't run yet", async () => {
    mockFetchTrialEntries.mockResolvedValue(null);
    render(await SignalsPage());
    expect(screen.getByTestId("signals-empty")).toBeInTheDocument();
  });

  it("renders a real entry with its chart", async () => {
    const trialExport: TrialEntriesExport = { schema_version: 1, last_updated: "x", entries: [entry()] };
    mockFetchTrialEntries.mockResolvedValue(trialExport);
    mockFetchCandleData.mockResolvedValue({ status: "ok", data: CANDLE_FILE });

    render(await SignalsPage());

    expect(screen.getByText("ETH_BIDIRECTIONAL_ZSCORE_FADE")).toBeInTheDocument();
    expect(screen.getByText("SHORT")).toBeInTheDocument();
    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
    expect(mockFetchCandleData).toHaveBeenCalledWith("ETH", "4h");
  });

  it("shows a chart-unavailable message when no candle data exists for this asset/timeframe", async () => {
    const trialExport: TrialEntriesExport = { schema_version: 1, last_updated: "x", entries: [entry()] };
    mockFetchTrialEntries.mockResolvedValue(trialExport);
    mockFetchCandleData.mockResolvedValue({ status: "not_found" });

    render(await SignalsPage());

    expect(screen.getByTestId("signal-chart-unavailable")).toBeInTheDocument();
  });

  it("most recent entry renders first", async () => {
    const older = entry({ execution_log_id: 1, hypothesis_name: "OLDER_ONE", timestamp: "2026-08-01T00:00:00Z" });
    const newer = entry({ execution_log_id: 2, hypothesis_name: "NEWER_ONE", timestamp: "2026-08-06T00:00:00Z" });
    mockFetchTrialEntries.mockResolvedValue({ schema_version: 1, last_updated: "x", entries: [older, newer] });
    mockFetchCandleData.mockResolvedValue({ status: "not_found" });

    render(await SignalsPage());

    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings[0]).toBe("NEWER_ONE");
    expect(headings[1]).toBe("OLDER_ONE");
  });
});
