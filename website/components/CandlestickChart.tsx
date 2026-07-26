"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart } from "lightweight-charts";
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
};

export interface CandlestickChartProps {
  candles: Candle[];
  markers: ChartMarker[];
}

// lightweight-charts (TradingView's Apache-2.0 package, ~45KB gzipped) ships no
// forced watermark to remove -- that's an opt-in feature of the library, disabled by
// default, so simply never configuring one satisfies "no default watermark."
export default function CandlestickChart({ candles, markers }: CandlestickChartProps) {
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

    series.setData(candles);
    if (markers.length > 0) {
      series.setMarkers(markers);
    }

    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [candles, markers]);

  return (
    <div ref={containerRef} data-testid="candlestick-chart" className="h-[300px] w-full sm:h-[400px]" />
  );
}
