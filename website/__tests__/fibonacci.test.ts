import { computeFibRetracementLevels, makeTrendLine } from "@/lib/fibonacci";

describe("computeFibRetracementLevels", () => {
  it("computes standard ratio levels between a swing high and low", () => {
    const levels = computeFibRetracementLevels(200, 100);
    const byRatio = Object.fromEntries(levels.map((l) => [l.ratio, l.price]));
    expect(byRatio[0]).toBe(200);
    expect(byRatio[1]).toBe(100);
    expect(byRatio[0.5]).toBe(150);
    expect(byRatio[0.618]).toBeCloseTo(200 - 100 * 0.618, 6);
  });
});

describe("makeTrendLine", () => {
  it("is just its two endpoints", () => {
    const line = makeTrendLine({ time: 1, price: 10 }, { time: 5, price: 20 });
    expect(line).toEqual({ start: { time: 1, price: 10 }, end: { time: 5, price: 20 } });
  });
});
