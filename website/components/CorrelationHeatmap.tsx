import { buildCorrelationGrid, correlationColor } from "@/lib/quantCrossAsset";
import type { CorrelationPair } from "@/lib/types";

export interface CorrelationHeatmapProps {
  assets: string[];
  pairs: CorrelationPair[];
}

// A plain div grid, not an SVG or a charting library -- per this task's own
// constraint ("static SVG or simple div grid -- no new charting library"), a div
// grid is simpler to keep responsive/scrollable than hand-rolled SVG text
// positioning would be.
export default function CorrelationHeatmap({ assets, pairs }: CorrelationHeatmapProps) {
  if (assets.length === 0) {
    return <p className="text-muted text-sm">No assets available yet.</p>;
  }

  const grid = buildCorrelationGrid(assets, pairs);

  return (
    <div className="overflow-x-auto">
      <div
        data-testid="correlation-heatmap"
        className="inline-grid gap-[2px]"
        style={{ gridTemplateColumns: `minmax(70px, auto) repeat(${assets.length}, minmax(56px, 1fr))` }}
      >
        <div />
        {assets.map((asset) => (
          <div key={`col-${asset}`} className="px-1 py-1 text-center text-[10px] text-muted truncate" title={asset}>
            {asset}
          </div>
        ))}

        {assets.map((rowAsset, rowIndex) => (
          <div key={`row-${rowAsset}`} className="contents">
            <div className="px-2 py-1 text-[10px] text-muted whitespace-nowrap">{rowAsset}</div>
            {grid[rowIndex].map((cell, colIndex) => (
              <div
                key={`${rowAsset}-${assets[colIndex]}`}
                data-testid="heatmap-cell"
                data-row={rowAsset}
                data-col={assets[colIndex]}
                className="flex items-center justify-center rounded-sm px-1 py-2 text-[10px] text-parchment"
                style={{ backgroundColor: correlationColor(cell.value, cell.isSelf ? 0.15 : 0.85) }}
              >
                {cell.isSelf ? <span className="text-muted">&mdash;</span> : cell.value === null ? (
                  <span className="text-muted">N/A</span>
                ) : (
                  cell.value.toFixed(2)
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
