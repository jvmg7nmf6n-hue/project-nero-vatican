import Link from "next/link";
import TierBadge from "./TierBadge";
import { deriveSignalState, SIGNAL_STATE_LABELS, type SignalState } from "@/lib/signalState";
import { deriveStatLine } from "@/lib/statLine";
import { buildStrategyId } from "@/lib/strategyId";
import { classifyTier, type Tier } from "@/lib/tier";
import type { LedgerRow, StrategyRosterEntry, StrategyStats } from "@/lib/types";

const TIER_CARD_STYLES: Record<Tier, string> = {
  verified: "border-2 border-solid border-teal/70 bg-ink",
  watchlist: "border-2 border-dashed border-gold/60 bg-ink",
  experimental: "border-2 border-dotted border-muted/50 bg-ink",
};

interface SignalStateStyle {
  dot: string;
  text: string;
}

// Lives here (not in lib/signalState.ts) so tailwind.config.ts's content
// scanner -- which only reads app/**/*.{ts,tsx} and components/**/*.{ts,tsx} --
// actually sees these literal class-name strings at build time.
const SIGNAL_STATE_STYLES: Record<SignalState, SignalStateStyle> = {
  entry: { dot: "bg-teal", text: "text-teal" },
  exit: { dot: "bg-amber-400", text: "text-amber-400" },
  watching: { dot: "bg-gray-400", text: "text-gray-300" },
  no_signal_yet: { dot: "bg-muted/50", text: "text-muted" },
};

export interface StrategyCardProps {
  entry: StrategyRosterEntry;
  recentRows: LedgerRow[];
  stats: StrategyStats[];
}

export default function StrategyCard({ entry, recentRows, stats }: StrategyCardProps) {
  const tier = classifyTier(entry.verification_status);
  const signalState = deriveSignalState(entry, recentRows);
  const statLine = deriveStatLine(entry, stats);
  const signalStyle = SIGNAL_STATE_STYLES[signalState];

  return (
    <Link
      href={`/strategy/${buildStrategyId(entry)}`}
      data-testid="strategy-card"
      data-tier={tier}
      data-signal-state={signalState}
      className={`block rounded-lg p-4 hover:opacity-90 ${TIER_CARD_STYLES[tier]}`}
    >
      {/* RESEARCH STATUS -- "has this strategy earned trust?" Static, backtest-derived,
          unrelated to whatever the ledger logged most recently. */}
      <div data-testid="research-status">
        <h3 className="font-serif text-lg text-parchment">{entry.name}</h3>
        <p className="text-muted text-sm">
          {entry.asset} &middot; {entry.timeframe}
        </p>
        <div className="mt-2 text-[10px] uppercase tracking-wide text-muted">
          Research status
        </div>
        <div className="mt-1">
          <TierBadge tier={tier} />
        </div>
      </div>

      {/* CURRENT SIGNAL -- "what is it doing right now?" Dynamic, ledger-derived.
          Separated by a divider and its own color language so it can never read as
          part of the research-status verdict above. */}
      <div
        data-testid="current-signal"
        className="mt-3 flex items-center gap-2 border-t border-muted/20 pt-3"
      >
        <span className={`h-2 w-2 rounded-full ${signalStyle.dot}`} aria-hidden="true" />
        <p className="text-sm">
          <span className="text-muted">Current signal: </span>
          <span className={`font-medium ${signalStyle.text}`}>
            {SIGNAL_STATE_LABELS[signalState]}
          </span>
        </p>
      </div>

      <p className="mt-2 text-xs text-muted">{statLine}</p>
    </Link>
  );
}
