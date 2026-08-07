import { render, screen } from "@testing-library/react";
import LedgerPage from "@/app/ledger/page";
import * as data from "@/lib/data";
import type { LedgerExport, LedgerRow, SiteSummary } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchLedgerFull = jest.mocked(data.fetchLedgerFull);
const mockFetchSiteSummary = jest.mocked(data.fetchSiteSummary);

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-17T12:00:00Z",
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    asset: "GOLD",
    signal_type: "EXIT",
    entry_price: 100,
    exit_price: 90,
    reasoning: "Stop loss hit",
    candle_timestamp: "1752753600000",
    ...overrides,
  };
}

describe("LedgerPage", () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it("fetches the FULL ledger, not the recent-only export", async () => {
    mockFetchLedgerFull.mockResolvedValue({ schema_version: 1, last_updated: "x", rows: [makeRow()] });
    mockFetchSiteSummary.mockResolvedValue(null);

    render(await LedgerPage());

    expect(mockFetchLedgerFull).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("ledger-table")).toBeInTheDocument();
  });

  it("shows the tracking-since empty state when there are no real rows yet", async () => {
    mockFetchLedgerFull.mockResolvedValue(null);
    mockFetchSiteSummary.mockResolvedValue({
      configs_tested: 0,
      strategies_survived: 0,
      strategy_families_verified: 0,
      tracking_since: "2026-07-17",
      last_curated: "x",
    });

    render(await LedgerPage());

    const empty = screen.getByTestId("ledger-empty-state");
    expect(empty.textContent).toContain("2026-07-17");
  });

  it("renders the page title", async () => {
    mockFetchLedgerFull.mockResolvedValue({ schema_version: 1, last_updated: "x", rows: [] } as LedgerExport);
    mockFetchSiteSummary.mockResolvedValue(null);

    render(await LedgerPage());

    expect(screen.getByText("Truth Ledger")).toBeInTheDocument();
  });
});
