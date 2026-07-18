import { deriveCurrentStatus } from "@/lib/status";
import type { LedgerRow, StrategyRosterEntry } from "@/lib/types";

export interface VerdictGridProps {
  strategies: StrategyRosterEntry[];
  recentRows: LedgerRow[];
}

export default function VerdictGrid({ strategies, recentRows }: VerdictGridProps) {
  if (strategies.length === 0) {
    return <p className="text-muted">No strategies registered yet.</p>;
  }

  return (
    <div data-testid="verdict-grid" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {strategies.map((strategy) => {
        const status = deriveCurrentStatus(strategy, recentRows);
        return (
          <div
            key={`${strategy.name}-${strategy.asset}`}
            className="rounded-lg border border-gold/30 bg-ink p-4"
          >
            <h3 className="font-serif text-lg text-parchment">{strategy.name}</h3>
            <p className="text-muted text-sm">
              {strategy.asset} &middot; {strategy.timeframe}
            </p>
            <span className="inline-block mt-2 rounded-full border border-gold/50 px-2 py-0.5 text-xs text-gold">
              {strategy.verification_status}
            </span>
            <p className="mt-3 text-sm text-parchment">
              Current status: <span className="text-teal">{status}</span>
            </p>
          </div>
        );
      })}
    </div>
  );
}
