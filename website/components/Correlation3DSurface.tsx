"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { computeCorrelationFrames } from "@/lib/rollingCorrelation";
import type { Candle } from "@/lib/candleData";

/**
 * CC-1 Part D4/D5 — 3D correlation surface (x/y = asset pairs, z = rolling
 * correlation), animated over time with a real slider (D5's "4D").
 *
 * WHY /quant, NOT /heatmap (a stale detail in the original directive,
 * corrected here): /heatmap (app/heatmap/page.tsx) shows per-asset WIN RATE
 * -- one value per asset, not a pairwise x/y relationship, so there is no
 * natural x/y/z surface to build there. The actual x/y=asset-pair,
 * z=correlation-coefficient data the directive describes is /quant's
 * existing 2D CorrelationHeatmap. See docs/investigations/
 * website_3d4d_correlation_d4d5.md for the full writeup.
 *
 * Plotly (plotly.js-dist, MIT) is loaded via a client-side dynamic import --
 * it touches `document`/canvas/WebGL directly and is not SSR-safe.
 */
export interface Correlation3DSurfaceProps {
  assets: string[];
  candlesByAsset: Record<string, Candle[]>;
  window?: number;
  frameCount?: number;
}

export default function Correlation3DSurface({
  assets,
  candlesByAsset,
  window: rollingWindow = 30,
  frameCount = 8,
}: Correlation3DSurfaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  const frames = useMemo(
    () => computeCorrelationFrames(candlesByAsset, assets, rollingWindow, frameCount),
    [candlesByAsset, assets, rollingWindow, frameCount]
  );

  useEffect(() => {
    let disposed = false;
    let plotlyModule: typeof import("plotly.js-dist").default | null = null;

    async function render() {
      if (!containerRef.current || frames.length === 0) return;
      const Plotly = (await import("plotly.js-dist")).default;
      plotlyModule = Plotly;
      if (disposed || !containerRef.current) return;

      const surfaceColorscale: Array<[number, string]> = [
        [0, "#d47a6a"], // -1, loss-red
        [0.5, "#8a94ad"], // 0, muted
        [1, "#2ec4b6"], // +1, teal
      ];

      const makeTrace = (matrix: (number | null)[][]) => ({
        type: "surface" as const,
        x: assets,
        y: assets,
        z: matrix,
        colorscale: surfaceColorscale,
        cmin: -1,
        cmax: 1,
        showscale: true,
      });

      const plotlyFrames = frames.map((frame, i) => ({
        name: `f${i}`,
        data: [makeTrace(frame.matrix)],
      }));

      await Plotly.newPlot(
        containerRef.current,
        [makeTrace(frames[0].matrix)],
        {
          paper_bgcolor: "#0a0e27",
          plot_bgcolor: "#0a0e27",
          font: { color: "#8a94ad", size: 10 },
          scene: {
            xaxis: { color: "#8a94ad" },
            yaxis: { color: "#8a94ad" },
            zaxis: { title: { text: "correlation" }, range: [-1, 1], color: "#8a94ad" },
          },
          margin: { l: 0, r: 0, t: 30, b: 0 },
          sliders: [
            {
              currentvalue: { prefix: "Window ending: ", font: { color: "#e8e2d0" } },
              pad: { t: 40 },
              steps: frames.map((frame, i) => ({
                label: new Date(frame.time * 1000).toISOString().slice(0, 10),
                method: "animate" as const,
                args: [
                  [`f${i}`],
                  { mode: "immediate" as const, transition: { duration: 200 }, frame: { duration: 200, redraw: true } },
                ],
              })),
            },
          ],
        },
        { displayModeBar: false, responsive: true }
      );
      await Plotly.addFrames(containerRef.current, plotlyFrames);
      if (!disposed) setReady(true);
    }

    render();
    const container = containerRef.current;

    return () => {
      disposed = true;
      if (container && plotlyModule) {
        plotlyModule.purge(container);
      }
    };
  }, [frames, assets]);

  if (frames.length === 0) {
    return (
      <p data-testid="correlation-3d-unavailable" className="text-muted text-sm">
        Not enough aligned real history yet for a rolling-correlation surface (needs at
        least {rollingWindow} shared trading days across every selected asset).
      </p>
    );
  }

  return (
    <div>
      <div
        ref={containerRef}
        data-testid="correlation-3d-surface"
        className="h-[480px] w-full"
        aria-label={`3D correlation surface across ${assets.join(", ")}, animated across ${frames.length} real historical rolling windows`}
        role="img"
      />
      {!ready ? <p className="text-muted text-xs mt-1">Rendering surface…</p> : null}
    </div>
  );
}
