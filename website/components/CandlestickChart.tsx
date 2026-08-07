"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart, type Time } from "lightweight-charts";
import { computeBollingerBands, computeEMA, computeSMA, computeVWAP } from "@/lib/indicators";
import type { Candle } from "@/lib/candleData";
import type { ChartMarker } from "@/lib/chartMarkers";

// Design-system tokens, matched exactly (see CLAUDE.md / tailwind.config.ts):
// navy background, teal up-candles, loss-red down-candles, a subtle grid.
const CHART_COLORS = {
  background: "#0a0e27",
  text: "#8a94ad",
  grid: "#1a2040",
  upCandle: "#2ec4b6",
  downCandle: "#d47a6a",
  ma: "#d4af37",
  ema: "#2ec4b6",
  bollinger: "#8a94ad",
  vwap: "#e8e2d0",
};

// CC-1 Part D2 — overlay periods are fixed constants (not user-configurable
// yet): 20-period MA/EMA and 20-period/2-stdev Bollinger Bands are this
// codebase's own standard lookback (matches ma_period=20 already used by
// several strategies, e.g. orderflow_imbalance.py's MA20 gate) -- not
// invented for this chart.
const MA_PERIOD = 20;
const EMA_PERIOD = 20;
const BOLLINGER_PERIOD = 20;
const BOLLINGER_STDEV = 2;

export interface ChartOverlayToggles {
  ma?: boolean;
  ema?: boolean;
  bollinger?: boolean;
  vwap?: boolean;
}

export interface CandlestickChartProps {
  candles: Candle[];
  markers: ChartMarker[];
  overlays?: ChartOverlayToggles;
}

// lightweight-charts (TradingView's Apache-2.0 package, ~45KB gzipped) ships no
// forced watermark to remove -- that's an opt-in feature of the library, disabled by
// default, so simply never configuring one satisfies "no default watermark."
export default function CandlestickChart({ candles, markers, overlays = {} }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || candles.length === 0) {
      return;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: CHART_COLORS.background },
        textColor: CHART_COLORS.text,
      },
      grid: {
        vertLines: { color: CHART_COLORS.grid },
        horzLines: { color: CHART_COLORS.grid },
      },
      timeScale: { borderColor: CHART_COLORS.grid },
      rightPriceScale: { borderColor: CHART_COLORS.grid },
    });

    const series = chart.addCandlestickSeries({
      upColor: CHART_COLORS.upCandle,
      downColor: CHART_COLORS.downCandle,
      borderUpColor: CHART_COLORS.upCandle,
      borderDownColor: CHART_COLORS.downCandle,
      wickUpColor: CHART_COLORS.upCandle,
      wickDownColor: CHART_COLORS.downCandle,
    });

    // candleData.ts / chartMarkers.ts deliberately keep `time` as a plain `number`
    // (framework-free, no lightweight-charts import) -- the branded `Time` cast
    // happens only here, at the boundary where data is actually handed to the chart.
    series.setData(candles.map((c) => ({ ...c, time: c.time as Time })));
    if (markers.length > 0) {
      series.setMarkers(markers.map((m) => ({ ...m, time: m.time as Time })));
    }

    // CC-1 Part D2: overlays are plain lightweight-charts line series, computed
    // by lib/indicators.ts's pure functions -- see that file's own header for
    // why these are hand-rolled rather than pulled from a third-party
    // indicators package (a confirmed lightweight-charts v4/v5 incompatibility,
    // not a style preference).
    if (overlays.ma) {
      const maSeries = chart.addLineSeries({ color: CHART_COLORS.ma, lineWidth: 1, title: `MA${MA_PERIOD}` });
      maSeries.setData(computeSMA(candles, MA_PERIOD).map((p) => ({ time: p.time as Time, value: p.value })));
    }
    if (overlays.ema) {
      const emaSeries = chart.addLineSeries({ color: CHART_COLORS.ema, lineWidth: 1, title: `EMA${EMA_PERIOD}` });
      emaSeries.setData(computeEMA(candles, EMA_PERIOD).map((p) => ({ time: p.time as Time, value: p.value })));
    }
    if (overlays.bollinger) {
      const bb = computeBollingerBands(candles, BOLLINGER_PERIOD, BOLLINGER_STDEV);
      const upperSeries = chart.addLineSeries({ color: CHART_COLORS.bollinger, lineWidth: 1, title: "BB upper" });
      upperSeries.setData(bb.upper.map((p) => ({ time: p.time as Time, value: p.value })));
      const lowerSeries = chart.addLineSeries({ color: CHART_COLORS.bollinger, lineWidth: 1, title: "BB lower" });
      lowerSeries.setData(bb.lower.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    if (overlays.vwap) {
      const vwapPoints = computeVWAP(candles);
      if (vwapPoints.length > 0) {
        const vwapSeries = chart.addLineSeries({ color: CHART_COLORS.vwap, lineWidth: 1, title: "VWAP" });
        vwapSeries.setData(vwapPoints.map((p) => ({ time: p.time as Time, value: p.value })));
      }
    }

    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [candles, markers, overlays]);

  return (
    <div ref={containerRef} data-testid="candlestick-chart" className="h-[300px] w-full sm:h-[400px]" />
  );
}
