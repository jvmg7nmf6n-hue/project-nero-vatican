import { render, screen } from "@testing-library/react";
import MacroPage from "@/app/macro/page";
import * as data from "@/lib/data";
import type { MacroConflictFlagRecord, MacroReadRecord, MacroReadsExport } from "@/lib/types";

jest.mock("@/lib/data");

const mockFetchMacroReads = jest.mocked(data.fetchMacroReads);

function goldRead(overrides: Partial<MacroReadRecord> = {}): MacroReadRecord {
  return {
    run_id: "r1",
    timestamp: "2026-08-07T04:07:42Z",
    asset: "GOLD",
    bias: "BEARISH",
    confidence: 0.477,
    agreement: 0.5,
    coverage: 0.113,
    probability_up: 0.25,
    provenance_breakdown: {
      monetary_policy: "real",
      learning: "real",
      liquidity: "mixed",
      news_intelligence: "synthetic",
    },
    reasoning: "GOLD bearish reasoning text",
    risks: [],
    alternative_scenarios: [
      { name: "Base case", probability: 0.5, gold_bias: "BEARISH", btc_bias: "STRONG_BULLISH", narrative: "x" },
    ],
    data_mode: "live",
    ...overrides,
  };
}

function btcRead(overrides: Partial<MacroReadRecord> = {}): MacroReadRecord {
  return { ...goldRead(overrides), asset: "BITCOIN", bias: "STRONG_BULLISH", agreement: 1.0, coverage: 0.244 };
}

const FLAG: MacroConflictFlagRecord = {
  execution_log_id: 1, macro_read_id: null, strategy: "ORDERFLOW_IMBALANCE", asset: "BTC",
  entry_direction: "SHORT", conflicted: false, status: "insufficient_data",
  reason: "no macro read exists prior to this entry's timestamp", evaluated_at: "x",
};

describe("MacroPage", () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it("shows an honest empty state when no macro reads exist", async () => {
    mockFetchMacroReads.mockResolvedValue(null);
    render(await MacroPage());
    expect(screen.getByTestId("macro-page-unavailable")).toBeInTheDocument();
  });

  it("renders real GOLD and BITCOIN reads with provenance and reasoning", async () => {
    const payload: MacroReadsExport = {
      schema_version: 1, last_updated: "x",
      macro_reads: [goldRead(), btcRead()],
      conflict_flags: [FLAG],
    };
    mockFetchMacroReads.mockResolvedValue(payload);

    render(await MacroPage());

    expect(screen.getAllByText("BEARISH").length).toBeGreaterThan(0);
    expect(screen.getAllByText("STRONG_BULLISH").length).toBeGreaterThan(0);
    // Provenance breakdown table is scoped to BTC and shows the real data source.
    expect(screen.getByText("FRED DFII10 (10y real yield, t+2 lag) + yfinance DX-Y.NYB (DXY)")).toBeInTheDocument();
    expect(screen.getByText(/GOLD bearish reasoning text|Bitcoin/)).toBeInTheDocument();
    expect(screen.getByText("Base case (50%)")).toBeInTheDocument();
  });

  it("shows a per-asset unavailable message when only one asset has a read", async () => {
    const payload: MacroReadsExport = {
      schema_version: 1, last_updated: "x", macro_reads: [goldRead()], conflict_flags: [],
    };
    mockFetchMacroReads.mockResolvedValue(payload);

    render(await MacroPage());

    expect(screen.getByTestId("macro-read-unavailable-BITCOIN")).toBeInTheDocument();
  });

  it("shows the sparse-history note with fewer than 5 cycles", async () => {
    const payload: MacroReadsExport = {
      schema_version: 1, last_updated: "x", macro_reads: [goldRead(), btcRead()], conflict_flags: [],
    };
    mockFetchMacroReads.mockResolvedValue(payload);

    render(await MacroPage());

    expect(screen.getByTestId("macro-history-sparse")).toBeInTheDocument();
  });

  it("shows an empty conflicts message when no BTC entries have been evaluated", async () => {
    const payload: MacroReadsExport = {
      schema_version: 1, last_updated: "x", macro_reads: [goldRead(), btcRead()], conflict_flags: [],
    };
    mockFetchMacroReads.mockResolvedValue(payload);

    render(await MacroPage());

    expect(screen.getByTestId("macro-conflicts-empty")).toBeInTheDocument();
  });
});
