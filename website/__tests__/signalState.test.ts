import { deriveSignalState, SIGNAL_STATE_LABELS } from "@/lib/signalState";
import type { LedgerRow } from "@/lib/types";

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-26T12:00:00Z",
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    asset: "GOLD",
    signal_type: "ENTRY",
    entry_price: 100,
    exit_price: null,
    reasoning: "",
    candle_timestamp: "1752753600000",
    ...overrides,
  };
}

const ENTRY = { name: "BREAKOUT_MOMENTUM", asset: "GOLD" };

describe("deriveSignalState", () => {
  it("returns 'no_signal_yet' when there is no matching ledger row", () => {
    expect(deriveSignalState(ENTRY, [])).toBe("no_signal_yet");
  });

  it("returns 'entry' for the latest ENTRY row", () => {
    const rows = [makeRow({ signal_type: "ENTRY" })];
    expect(deriveSignalState(ENTRY, rows)).toBe("entry");
  });

  it("returns 'exit' for the latest EXIT row", () => {
    const rows = [makeRow({ signal_type: "EXIT" })];
    expect(deriveSignalState(ENTRY, rows)).toBe("exit");
  });

  it("returns 'watching' for the latest WATCH row", () => {
    const rows = [makeRow({ signal_type: "WATCH" })];
    expect(deriveSignalState(ENTRY, rows)).toBe("watching");
  });

  it("returns 'watching' for the latest NO_TRADE row", () => {
    const rows = [makeRow({ signal_type: "NO_TRADE" })];
    expect(deriveSignalState(ENTRY, rows)).toBe("watching");
  });

  it("only matches rows for the same strategy and asset", () => {
    const rows = [makeRow({ strategy: "TREND_PULLBACK", asset: "GOLD", signal_type: "ENTRY" })];
    expect(deriveSignalState(ENTRY, rows)).toBe("no_signal_yet");
  });

  it("uses the newest (first) matching row when several exist", () => {
    const rows = [
      makeRow({ signal_type: "EXIT", timestamp: "2026-07-26T00:00:00Z" }),
      makeRow({ signal_type: "ENTRY", timestamp: "2026-07-25T00:00:00Z" }),
    ];
    expect(deriveSignalState(ENTRY, rows)).toBe("exit");
  });
});

describe("SignalState labels", () => {
  it("has exactly one label for each of the 4 states", () => {
    const states = Object.keys(SIGNAL_STATE_LABELS) as (keyof typeof SIGNAL_STATE_LABELS)[];
    expect(states).toEqual(["entry", "exit", "watching", "no_signal_yet"]);
  });

  it("labels no_signal_yet as 'NO SIGNAL YET'", () => {
    expect(SIGNAL_STATE_LABELS.no_signal_yet).toBe("NO SIGNAL YET");
  });

  it("labels watching as 'WATCHING'", () => {
    expect(SIGNAL_STATE_LABELS.watching).toBe("WATCHING");
  });
});
