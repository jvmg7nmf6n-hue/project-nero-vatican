import type { SiteSummary } from "@/lib/types";

export function daysSince(isoDate: string): number | null {
  const then = new Date(isoDate);
  if (Number.isNaN(then.getTime())) {
    return null;
  }
  const diffMs = Date.now() - then.getTime();
  return Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
}

export interface StatsStripProps {
  summary: SiteSummary | null;
}

export default function StatsStrip({ summary }: StatsStripProps) {
  if (!summary) {
    return (
      <div data-testid="stats-strip" className="text-muted">
        Stats are temporarily unavailable.
      </div>
    );
  }

  const days = daysSince(summary.tracking_since);

  return (
    <div data-testid="stats-strip" className="grid grid-cols-1 sm:grid-cols-3 gap-6">
      <div>
        <div className="font-serif text-3xl text-parchment">{summary.configs_tested}</div>
        <div className="text-muted text-sm">Configs tested</div>
      </div>
      <div>
        <div className="font-serif text-3xl text-parchment">{summary.strategies_survived}</div>
        <div className="text-muted text-sm">Strategies survived</div>
      </div>
      <div>
        <div className="font-serif text-3xl text-parchment">{summary.tracking_since}</div>
        <div className="text-muted text-sm">
          Tracking since{days !== null ? ` (${days} day${days === 1 ? "" : "s"})` : ""}
        </div>
      </div>
    </div>
  );
}
