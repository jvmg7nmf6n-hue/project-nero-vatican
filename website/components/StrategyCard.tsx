import Link from "next/link";
import TierBadge from "./TierBadge";
import { formatTimestamp } from "./LedgerTable";
import { deriveSignalDetail } from "@/lib/signalDetail";
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
  const rawSignalState = deriveSignalState(entry, recentRows);
  const signalDetail =
    rawSignalState === "entry" || rawSignalState === "exit"
      ? deriveSignalDetail(entry, recentRows, stats)
      : null;
  // Never show a bare ENTRY/EXIT label with no backing detail (e.g. the exact
  // (name, version, asset) triple doesn't match the row deriveSignalState's
  // looser (name, asset)-only lookup found) -- fall back to "no signal yet"
  // instead, per the same "never fabricate" discipline the rest of the site uses.
  const signalState: SignalState =
    (rawSignalState === "entry" || rawSignalState === "exit") && !signalDetail
      ? "no_signal_yet"
      : rawSignalState;
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
        {/* Structured backtest evaluation (verdict_is/verdict_oos/untestable_reason)
            -- only shown when this session's own structured harness actually produced
            one; a strategy with no entry here still has its tier badge above (derived
            from verification_status), so this is additive detail, not the only signal.
            Never omitted when it exists -- the whole point is that a card must not look
            identical whether a strategy DIED in-sample or was never tested at all. */}
        {entry.backtest_evaluation.untestable_reason ? (
          <p data-testid="card-backtest-untestable" className="mt-1 text-[11px] text-gold">
            Untestable by standard harness
          </p>
        ) : entry.backtest_evaluation.verdict_is || entry.backtest_evaluation.verdict_oos ? (
          <p data-testid="card-backtest-verdict" className="mt-1 text-[11px] text-muted">
            Backtest: {entry.backtest_evaluation.verdict_is ?? "n/a"} (IS) /{" "}
            {entry.backtest_evaluation.verdict_oos ?? "n/a"} (OOS)
          </p>
        ) : null}
      </div>

      {/* CURRENT SIGNAL -- "what is it doing right now?" Dynamic, ledger-derived.
          Separated by a divider and its own color language so it can never read as
          part of the research-status verdict above. */}
      <div data-testid="current-signal" className="mt-3 border-t border-muted/20 pt-3">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${signalStyle.dot}`} aria-hidden="true" />
          <p className="text-sm">
            <span className="text-muted">Current signal: </span>
            <span className={`font-medium ${signalStyle.text}`}>
              {SIGNAL_STATE_LABELS[signalState]}
            </span>
          </p>
        </div>
        {signalDetail ? (
          <p data-testid="signal-detail" className="mt-1 pl-4 text-xs text-muted">
            {signalState === "entry" ? (
              <>
                Entered {signalDetail.entryPrice !== null ? `@ ${signalDetail.entryPrice} ` : ""}
                {signalDetail.entryTimestamp ? formatTimestamp(signalDetail.entryTimestamp) : ""}
              </>
            ) : (
              <>
                Exited {signalDetail.exitPrice !== null ? `@ ${signalDetail.exitPrice} ` : ""}
                {signalDetail.exitTimestamp ? formatTimestamp(signalDetail.exitTimestamp) : ""}
                {signalDetail.entryPrice !== null ? ` (entered @ ${signalDetail.entryPrice})` : ""}
                {" · "}
                {signalDetail.pnlPending
                  ? "P&L pending"
                  : `P&L: ${signalDetail.avgReturnPct !== null ? signalDetail.avgReturnPct.toFixed(2) : "n/a"}%`}
              </>
            )}
          </p>
        ) : null}
      </div>

      <p className="mt-2 text-xs text-muted">{statLine}</p>
    </Link>
  );
}
