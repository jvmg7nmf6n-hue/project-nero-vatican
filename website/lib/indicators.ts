import type { Candle } from "./candleData";

/**
 * CC-1 Part D2 — chart overlay indicators, hand-rolled rather than pulled from
 * `lightweight-charts-indicators`/`lightweight-charts-drawing` (deepentropy).
 *
 * FINDING (license/compat check, done before writing any of this): every
 * published version of `lightweight-charts-indicators` (up to 0.5.0) and
 * `lightweight-charts-drawing` (0.1.1) peer-depends on `oakscriptjs`, which in
 * turn requires `lightweight-charts@^5.0.0` for EVERY published version back
 * to 0.1.5 -- there is no version of either package compatible with this
 * project's existing `lightweight-charts@^4.2.0` pin (confirmed via `npm view
 * <pkg>@<version> peerDependencies` across the full version range, not
 * assumed). Forcing the install with `--legacy-peer-deps` would silently
 * accept a v4-chart-instance-fed-to-v5-oriented-code mismatch -- lightweight-
 * charts v5 changed series creation (`chart.addSeries(CandlestickSeries, ...)`
 * instead of v4's `chart.addCandlestickSeries(...)`) AND moved markers out of
 * the series API into a separate `createSeriesMarkers` primitive, which would
 * mean touching/rebuilding the exact `series.setMarkers` call this directive
 * explicitly says not to rebuild. Upgrading the whole project to v5 to unlock
 * two small indicator packages was judged the wrong trade for a
 * utility/display-only pass -- especially since every indicator asked for
 * (SMA/EMA/Bollinger Bands/VWAP) is a well-known, ~10-line formula, the exact
 * same reasoning the directive itself already applied to VWAP ("write it as a
 * custom ~10-line utility... don't pull it from the indicators package").
 * This file extends that same reasoning to every overlay, consistently.
 *
 * Every function here is pure (candles in, numeric series out) and takes only
 * ALREADY-CLOSED candles -- no lookahead, matching this codebase's own
 * standing rule.
 */

export interface LinePoint {
  time: number;
  value: number;
}

export function computeSMA(candles: Candle[], period: number): LinePoint[] {
  if (period <= 0 || candles.length < period) return [];
  const out: LinePoint[] = [];
  let windowSum = 0;
  for (let i = 0; i < candles.length; i++) {
    windowSum += candles[i].close;
    if (i >= period) windowSum -= candles[i - period].close;
    if (i >= period - 1) out.push({ time: candles[i].time, value: windowSum / period });
  }
  return out;
}

export function computeEMA(candles: Candle[], period: number): LinePoint[] {
  if (period <= 0 || candles.length === 0) return [];
  const k = 2 / (period + 1);
  const out: LinePoint[] = [];
  let prevEma: number | null = null;
  for (const candle of candles) {
    prevEma = prevEma === null ? candle.close : candle.close * k + prevEma * (1 - k);
    out.push({ time: candle.time, value: prevEma });
  }
  return out;
}

export interface BollingerBands {
  upper: LinePoint[];
  middle: LinePoint[];
  lower: LinePoint[];
}

/** Middle band = SMA(period); upper/lower = middle +/- stdDevMultiplier * rolling stdev. */
export function computeBollingerBands(
  candles: Candle[],
  period: number,
  stdDevMultiplier: number
): BollingerBands {
  const middle = computeSMA(candles, period);
  if (middle.length === 0) return { upper: [], middle: [], lower: [] };

  const upper: LinePoint[] = [];
  const lower: LinePoint[] = [];
  const offset = period - 1;
  for (let i = 0; i < middle.length; i++) {
    const windowCandles = candles.slice(offset + i - (period - 1), offset + i + 1);
    const mean = middle[i].value;
    const variance =
      windowCandles.reduce((sum, c) => sum + (c.close - mean) ** 2, 0) / windowCandles.length;
    const stdev = Math.sqrt(variance);
    upper.push({ time: middle[i].time, value: mean + stdDevMultiplier * stdev });
    lower.push({ time: middle[i].time, value: mean - stdDevMultiplier * stdev });
  }
  return { upper, middle, lower };
}

/**
 * VWAP = cumsum(price * volume) / cumsum(volume), the exact formula the
 * directive specifies -- cumulative over the whole visible candle series
 * (not session-reset), using typical price ((H+L+C)/3) as `price`.
 * Returns [] (never a fabricated line) the moment any candle's volume is
 * null -- this codebase's own "VOLUME HONESTY" convention
 * (nero_core/execution/export_candle_data.py) already establishes that a
 * null volume means "this source doesn't provide real volume," and VWAP
 * computed from a silently-zeroed volume would be a fabricated number, not
 * a genuine absence-of-data signal.
 */
export function computeVWAP(candles: Candle[]): LinePoint[] {
  if (candles.some((c) => c.volume === null)) return [];
  const out: LinePoint[] = [];
  let cumPV = 0;
  let cumV = 0;
  for (const candle of candles) {
    const typicalPrice = (candle.high + candle.low + candle.close) / 3;
    cumPV += typicalPrice * (candle.volume as number);
    cumV += candle.volume as number;
    out.push({ time: candle.time, value: cumV === 0 ? typicalPrice : cumPV / cumV });
  }
  return out;
}
