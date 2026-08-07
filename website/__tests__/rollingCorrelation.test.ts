import {
  alignAndComputeReturns,
  computeCorrelationFrames,
  computeLogReturns,
  pearsonCorrelation,
} from "@/lib/rollingCorrelation";
import type { Candle } from "@/lib/candleData";

function candle(time: number, close: number): Candle {
  return { time, open: close, high: close, low: close, close, volume: 100 };
}

describe("computeLogReturns", () => {
  it("computes ln(close[i]/close[i-1])", () => {
    const returns = computeLogReturns([100, 110, 99]);
    expect(returns[0]).toBeCloseTo(Math.log(1.1), 10);
    expect(returns[1]).toBeCloseTo(Math.log(99 / 110), 10);
    expect(returns).toHaveLength(2);
  });
});

describe("pearsonCorrelation", () => {
  it("is 1 for perfectly correlated series", () => {
    expect(pearsonCorrelation([1, 2, 3, 4], [2, 4, 6, 8])).toBeCloseTo(1, 10);
  });

  it("is -1 for perfectly anti-correlated series", () => {
    expect(pearsonCorrelation([1, 2, 3, 4], [8, 6, 4, 2])).toBeCloseTo(-1, 10);
  });

  it("is null when either series has zero variance", () => {
    expect(pearsonCorrelation([1, 1, 1], [1, 2, 3])).toBeNull();
  });
});

describe("alignAndComputeReturns", () => {
  it("aligns on real shared timestamps only, never positionally", () => {
    const candlesByAsset: Record<string, Candle[]> = {
      A: [candle(1, 100), candle(2, 110), candle(3, 121)],
      // B is missing time=2 entirely -- must not shift B's other values into that slot.
      B: [candle(1, 50), candle(3, 55)],
    };
    const { times, returnsByAsset } = alignAndComputeReturns(candlesByAsset);
    expect(times).toEqual([3]); // only time=3 has a return computable from the shared {1,3} grid
    expect(returnsByAsset.A[0]).toBeCloseTo(Math.log(121 / 100), 10);
    expect(returnsByAsset.B[0]).toBeCloseTo(Math.log(55 / 50), 10);
  });

  it("returns empty when there is no shared timestamp grid", () => {
    const candlesByAsset: Record<string, Candle[]> = {
      A: [candle(1, 100)],
      B: [candle(2, 50)],
    };
    const { times } = alignAndComputeReturns(candlesByAsset);
    expect(times).toEqual([]);
  });
});

describe("computeCorrelationFrames", () => {
  function makeTrendingCandles(n: number, start: number, slope: number, seed: number): Candle[] {
    const out: Candle[] = [];
    let value = start;
    for (let i = 0; i < n; i++) {
      // deterministic pseudo-noise, no Math.random (repo convention: no randomness in tests)
      const noise = Math.sin(i * seed) * 0.5;
      value += slope + noise;
      out.push(candle(i, value));
    }
    return out;
  }

  it("computes real, non-null frames once enough aligned history exists", () => {
    const candlesByAsset = {
      X: makeTrendingCandles(60, 100, 1, 0.3),
      Y: makeTrendingCandles(60, 200, 1.2, 0.31), // similar trend -> should correlate positively
    };
    const frames = computeCorrelationFrames(candlesByAsset, ["X", "Y"], 30, 4);
    expect(frames.length).toBeGreaterThan(0);
    for (const frame of frames) {
      expect(frame.matrix[0][0]).toBe(1); // self-correlation
      expect(frame.matrix[0][1]).not.toBeNull();
      expect(frame.matrix[0][1]).toBeGreaterThan(0); // both series trend up together
    }
  });

  it("returns [] when there isn't even one full window of aligned history", () => {
    const candlesByAsset = {
      X: makeTrendingCandles(10, 100, 1, 0.3),
      Y: makeTrendingCandles(10, 200, 1, 0.3),
    };
    expect(computeCorrelationFrames(candlesByAsset, ["X", "Y"], 30, 4)).toEqual([]);
  });

  it("frame timestamps are real, strictly increasing, and never fabricated between real points", () => {
    const candlesByAsset = {
      X: makeTrendingCandles(100, 100, 1, 0.3),
      Y: makeTrendingCandles(100, 200, 1, 0.31),
    };
    const frames = computeCorrelationFrames(candlesByAsset, ["X", "Y"], 30, 5);
    const times = frames.map((f) => f.time);
    const sorted = [...times].sort((a, b) => a - b);
    expect(times).toEqual(sorted);
    expect(new Set(times).size).toBe(times.length); // no duplicate frames
    for (const t of times) {
      expect(Number.isInteger(t)).toBe(true);
    }
  });
});
