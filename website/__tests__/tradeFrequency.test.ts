import { computeTradeFrequency } from "@/lib/tradeFrequency";
import type { LedgerRow } from "@/lib/types";

function row(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-08-01T00:00:00+00:00",
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    asset: "GOLD",
    signal_type: "NO_TRADE",
    entry_price: null,
    exit_price: null,
    reasoning: "x",
    candle_timestamp: "2026-08-01T00:00:00+00:00",
    ...overrides,
  };
}

describe("computeTradeFrequency", () => {
  it("reports zero real trades honestly, never a fabricated rate, when only NO_TRADE rows exist", () => {
    // Real shape: BREAKOUT_MOMENTUM/GOLD has 2 real NO_TRADE ledger rows and
    // zero ENTRY rows as of 2026-08-07.
    const rows = [
      row({ timestamp: "2026-07-31T01:06:07+00:00" }),
      row({ timestamp: "2026-08-07T00:11:18+00:00" }),
    ];
    const result = computeTradeFrequency(rows, "BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD");
    expect(result.entryCount).toBe(0);
    expect(result.ratePerYear).toBeNull();
    expect(result.sinceIso).toBe("2026-07-31T01:06:07+00:00");
  });

  it("reports a real count without computing a rate from a single entry", () => {
    const rows = [row(), row({ signal_type: "ENTRY", timestamp: "2026-08-05T00:00:00+00:00" })];
    const result = computeTradeFrequency(rows, "BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD");
    expect(result.entryCount).toBe(1);
    expect(result.ratePerYear).toBeNull();
  });

  it("computes a real annualized rate from 2+ real entries, matching independent arithmetic", () => {
    // Real shape (ORDERFLOW_IMBALANCE/BTC, verified independently against
    // docs/site_data/ledger_full.json as of 2026-08-07): 2 entries ~9 days
    // apart -> a real, disclosed short-window annualization.
    const rows = [
      row({ strategy: "ORDERFLOW_IMBALANCE", strategy_version: "orderflow-imbalance-v1.0.0", asset: "BTC", signal_type: "ENTRY", timestamp: "2026-07-29T14:28:20+00:00" }),
      row({ strategy: "ORDERFLOW_IMBALANCE", strategy_version: "orderflow-imbalance-v1.0.0", asset: "BTC", signal_type: "ENTRY", timestamp: "2026-08-07T16:06:11+00:00" }),
    ];
    const result = computeTradeFrequency(rows, "ORDERFLOW_IMBALANCE", "orderflow-imbalance-v1.0.0", "BTC");
    expect(result.entryCount).toBe(2);
    expect(result.spanDays).not.toBeNull();
    expect(result.spanDays!).toBeCloseTo(9.068, 2);
    expect(result.ratePerYear!).toBeCloseTo((2 / 9.068) * 365.25, 0);
  });

  it("never mixes a different strategy/version/asset's rows into the count", () => {
    const rows = [
      row({ signal_type: "ENTRY" }),
      row({ signal_type: "ENTRY", asset: "SILVER", strategy_version: "breakout-momentum-v1.6.0-silver-calibrated-24h" }),
      row({ signal_type: "ENTRY", strategy: "TREND_PULLBACK", strategy_version: "trend-pullback-v1.0.0", asset: "BNB" }),
    ];
    const result = computeTradeFrequency(rows, "BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD");
    expect(result.entryCount).toBe(1);
  });

  it("returns an honest null sinceIso when no ledger row exists at all for this strategy", () => {
    const result = computeTradeFrequency([], "BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD");
    expect(result.sinceIso).toBeNull();
    expect(result.entryCount).toBe(0);
  });
});
