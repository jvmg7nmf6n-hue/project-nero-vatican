import { buildQuantMetricCards } from "@/lib/quantPanel";
import type { QuantMetricsEntry } from "@/lib/types";

export interface QuantPanelProps {
  entry: QuantMetricsEntry | null;
}

// Research/education framing throughout, per this panel's own scope: Vatican does
// not place orders, and every card below is an independently-interpretable
// statistic -- there is deliberately no composite score, rank, or "overall
// health" figure anywhere on this panel.
export default function QuantPanel({ entry }: QuantPanelProps) {
  return (
    <section>
      <h2 className="font-serif text-xl text-parchment mb-2">Quant Panel</h2>
      <p className="text-xs text-muted mb-4 max-w-2xl">
        Standalone risk/return statistics for this asset, for research and educational
        context only -- not a trade instruction, and not combined into any single score.
      </p>

      {!entry ? (
        <p data-testid="quant-panel-unavailable" className="text-muted text-sm">
          Quant metrics coming soon for this asset.
        </p>
      ) : (
        <>
          <p data-testid="quant-panel-context" className="text-xs text-muted mb-3">
            Trailing window: {entry.window_used} periods &middot; {entry.timeframe} candles
          </p>
          <div data-testid="quant-panel-grid" className="grid gap-3 grid-cols-2 lg:grid-cols-5">
            {buildQuantMetricCards(entry).map((card) => (
              <div
                key={card.key}
                data-testid={`quant-card-${card.key}`}
                className="rounded-lg border border-muted/20 bg-ink p-3"
              >
                <div className="text-[10px] uppercase tracking-wide text-muted">{card.label}</div>
                <div
                  data-testid={`quant-card-${card.key}-value`}
                  className="mt-1 font-serif text-lg text-parchment"
                >
                  {card.value === null ? <span className="text-muted">&mdash;</span> : card.value}
                </div>
                <p className="mt-1 text-[11px] text-muted leading-snug">{card.explanation}</p>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
