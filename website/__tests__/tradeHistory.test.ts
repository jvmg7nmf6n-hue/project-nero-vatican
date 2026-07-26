import { buildTradeHistory } from "@/lib/tradeHistory";
import type { LedgerRow } from "@/lib/types";

const ENTRY = { name: "BREAKOUT_MOMENTUM", version: "breakout-momentum-v1.2.0-gold-calibrated-1week", asset: "GOLD" };

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-01T00:00:00Z",
    strategy: ENTRY.name,
    strategy_version: ENTRY.version,
    asset: ENTRY.asset,
    signal_type: "ENTRY",
    entry_price: 100,
    exit_price: null,
    reasoning: "",
    candle_timestamp: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("buildTradeHistory", () => {
  it("returns an empty list when there are no ledger rows at all", () => {
    expect(buildTradeHistory(ENTRY, [])).toEqual([]);
  });

  it("pairs one ENTRY with the following EXIT into a resolved trade", () => {
    const rows = [
      makeRow({ signal_type: "ENTRY", entry_price: 100, candle_timestamp: "2026-07-01T00:00:00Z", timestamp: "t1" }),
      makeRow({
        signal_type: "EXIT", exit_price: 110, entry_price: null,
        candle_timestamp: "2026-07-02T00:00:00Z", timestamp: "t2",
        reasoning: "TARGET exit, r_multiple=1.500, net_pnl=50.00",
      }),
    ];

    const trades = buildTradeHistory(ENTRY, rows);

    expect(trades).toHaveLength(1);
    expect(trades[0]).toEqual({
      entryTimestamp: "t1",
      entryPrice: 100,
      exitTimestamp: "t2",
      exitPrice: 110,
      result: "win",
      rMultiple: 1.5,
    });
  });

  it("labels a negative r_multiple exit as a loss", () => {
    const rows = [
      makeRow({ signal_type: "ENTRY", entry_price: 100, candle_timestamp: "2026-07-01T00:00:00Z" }),
      makeRow({
        signal_type: "EXIT", exit_price: 90,
        candle_timestamp: "2026-07-02T00:00:00Z",
        reasoning: "SL exit, r_multiple=-1.020, net_pnl=-90.00",
      }),
    ];

    const trades = buildTradeHistory(ENTRY, rows);

    expect(trades[0].result).toBe("loss");
    expect(trades[0].rMultiple).toBe(-1.02);
  });

  it("falls back to comparing entry/exit price when reasoning has no r_multiple (e.g. COINTEGRATION_PAIRS)", () => {
    const rows = [
      makeRow({ signal_type: "ENTRY", entry_price: 100, candle_timestamp: "2026-07-01T00:00:00Z", reasoning: "|z|=2.1" }),
      makeRow({ signal_type: "EXIT", exit_price: 105, candle_timestamp: "2026-07-02T00:00:00Z", reasoning: "z reverted" }),
    ];

    const trades = buildTradeHistory(ENTRY, rows);

    expect(trades[0].rMultiple).toBeNull();
    expect(trades[0].result).toBe("win");
  });

  it("does not count a trailing unpaired ENTRY as a resolved trade (open position)", () => {
    const rows = [
      makeRow({ signal_type: "ENTRY", entry_price: 100, candle_timestamp: "2026-07-01T00:00:00Z" }),
      makeRow({ signal_type: "EXIT", exit_price: 110, candle_timestamp: "2026-07-02T00:00:00Z" }),
      makeRow({ signal_type: "ENTRY", entry_price: 120, candle_timestamp: "2026-07-03T00:00:00Z" }),
    ];

    const trades = buildTradeHistory(ENTRY, rows);

    expect(trades).toHaveLength(1);
  });

  it("skips an orphaned leading EXIT with no preceding ENTRY, rather than fabricating a trade", () => {
    const rows = [
      makeRow({ signal_type: "EXIT", exit_price: 110, candle_timestamp: "2026-07-01T00:00:00Z" }),
      makeRow({ signal_type: "ENTRY", entry_price: 100, candle_timestamp: "2026-07-02T00:00:00Z" }),
      makeRow({ signal_type: "EXIT", exit_price: 120, candle_timestamp: "2026-07-03T00:00:00Z" }),
    ];

    const trades = buildTradeHistory(ENTRY, rows);

    expect(trades).toHaveLength(1);
    expect(trades[0].exitPrice).toBe(120);
  });

  it("only includes rows matching this exact (strategy, version, asset)", () => {
    const rows = [
      makeRow({ signal_type: "ENTRY", strategy_version: "some-other-version" }),
      makeRow({ signal_type: "EXIT", strategy_version: "some-other-version" }),
    ];

    expect(buildTradeHistory(ENTRY, rows)).toEqual([]);
  });

  it("returns trades newest-first", () => {
    const rows = [
      makeRow({ signal_type: "ENTRY", entry_price: 100, candle_timestamp: "2026-07-01T00:00:00Z", timestamp: "entry1" }),
      makeRow({ signal_type: "EXIT", exit_price: 110, candle_timestamp: "2026-07-02T00:00:00Z", timestamp: "exit1" }),
      makeRow({ signal_type: "ENTRY", entry_price: 120, candle_timestamp: "2026-07-03T00:00:00Z", timestamp: "entry2" }),
      makeRow({ signal_type: "EXIT", exit_price: 130, candle_timestamp: "2026-07-04T00:00:00Z", timestamp: "exit2" }),
    ];

    const trades = buildTradeHistory(ENTRY, rows);

    expect(trades).toHaveLength(2);
    expect(trades[0].exitTimestamp).toBe("exit2");
    expect(trades[1].exitTimestamp).toBe("exit1");
  });
});
