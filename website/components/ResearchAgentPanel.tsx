import type {
  AgentHypothesis,
  AgentPerformanceExport,
  AgentPerformanceRun,
  AgentRunSummary,
  AgentTestResult,
} from "@/lib/types";

// Read-only, per the Research Agent branch's own spec: no approval button
// anywhere on this panel. SURVIVED/PROMISING-WATCHLIST hypotheses show
// review_status "pending_human_approval" as plain text -- a human approves
// (or doesn't) entirely outside this UI, this panel only ever displays state.

const VERDICT_LABELS: Record<string, string> = {
  SURVIVED: "Survived",
  "PROMISING-WATCHLIST": "Promising — Watchlist",
  DIED: "Died",
  UNTESTABLE: "Untestable",
  SKIPPED: "Skipped",
};

export interface ResearchAgentPanelProps {
  hypotheses: AgentHypothesis[];
  testResults: AgentTestResult[];
  performance: AgentPerformanceExport | null;
  // CC-1 Factory Loop closeout, item 4a: optional (not required) so every
  // existing call site/test that doesn't pass it keeps compiling -- an
  // absent/empty runSummaries list simply means the too_slow list below has
  // nothing to add beyond whatever testResults itself carries.
  runSummaries?: AgentRunSummary[];
}

function resultFor(hypothesisName: string, testResults: AgentTestResult[]): AgentTestResult | undefined {
  return testResults.find((r) => r.hypothesis_name === hypothesisName);
}

// CC-1 Factory Loop closeout, item 4a: agent_test_results.json (testResults)
// is the ORIGINAL, richer source (carries a full human-readable `reason`,
// e.g. months-to-30-trades) but is currently NOT committed by
// research_agent_manual.yml at all (confirmed: zero git history for that
// path) -- so today it never populates this panel. agent_run_summaries.json
// (runSummaries) IS committed and already carries real hypothesis NAMES for
// TOO_SLOW rejections (its own `too_slow` field), just with a thinner
// measured-vs-claimed reason instead of the full one. Both sources are
// merged here, deduplicated by hypothesis_name (testResults wins when a name
// appears in both, since its reason text is richer) -- this fixes today's
// empty panel without silently discarding agent_test_results.json the day
// it starts being committed successfully.
interface TooSlowRow {
  hypothesis_name: string;
  reasonText: string;
}

function mergedTooSlowRows(testResults: AgentTestResult[], runSummaries: AgentRunSummary[]): TooSlowRow[] {
  const fromTestResults = testResults
    .filter((r) => r.frequency_classification === "TOO_SLOW")
    .map((r): TooSlowRow => ({ hypothesis_name: r.hypothesis_name, reasonText: r.reason }));

  const seen = new Set(fromTestResults.map((r) => r.hypothesis_name));
  const fromRunSummaries: TooSlowRow[] = [];
  for (const summary of runSummaries) {
    for (const entry of summary.too_slow ?? []) {
      if (seen.has(entry.hypothesis_name)) continue;
      seen.add(entry.hypothesis_name);
      fromRunSummaries.push({
        hypothesis_name: entry.hypothesis_name,
        reasonText: `measured ${entry.measured_trades_per_year.toFixed(2)} trades/year (claimed ${entry.llm_claimed_trades_per_year.toFixed(1)})`,
      });
    }
  }

  return [...fromTestResults, ...fromRunSummaries];
}

function Stat({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div data-testid="agent-performance-stat" className="rounded-lg border border-gold/30 bg-ink p-3">
      <div className="text-muted text-[10px] uppercase tracking-wide">{label}</div>
      <div className="text-parchment text-lg">{value}</div>
      {note && (
        <div data-testid="agent-cost-unknown-note" className="text-muted text-[10px] mt-1">
          {note}
        </div>
      )}
    </div>
  );
}

