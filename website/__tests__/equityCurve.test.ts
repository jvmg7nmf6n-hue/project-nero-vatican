import { buildEquityCurve } from "@/lib/equityCurve";
import type { ResolvedTrade } from "@/lib/tradeHistory";

function makeTrade(overrides: Partial<ResolvedTrade> = {}): ResolvedTrade {
  return {
    entryTimestamp: "t1",
    entryPrice: 100,
    exitTimestamp: "t2",
    exitPrice: 110,
    result: "win",
    rMultiple: 1,
    ...overrides,
  };
}

describe("buildEquityCurve", () => {
  it("returns an empty curve for zero trades", () => {
    const curve = buildEquityCurve([]);
    expect(curve.points).toEqual([]);
  });

  it("uses r_multiple units when every trade has one, in chronological cumulative order", () => {
    // buildTradeHistory's own convention: newest-first input.
    const trades = [
      makeTrade({ rMultiple: 2, result: "win" }), // newest
      makeTrade({ rMultiple: -1, result: "loss" }), // oldest
    ];

    const curve = buildEquityCurve(trades);

    expect(curve.unit).toBe("r_multiple");
    expect(curve.points).toEqual([
      { index: 1, cumulativeValue: -1, tradeResult: "loss" },
      { index: 2, cumulativeValue: 1, tradeResult: "win" },
    ]);
  });

  it("falls back to pct_return when any trade lacks an r_multiple", () => {
    const trades = [
      makeTrade({ rMultiple: null, entryPrice: 100, exitPrice: 105, result: "win" }),
      makeTrade({ rMultiple: 1, entryPrice: 50, exitPrice: 55, result: "win" }),
    ];

    const curve = buildEquityCurve(trades);

    expect(curve.unit).toBe("pct_return");
  });

  it("computes cumulative pct_return correctly from entry/exit prices", () => {
    const trades = [
      makeTrade({ rMultiple: null, entryPrice: 200, exitPrice: 190, result: "loss" }), // -5%, newest
      makeTrade({ rMultiple: null, entryPrice: 100, exitPrice: 110, result: "win" }), // +10%, oldest
    ];

    const curve = buildEquityCurve(trades);

    expect(curve.points[0].cumulativeValue).toBeCloseTo(10);
    expect(curve.points[1].cumulativeValue).toBeCloseTo(5);
  });

  it("treats a pct_return trade with a null entry or exit price as a zero-value step", () => {
    const trades = [makeTrade({ rMultiple: null, entryPrice: null, exitPrice: 110 })];
    const curve = buildEquityCurve(trades);
    expect(curve.points[0].cumulativeValue).toBe(0);
  });

  it("assigns sequential 1-based indices", () => {
    const trades = [makeTrade(), makeTrade(), makeTrade()];
    const curve = buildEquityCurve(trades);
    expect(curve.points.map((p) => p.index)).toEqual([1, 2, 3]);
  });
});
