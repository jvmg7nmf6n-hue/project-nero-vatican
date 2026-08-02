import type { BacktestEvaluation } from "@/lib/types";

export interface BacktestEvaluationPanelProps {
  evaluation: BacktestEvaluation;
}

// This is the same failure class as the 401 dashboard gap fixed earlier: a
// strategy card that only ever shows the free-text verification_status
// summary can silently omit that a strategy DIED in-sample, or that its
// out-of-sample sample is too thin to mean anything, or that it can't run
// through the standard harness at all. This panel exists so none of those
// three cases ever renders as a blank space -- every branch below prints
// something explicit, never nothing.
export default function BacktestEvaluationPanel({ evaluation }: BacktestEvaluationPanelProps) {
  const hasStructuredVerdict = evaluation.verdict_is !== null || evaluation.verdict_oos !== null;
  const hasAnyEvidence =
    hasStructuredVerdict || evaluation.is_trades !== null || evaluation.oos_trades !== null;

  if (!hasAnyEvidence && !evaluation.untestable_reason) {
    return (
      <p data-testid="backtest-evaluation-not-yet" className="text-muted text-sm">
        {evaluation.note ?? "Not yet evaluated with this structured format."}
      </p>
    );
  }

  return (
    <div data-testid="backtest-evaluation-panel" className="flex flex-col gap-3">
      {evaluation.untestable_reason ? (
        <div
          data-testid="backtest-evaluation-untestable"
          className="rounded-lg border border-gold/50 bg-gold/5 p-3 text-sm text-parchment"
        >
          <span className="font-medium">Untestable by the standard harness.</span>{" "}
          {evaluation.untestable_reason}
        </div>
      ) : null}

      {hasAnyEvidence ? (
        <div data-testid="backtest-evaluation-stats" className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-lg border border-gold/30 bg-ink p-3">
            <div className="text-muted text-[10px] uppercase tracking-wide">Verdict (in-sample)</div>
            <div data-testid="verdict-is" className="mt-1 text-parchment">
              {evaluation.verdict_is ?? "n/a"}
            </div>
          </div>
          <div className="rounded-lg border border-gold/30 bg-ink p-3">
            <div className="text-muted text-[10px] uppercase tracking-wide">Verdict (out-of-sample)</div>
            <div data-testid="verdict-oos" className="mt-1 text-parchment">
              {evaluation.verdict_oos ?? "n/a"}
            </div>
          </div>
          <div className="rounded-lg border border-gold/30 bg-ink p-3">
            <div className="text-muted text-[10px] uppercase tracking-wide">Trades (IS / OOS)</div>
            <div data-testid="trade-counts" className="mt-1 text-parchment">
              {evaluation.is_trades ?? "n/a"} / {evaluation.oos_trades ?? "n/a"}
            </div>
          </div>
          <div className="rounded-lg border border-gold/30 bg-ink p-3">
            <div className="text-muted text-[10px] uppercase tracking-wide">Expectancy R (IS / OOS)</div>
            <div data-testid="expectancy" className="mt-1 text-parchment">
              {evaluation.is_expectancy_r !== null ? evaluation.is_expectancy_r.toFixed(3) : "n/a"} /{" "}
              {evaluation.oos_expectancy_r !== null ? evaluation.oos_expectancy_r.toFixed(3) : "n/a"}
            </div>
          </div>
        </div>
      ) : null}

      {evaluation.evaluated_at || evaluation.data_source || evaluation.method ? (
        <p data-testid="backtest-evaluation-meta" className="text-xs text-muted">
          {evaluation.evaluated_at ? <>Evaluated {evaluation.evaluated_at}. </> : null}
          {evaluation.data_source ? <>Data: {evaluation.data_source}. </> : null}
          {evaluation.method ? <>Method: {evaluation.method}.</> : null}
        </p>
      ) : null}
    </div>
  );
}