const RUN_STATUS_LABELS: Record<string, string> = {
  clean: "Clean",
  error: "Error",
  disabled: "Disabled",
};

// A run with status="error" but no visibly distinct treatment is worse than
// no panel at all: llm_calls_made=3 with nothing flagging the failure
// asserts the run went fine when it didn't. This badge (and the red-bordered
// card below) exist so an errored run can never look identical to a clean
// one at a glance.
function RunRow({ run }: { run: AgentPerformanceRun }) {
  const isError = run.status === "error";
  return (
    <li
      data-testid="agent-run-row"
      data-status={run.status}
      className={`rounded-lg border p-3 text-xs ${
        isError ? "border-red-500 bg-red-950/30" : "border-gold/30 bg-ink"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          data-testid="agent-run-status-badge"
          className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${
            isError ? "bg-red-500 text-ink font-bold" : "bg-gold/20 text-parchment"
          }`}
        >
          {RUN_STATUS_LABELS[run.status] ?? run.status}
        </span>
        <span className="text-muted">{run.run_at}</span>
        <span className="text-parchment">
          {run.hypotheses_generated} generated / {run.llm_calls_made} LLM calls / $
          {run.total_llm_cost_usd.toFixed(4)}
        </span>
      </div>
      {isError && run.errors.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {run.errors.map((err, i) => (
            <li key={i} data-testid="agent-run-error" className="text-red-300">
              [{err.phase}] {err.context}: {err.message}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function ResearchAgentPanel({
  hypotheses,
  testResults,
  performance,
  runSummaries = [],
}: ResearchAgentPanelProps) {
  const cumulative = performance?.cumulative ?? null;
  const tooSlowRejections = mergedTooSlowRows(testResults, runSummaries);

  return (
    <div data-testid="research-agent-panel" className="flex flex-col gap-8">
      <div>
        <h3 className="font-serif text-lg text-parchment mb-2">Agent performance</h3>
        {cumulative ? (
          <div data-testid="agent-performance-summary" className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Hypotheses generated" value={cumulative.hypotheses_generated} />
            <Stat label="Duplicates skipped" value={cumulative.duplicates_skipped} />
            <Stat label="TOO_SLOW rejected" value={cumulative.too_slow_rejected} />
            <Stat label="UNMEASURABLE rejected" value={cumulative.unmeasurable_rejected} />
            <Stat label="Tested" value={cumulative.tested} />
            <Stat label="Survived" value={cumulative.survived} />
            <Stat label="Died" value={cumulative.died} />
            <Stat
              label="Survival rate"
              value={cumulative.survival_rate === null ? "n/a" : `${(cumulative.survival_rate * 100).toFixed(0)}%`}
            />
            <Stat
              label="Cumulative API cost"
              value={`$${cumulative.total_llm_cost_usd.toFixed(2)} recorded`}
              // CC-1 Factory Loop closeout, item 3: a timed-out call is
              // recorded as UNKNOWN cost, never a fabricated $0 (see
              // AgentPerformanceCumulative's own docstring in lib/types.ts)
              // -- the recorded total above is therefore a LOWER BOUND, and
              // this note is what keeps that visible rather than reading as
              // complete. Omitted entirely when there is nothing unknown to
              // report (0, missing, or a pre-instrumentation run).
              note={
                cumulative.calls_with_unknown_cost
                  ? `${cumulative.calls_with_unknown_cost} call${cumulative.calls_with_unknown_cost === 1 ? "" : "s"} of unknown cost, not included above`
                  : undefined
              }
            />
          </div>
        ) : (
          <p data-testid="agent-performance-empty" className="text-muted">
            No agent runs recorded yet.
          </p>
        )}
      </div>

      <div>
        <h3 className="font-serif text-lg text-parchment mb-2">Recent runs</h3>
        {!performance || performance.runs.length === 0 ? (
          <p data-testid="agent-runs-empty" className="text-muted">
            No runs recorded yet.
          </p>
        ) : (
          <ul data-testid="agent-runs-list" className="flex flex-col gap-2">
            {[...performance.runs]
              .slice(-10)
              .reverse()
              .map((run, i) => (
                <RunRow key={`${run.run_at}-${i}`} run={run} />
              ))}
          </ul>
        )}
      </div>

      <div>
        <h3 className="font-serif text-lg text-parchment mb-2">Research Agent Findings</h3>
        {hypotheses.length === 0 ? (
          // CC-1 Factory Loop closeout, item 4b: agent_hypotheses.json (the
          // raw proposal text this panel reads for `hypotheses`) is
          // DELIBERATELY never committed -- research_agent_manual.yml
          // uploads it as a workflow artifact only, pending human review
          // (see that workflow's own comment). Under that correct, unchanged
          // gate, `hypotheses.length === 0` is true EVERY run, whether or
          // not anything was actually generated -- "No hypotheses generated
          // yet" is therefore not stale, it is PERMANENTLY FALSE whenever a
          // run did generate something. cumulative.hypotheses_generated (a
          // committed, derived count -- never the raw text itself) is what
          // distinguishes the three real states without violating the
          // no-raw-text rule.
          cumulative && cumulative.hypotheses_generated > 0 ? (
            <p data-testid="agent-hypotheses-pending-review" className="text-muted">
              {cumulative.hypotheses_generated} {cumulative.hypotheses_generated === 1 ? "hypothesis" : "hypotheses"}{" "}
              generated so far, pending human review — raw proposal text is not published here until reviewed.
            </p>
          ) : (
            <p data-testid="agent-hypotheses-empty" className="text-muted">
              No hypotheses generated yet.
            </p>
          )
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {hypotheses.map((h) => {
              const result = resultFor(h.hypothesis_name, testResults);
              return (
                <div
                  key={h.hypothesis_name}
                  data-testid="agent-hypothesis-card"
                  data-verdict={result?.verdict ?? "not_tested"}
                  className="rounded-lg border border-gold/30 bg-ink p-4"
                >
                  <h4 className="font-serif text-parchment">{h.hypothesis_name}</h4>
                  <p className="text-muted text-xs mt-1">
                    {h.asset} / {h.timeframe} — from: {h.scan_finding}
                  </p>
                  <p className="mt-2 text-sm text-teal">{h.mechanism}</p>
                  {result ? (
                    <div className="mt-3 flex flex-col gap-1 text-xs">
                      <span className="text-parchment">
                        Frequency: {result.frequency_classification}
                        {result.measured_trades_per_year !== null
                          ? ` (${result.measured_trades_per_year.toFixed(1)}/yr)`
                          : ""}
                      </span>
                      <span className="text-parchment">Verdict: {VERDICT_LABELS[result.verdict] ?? result.verdict}</span>
                      <span className="text-muted">{result.review_status}</span>
                    </div>
                  ) : (
                    <span data-testid="agent-hypothesis-not-tested" className="mt-3 inline-block text-xs text-muted">
                      not yet tested
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <h3 className="font-serif text-lg text-parchment mb-2">TOO_SLOW rejections (graveyard extension)</h3>
        <p className="text-muted text-sm mb-3">
          Hypotheses whose measured historical frequency would take over a year to accumulate 30 resolved
          trades — rejected before ever reaching the backtest harness, no matter how sound the mechanism looked.
        </p>
        {tooSlowRejections.length === 0 ? (
          <p data-testid="agent-too-slow-empty" className="text-muted">
            No TOO_SLOW rejections recorded yet.
          </p>
        ) : (
          <ol className="flex flex-col gap-2">
            {tooSlowRejections.map((r) => (
              <li key={r.hypothesis_name} data-testid="agent-too-slow-row" className="text-sm">
                <span className="text-parchment">{r.hypothesis_name}</span>
                <span className="text-muted"> — {r.reasonText}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
