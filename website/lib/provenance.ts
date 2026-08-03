import { classifyTier, TIER_LABELS } from "./tier";
import { DEFAULT_BACKTEST_EVALUATION, type StrategyRosterEntry, type StrategyStats } from "./types";

// COINTEGRATION_PAIRS hand-authored override (docs/investigations/
// pairs_short_leg_cost_scoping.md's follow-up): the generic priority logic
// below no longer describes this strategy accurately once the short leg was
// actually costed (nero_core.strategies.cointegration_pairs.
// run_pairs_backtest_two_leg -- PERP-SHORT, hedge-ratio-weighted, real
// Binance funding settlements). A real, computed re-run confirmed the edge
// survives (native grid: train +0.0436R, OOS +0.0025R, both down slightly
// from the single-leg numbers but still positive on every grid tested) --
// but OOS is thin enough, and the grid-shift audit's own live-data fetches
// are not pinned (one config's native fetch was observed silently falling
// back to a different vendor mid-run -- see docs/grid_shift_robustness_
// followup.md's NEAR/2h note), that a different data pull could plausibly
// flip its sign. This is intentionally more conservative than the generic
// "Under Trial -- backtest evidence, written <date>" phrasing every other
// strategy gets, and intentionally NOT the old net_pnl/notional-only caveat
// -- both real gaps (basis/liquidation risk, thin/unpinned OOS) are now
// named explicitly rather than left for a reader to infer from the raw R.
// Tier label hardcoded here (not read from TIER_LABELS) because this whole
// line is a fixed, hand-authored override for one specific strategy, not a
// generic priority-logic template -- see TIER_LABELS's own comment for the
// "Verified" -> "Under Trial" rename this literal string must stay in sync
// with by hand.
const COINTEGRATION_PAIRS_PROVENANCE =
  "Under Trial — two-leg funding-costed backtest, edge survives but basis/liquidation risk still unmodeled. " +
  "OOS expectancy (+0.0025R) is thin enough that a different live data pull could flip its sign — grid-shift " +
  "audits fetch live vendor data that isn't pinned, so this could change on a re-run. Its R is net_pnl/notional, " +
  "not a stop-distance risk multiple, so it is not comparable to other strategies' R on this page.";

type ProvenanceEntry = Pick<
  StrategyRosterEntry,
  "name" | "version" | "asset" | "verification_status" | "backtest_evaluation" | "source_report" | "source_report_written_at"
>;

function hasStructuredBacktestEvidence(evaluation: NonNullable<StrategyRosterEntry["backtest_evaluation"]>): boolean {
  return (
    evaluation.verdict_is !== null ||
    evaluation.verdict_oos !== null ||
    evaluation.is_trades !== null ||
    evaluation.oos_trades !== null
  );
}

// Badge-provenance fix (docs/investigations/live_strategy_backtest_and_
// universe_expansion_report.md's follow-up item 1): a tier badge alone
// ("Under Trial") doesn't say what it rests on or when that evidence was last
// touched -- a strategy backed by a real multi-year backtest looked
// identical to one backed by a single hand-typed status string. No new
// computation happens here -- every branch below only reads fields other
// modules already compute (backtest_evaluation, source_report_written_at,
// live resolved_trades) and states plainly which one is the actual basis.
// Priority, most to least authoritative:
//   1. permanently_unbacktestable -- a structural fact, overrides everything.
//   2. Real backtest evidence -- a structured harness entry (evaluated_at)
//      or a narrative source-report doc (source_report_written_at),
//      whichever has a real date.
//   3. Live resolved trades only, no backtest evidence at all.
//   4. Nothing but the hand-written verification_status string itself --
//      stated as exactly that, never dressed up as evidence it doesn't have.
export function deriveProvenanceLine(entry: ProvenanceEntry, stats: StrategyStats[]): string {
  if (entry.name === "COINTEGRATION_PAIRS") {
    return COINTEGRATION_PAIRS_PROVENANCE;
  }

  const tierLabel = TIER_LABELS[classifyTier(entry.verification_status)];
  // 2026-08-03 production incident: a currently-fetched export can genuinely
  // lack backtest_evaluation entirely (see DEFAULT_BACKTEST_EVALUATION's own
  // comment in lib/types.ts) -- never read entry.backtest_evaluation directly.
  const evaluation = entry.backtest_evaluation ?? DEFAULT_BACKTEST_EVALUATION;

  if (evaluation.permanently_unbacktestable) {
    return "Unbacktestable — live evidence only (no historical data source).";
  }

  const hasBacktestEvidence = hasStructuredBacktestEvidence(evaluation) || entry.source_report !== null;

  if (hasBacktestEvidence) {
    const date = evaluation.evaluated_at ?? entry.source_report_written_at ?? null;
    return date
      ? `${tierLabel} — backtest evidence, written ${date}, not re-evaluated since.`
      : `${tierLabel} — backtest evidence recorded, but no written date is tracked for it.`;
  }

  const match = stats.find(
    (row) => row.strategy === entry.name && row.strategy_version === entry.version && row.asset === entry.asset
  );
  const resolvedTrades = match?.resolved_trades ?? 0;

  if (resolvedTrades > 0) {
    return `${tierLabel} — ${resolvedTrades} live resolved trade${resolvedTrades === 1 ? "" : "s"}, updated automatically.`;
  }

  return `${tierLabel} — this status is a hand-written note only; no structured backtest or live-trade evidence is recorded yet.`;
}
