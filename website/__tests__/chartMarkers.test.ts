import { buildChartMarkers } from "@/lib/chartMarkers";
import type { Candle } from "@/lib/candleData";
import type { ResolvedTrade } from "@/lib/tradeHistory";

function makeCandle(time: number): Candle {
  return { time, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 };
}

function makeTrade(overrides: Partial<ResolvedTrade> = {}): ResolvedTrade {
  return {
    entryTimestamp: "2026-01-02T00:00:00Z",
    entryPrice: 100,
    exitTimestamp: "2026-01-03T00:00:00Z",
    exitPrice: 110,
    result: "win",
    rMultiple: 1.5,
    ...overrides,
  };
}

// Candle window spanning 2026-01-01 through 2026-01-10 (Unix seconds).
const CANDLES: Candle[] = [
  makeCandle(Math.floor(new Date("2026-01-01T00:00:00Z").getTime() / 1000)),
  makeCandle(Math.floor(new Date("2026-01-10T00:00:00Z").getTime() / 1000)),
];

describe("buildChartMarkers", () => {
  it("returns an empty array when there are no candles", () => {
    expect(buildChartMarkers([makeTrade()], [])).toEqual([]);
  });

  it("returns an empty array when there are no trades", () => {
    expect(buildChartMarkers([], CANDLES)).toEqual([]);
  });

  it("builds an ENTRY marker (teal, arrowUp, belowBar) and a WIN EXIT marker (teal, arrowDown, aboveBar)", () => {
    const markers = buildChartMarkers([makeTrade({ result: "win" })], CANDLES);

    expect(markers).toHaveLength(2);
    const [entry, exit] = markers;
    expect(entry).toMatchObject({ position: "belowBar", color: "#2ec4b6", shape: "arrowUp", text: "ENTRY" });
    expect(exit).toMatchObject({ position: "aboveBar", color: "#2ec4b6", shape: "arrowDown", text: "EXIT" });
  });

  it("colors a losing EXIT loss-red", () => {
    const markers = buildChartMarkers([makeTrade({ result: "loss" })], CANDLES);
    const exit = markers.find((m) => m.text === "EXIT");
    expect(exit?.color).toBe("#d47a6a");
  });

  it("colors a flat EXIT a neutral muted color rather than guessing win or loss", () => {
    const markers = buildChartMarkers([makeTrade({ result: "flat" })], CANDLES);
    const exit = markers.find((m) => m.text === "EXIT");
    expect(exit?.color).toBe("#8a94ad");
  });

  it("excludes a trade whose entry timestamp falls before the visible candle window, without erroring", () => {
    const trade = makeTrade({ entryTimestamp: "2020-01-01T00:00:00Z" });
    expect(() => buildChartMarkers([trade], CANDLES)).not.toThrow();
    const markers = buildChartMarkers([trade], CANDLES);
    expect(markers.some((m) => m.text === "ENTRY")).toBe(false);
    // The exit (within range) is still included independently.
    expect(markers.some((m) => m.text === "EXIT")).toBe(true);
  });

  it("excludes a trade whose exit timestamp falls after the visible candle window, without erroring", () => {
    const trade = makeTrade({ exitTimestamp: "2030-01-01T00:00:00Z" });
    expect(() => buildChartMarkers([trade], CANDLES)).not.toThrow();
    const markers = buildChartMarkers([trade], CANDLES);
    expect(markers.some((m) => m.text === "EXIT")).toBe(false);
    expect(markers.some((m) => m.text === "ENTRY")).toBe(true);
  });

  it("drops a trade entirely when both timestamps are out of range", () => {
    const trade = makeTrade({ entryTimestamp: "2020-01-01T00:00:00Z", exitTimestamp: "2030-01-01T00:00:00Z" });
    expect(buildChartMarkers([trade], CANDLES)).toEqual([]);
  });

  it("returns markers sorted ascending by time, even when trades are passed newest-first", () => {
    const older = makeTrade({ entryTimestamp: "2026-01-02T00:00:00Z", exitTimestamp: "2026-01-03T00:00:00Z" });
    const newer = makeTrade({ entryTimestamp: "2026-01-05T00:00:00Z", exitTimestamp: "2026-01-06T00:00:00Z" });
    // buildTradeHistory's own convention: newest-first input.
    const markers = buildChartMarkers([newer, older], CANDLES);
    const times = markers.map((m) => m.time);
    expect(times).toEqual([...times].sort((a, b) => a - b));
  });
});
