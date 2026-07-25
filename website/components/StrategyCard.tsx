import { deriveCurrentStatus } from "@/lib/status";
import { deriveStatLine } from "@/lib/statLine";
import { classifyTier, TIER_LABELS, type Tier } from "@/lib/tier";
import type { LedgerRow, StrategyRosterEntry, StrategyStats } from "@/lib/types";

const TIER_CARD_STYLES: Record<Tier, string> = {
  verified: "border-2 border-solid border-teal/70 bg-ink",
  watchlist: "border-2 border-dashed border-gold/60 bg-ink",
  experimental: "border-2 border-dotted border-muted/50 bg-ink",
};

const TIER_BADGE_STYLES: Record<Tier, string> = {
  verified: "border-teal/70 text-teal",
  watchlist: "border-gold/60 text-gold",
  experimental: "border-muted/60 text-muted",
};

export interface StrategyCardProps {
  entry: StrategyRosterEntry;
  recentRows: LedgerRow[];
  stats: StrategyStats[];
}

export default function StrategyCard({ entry, recentRows, stats }: StrategyCardProps) {
  const tier = classifyTier(entry.verification_status);
  const status = deriveCurrentStatus(entry, recentRows);
  const statLine = deriveStatLine(entry, stats);

  return (
    <div
      data-testid="strategy-card"
      data-tier={tier}
      className={`rounded-lg p-4 ${TIER_CARD_STYLES[tier]}`}
    >
      <h3 className="font-serif text-lg text-parchment">{entry.name}</h3>
      <p className="text-muted text-sm">
        {entry.asset} &middot; {entry.timeframe}
      </p>
      <span
        className={`inline-block mt-2 rounded-full border px-2 py-0.5 text-xs ${TIER_BADGE_STYLES[tier]}`}
      >
        {TIER_LABELS[tier]}
      </span>
      <p className="mt-3 text-sm text-parchment">
        Current status: <span className="text-teal">{status}</span>
      </p>
      <p className="mt-1 text-xs text-muted">{statLine}</p>
    </div>
  );
}
