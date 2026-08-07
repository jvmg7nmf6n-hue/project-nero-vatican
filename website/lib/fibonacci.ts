/**
 * CC-1 Part D2 — Fibonacci retracement + trend line, hand-rolled for the same
 * reason documented in lib/indicators.ts's own header: `lightweight-charts-
 * drawing@0.1.1` (the package this directive named for `FibRetracement` +
 * `TrendLine`) peer-depends on `lightweight-charts@^5.0.0`, incompatible with
 * this project's v4 pin -- confirmed via `npm view`, not assumed. Both
 * primitives here are simple enough (a handful of ratio multiplications; a
 * two-point line) that hand-rolling is a smaller, safer surface than
 * vendoring source from an 8-commit package specifically flagged for review
 * in the original directive, then having to adapt it to a different major
 * version of the underlying charting library anyway.
 */

export const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;

export interface FibLevel {
  ratio: number;
  price: number;
}

/**
 * Standard retracement levels between a swing high and swing low.
 * `high`/`low` must be an already-identified swing pair -- this function has
 * no opinion on how the swing was chosen, it only computes the ratio prices.
 */
export function computeFibRetracementLevels(high: number, low: number): FibLevel[] {
  const range = high - low;
  return FIB_RATIOS.map((ratio) => ({ ratio, price: high - range * ratio }));
}

export interface TrendLinePoint {
  time: number;
  price: number;
}

export interface TrendLine {
  start: TrendLinePoint;
  end: TrendLinePoint;
}

/** A trend line is just its two endpoints -- rendering hands this straight to lightweight-charts' own two-point line series. */
export function makeTrendLine(start: TrendLinePoint, end: TrendLinePoint): TrendLine {
  return { start, end };
}
