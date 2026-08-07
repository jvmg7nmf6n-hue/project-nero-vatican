import { computeBollingerBands, computeEMA, computeSMA, computeVWAP } from "@/lib/indicators";
import type { Candle } from "@/lib/candleData";

function candle(time: number, close: number, volume: number | null = 100): Candle {
  return { time, open: close, high: close, low: close, close, volume };
}

describe("computeSMA", () => {
  it("returns the plain average over the window", () => {
    const candles = [1, 2, 3, 4, 5].map((c, i) => candle(i, c));
    const sma = computeSMA(candles, 3);
    // First value available at index 2: avg(1,2,3) = 2
    expect(sma[0]).toEqual({ time: 2, value: 2 });
    // avg(2,3,4) = 3
    expect(sma[1]).toEqual({ time: 3, value: 3 });
    // avg(3,4,5) = 4
    expect(sma[2]).toEqual({ time: 4, value: 4 });
    expect(sma).toHaveLength(3);
  });

  it("returns empty when there are fewer candles than the period", () => {
    const candles = [1, 2].map((c, i) => candle(i, c));
    expect(computeSMA(candles, 5)).toEqual([]);
  });
});

describe("computeEMA", () => {
  it("seeds on the first close then applies the smoothing formula", () => {
    const candles = [10, 12, 14].map((c, i) => candle(i, c));
    const ema = computeEMA(candles, 2); // k = 2/3
    expect(ema[0].value).toBeCloseTo(10, 6);
    // ema1 = 12 * (2/3) + 10 * (1/3) = 11.333...
    expect(ema[1].value).toBeCloseTo(11.3333333, 5);
    // ema2 = 14 * (2/3) + 11.333.. * (1/3)
    expect(ema[2].value).toBeCloseTo(13.1111111, 5);
  });

  it("one point per candle, no warmup gap unlike SMA", () => {
    const candles = [1, 2, 3].map((c, i) => candle(i, c));
    expect(computeEMA(candles, 20)).toHaveLength(3);
  });
});

describe("computeBollingerBands", () => {
  it("middle band equals SMA, upper/lower are mean +/- k*stdev", () => {
    const closes = [10, 12, 14, 12, 10];
    const candles = closes.map((c, i) => candle(i, c));
    const bb = computeBollingerBands(candles, 5, 2);
    const mean = closes.reduce((a, b) => a + b, 0) / closes.length;
    const variance = closes.reduce((sum, c) => sum + (c - mean) ** 2, 0) / closes.length;
    const stdev = Math.sqrt(variance);
    expect(bb.middle[0].value).toBeCloseTo(mean, 6);
    expect(bb.upper[0].value).toBeCloseTo(mean + 2 * stdev, 6);
    expect(bb.lower[0].value).toBeCloseTo(mean - 2 * stdev, 6);
  });

  it("returns empty arrays when there's not enough data", () => {
    const candles = [candle(0, 1), candle(1, 2)];
    expect(computeBollingerBands(candles, 20, 2)).toEqual({ upper: [], middle: [], lower: [] });
  });
});

describe("computeVWAP", () => {
  it("computes cumulative typical-price-weighted average", () => {
    const candles: Candle[] = [
      { time: 0, open: 10, high: 12, low: 8, close: 10, volume: 100 }, // typical = 10
      { time: 1, open: 10, high: 14, low: 10, close: 12, volume: 200 }, // typical = 12
    ];
    const vwap = computeVWAP(candles);
    expect(vwap[0].value).toBeCloseTo(10, 6); // cumPV=1000, cumV=100 -> 10
    // cumPV = 1000 + 12*200 = 3400, cumV = 300 -> 11.333..
    expect(vwap[1].value).toBeCloseTo(11.3333333, 5);
  });

  it("returns [] (never a fabricated line) when any candle has null volume", () => {
    const candles: Candle[] = [
      { time: 0, open: 10, high: 12, low: 8, close: 10, volume: 100 },
      { time: 1, open: 10, high: 14, low: 10, close: 12, volume: null },
    ];
    expect(computeVWAP(candles)).toEqual([]);
  });
});
