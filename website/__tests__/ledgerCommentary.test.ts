import { deriveLedgerCommentary } from "@/lib/ledgerCommentary";
import type { LedgerRow } from "@/lib/types";

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

describe("deriveLedgerCommentary", () => {
  it("computes a real negative percentage move for a losing EXIT row", () => {
    expect(deriveLedgerCommentary(makeRow({ entry_price: 100, exit_price: 90 }))).toBe(
      "-10.00% vs entry"
    );
  });

  it("computes a real positive percentage move for a winning EXIT row", () => {
    expect(deriveLedgerCommentary(makeRow({ entry_price: 100, exit_price: 110 }))).toBe(
      "+10.00% vs entry"
    );
  });

  it("returns an honest empty string for a non-EXIT row", () => {
    expect(
      deriveLedgerCommentary(makeRow({ signal_type: "ENTRY", exit_price: null }))
    ).toBe("");
    expect(
      deriveLedgerCommentary(makeRow({ signal_type: "NO_TRADE", exit_price: null }))
    ).toBe("");
    expect(
      deriveLedgerCommentary(makeRow({ signal_type: "WATCH", exit_price: null }))
    ).toBe("");
  });

  it("returns an honest empty string for an EXIT row missing either price", () => {
    expect(deriveLedgerCommentary(makeRow({ entry_price: null }))).toBe("");
    expect(deriveLedgerCommentary(makeRow({ exit_price: null }))).toBe("");
  });

  it("returns an honest empty string rather than dividing by zero", () => {
    expect(deriveLedgerCommentary(makeRow({ entry_price: 0, exit_price: 90 }))).toBe("");
  });
});
