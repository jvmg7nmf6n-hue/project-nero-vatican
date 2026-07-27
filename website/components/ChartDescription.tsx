"use client";

import { useState } from "react";
import { formatTimestamp } from "./LedgerTable";
import type { ChartDescriptionData } from "@/lib/chartDescription";

export interface ChartDescriptionProps {
  data: ChartDescriptionData;
}

export default function ChartDescription({ data }: ChartDescriptionProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div data-testid="chart-description" className="mt-4 border-t border-muted/20 pt-3">
      <button
        type="button"
        data-testid="chart-description-toggle"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        className="text-sm text-muted hover:text-parchment"
      >
        {isOpen ? "Hide" : "Show"} about this chart {isOpen ? "▲" : "▼"}
      </button>

      {isOpen ? (
        <div data-testid="chart-description-body" className="mt-2 flex flex-col gap-1 text-sm text-muted">
          <p data-testid="chart-description-timeframe">{data.timeframeSentence}</p>
          <p data-testid="chart-description-window">{data.dataWindowSentence}</p>
          {data.markerLegendLine ? (
            <p data-testid="chart-description-legend">{data.markerLegendLine}</p>
          ) : null}
          <p data-testid="chart-description-status">{data.statusLine}</p>
          {data.openPositionEntryTimestamp ? (
            <p data-testid="chart-description-open-position" className="text-teal">
              ⚡ Active trade open since {formatTimestamp(data.openPositionEntryTimestamp)}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
