import { deriveCurrentStatus, NO_SIGNAL_YET } from "@/lib/status";
import type { LedgerRow } from "@/lib/types";

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-17T12:00:00Z",
    strategy: "BREAKOUT_MOMENTUM",
    asset: "GOLD",
    signal_type: "ENTRY",
    entry_price: 100,
    exit_price: null,
    reasoning: "",
    candle_timestamp: "1752753600000",
    ...overrides,
  };
}

describe("deriveCurrentStatus", () => {
  it("returns NO_SIGNAL_YET when there is no match", () => {
    const status = deriveCurrentStatus(
      { name: "BREAKOUT_MOMENTUM", asset: "GOLD" },
      []
    );
    expect(status).toBe(NO_SIGNAL_YET);
  });

  it("returns the signal_type of the first (newest) matching row", () => {
    const rows = [
      makeRow({ signal_type: "EXIT", timestamp: "2026-07-18T00:00:00Z" }),
      makeRow({ signal_type: "ENTRY", timestamp: "2026-07-17T00:00:00Z" }),
    ];
    const status = deriveCurrentStatus(
      { name: "BREAKOUT_MOMENTUM", asset: "GOLD" },
      rows
    );
    expect(status).toBe("EXIT");
  });

  it("only matches rows with the same strategy and asset", () => {
    const rows = [
      makeRow({ strategy: "TREND_PULLBACK", asset: "GOLD", signal_type: "ENTRY" }),
      makeRow({ strategy: "BREAKOUT_MOMENTUM", asset: "BNB", signal_type: "ENTRY" }),
    ];
    const status = deriveCurrentStatus(
      { name: "BREAKOUT_MOMENTUM", asset: "GOLD" },
      rows
    );
    expect(status).toBe(NO_SIGNAL_YET);
  });

  it("returns NO_SIGNAL_YET for a roster pair never logged", () => {
    const rows = [makeRow({ strategy: "COINTEGRATION_PAIRS", asset: "BTC-ETH" })];
    const status = deriveCurrentStatus({ name: "NEWS_SENTIMENT", asset: "BTC" }, rows);
    expect(status).toBe(NO_SIGNAL_YET);
  });
});
