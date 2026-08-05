import {
  computeAdamFunnel,
  computeEveFunnel,
  computePreRegistrationProgress,
  extractFrequencyClaims,
  PRE_REGISTERED_SESSION_COUNT,
} from "@/lib/agentsPage";
import {
  fetchAgentPerformance,
  fetchAgentRunSummaries,
  fetchEveBudgetLedger,
  fetchEveHypotheses,
  fetchEveSessionRegistry,
} from "@/lib/data";
import type { AgentFunnel } from "@/lib/agentsPage";
import type { EveSessionRegistryEntry } from "@/lib/types";

export const revalidate = 300;

export const metadata = {
  title: "Agents — Vatican",
};

function formatUsd(n: number): string {
  return `$${n.toFixed(4)}`;
}

function FunnelCard({ funnel }: { funnel: AgentFunnel }) {
  return (
    <div className="rounded-lg border border-gold/30 bg-ink p-4">
      <h3 className="font-serif text-lg text-parchment mb-3">{funnel.label}</h3>
      <div className="flex flex-wrap items-center gap-2 text-sm text-parchment">
        <span>{funnel.proposed} proposed</span>
        <span className="text-muted">→</span>
        <span>{funnel.dslValid} DSL-valid</span>
        <span className="text-muted">→</span>
        <span>{funnel.reachedHarness} reached harness</span>
        <span className="text-muted">→</span>
        <span className="font-medium">{funnel.survived} SURVIVED</span>
      </div>
      <p className="text-muted text-xs mt-2">
        {funnel.tooSlowCount} TOO_SLOW
        {funnel.selfDerivativeCount > 0 && `, ${funnel.selfDerivativeCount} SELF_DERIVATIVE excluded from the FDR family`}
      </p>
    </div>
  );
}

const SESSION_CLASSIFICATION_LABELS: Record<string, string> = {
  crashed_before_completion: "Crashed",
};

function SessionHealthRow({ entry }: { entry: EveSessionRegistryEntry }) {
  const isCrashed = entry.classification === "crashed_before_completion";
  return (
    <li
      data-testid="session-health-row"
      data-crashed={isCrashed}
      className={`rounded-lg border p-3 text-xs ${isCrashed ? "border-red-500 bg-red-950/30" : "border-gold/30 bg-ink"}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide ${
            isCrashed ? "bg-red-500 text-ink font-bold" : entry.counts_toward_pre_registered_8 ? "bg-teal/30 text-parchment" : "bg-gold/20 text-parchment"
          }`}
        >
          {SESSION_CLASSIFICATION_LABELS[entry.classification] ?? entry.classification}
        </span>
        <span className="text-parchment">{entry.session_id}</span>
        {entry.counts_toward_pre_registered_8 && <span className="text-teal">counts toward the 8</span>}
      </div>
      <p className="text-muted mt-1">{entry.reason}</p>
    </li>
  );
}

// CC-1 Master Directive, Phase 2: the Agents tab -- the first place on this
// site either agent's real operating state (not just their output) is
// visible: pre-registration progress, side-by-side funnels, every session's
// real health (crashed sessions included, never hidden), the claimed-vs-
// measured frequency finding, and cost -- recorded spend never presented as
// a complete total when unknown-cost calls exist (see /lab's own
// ResearchAgentPanel for the same discipline, item 3 of the prior
// directive).
export default async function AgentsPage() {
  const [eveRegistry, eveHypotheses, eveLedger, adamPerformance, adamRunSummaries] = await Promise.all([
    fetchEveSessionRegistry(),
    fetchEveHypotheses(),
    fetchEveBudgetLedger(),
    fetchAgentPerformance(),
    fetchAgentRunSummaries(),
  ]);

  const hypotheses = eveHypotheses ?? [];
  const ledger = eveLedger ?? [];
  const sessions = eveRegistry?.sessions ?? [];
  const runSummaries = adamRunSummaries ?? [];

  const progress = computePreRegistrationProgress(eveRegistry, hypotheses, ledger, adamPerformance);

  // The funnel is scoped to the one COUNTABLE session (if any) -- falls
  // back to the most recently attempted session's id so the page still
  // shows something real before Session 2 ever counts, rather than an
  // empty funnel next to a nonempty Session Health list below it.
  const countableSession = sessions.find((s) => s.counts_toward_pre_registered_8);
  const mostRecentSession = sessions.length > 0 ? sessions[sessions.length - 1] : null;
  const eveFunnelSessionId = countableSession?.session_id ?? mostRecentSession?.session_id ?? null;
  const eveFunnel = computeEveFunnel(hypotheses, eveFunnelSessionId);
  const adamFunnel = computeAdamFunnel(adamPerformance);

  const frequencyClaims = extractFrequencyClaims(runSummaries);

  const crashedSessions = sessions.filter((s) => s.classification === "crashed_before_completion");

  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="font-serif text-3xl text-parchment">Agents</h1>
        <p className="text-muted mt-2 max-w-2xl">
          What Adam and Eve are actually doing, in real numbers read directly from the same files
          this project&apos;s own harness writes — including the sessions that crashed and produced
          nothing. See the{" "}
          <a href="/factory-loop" className="underline">
            Factory Loop
          </a>{" "}
          page for how a hypothesis moves through this system end to end.
        </p>
      </div>

      <section data-testid="pre-registration-progress" className="rounded-lg border border-gold/40 bg-ink p-5">
        <h2 className="font-serif text-xl text-parchment mb-3">Pre-registration progress</h2>
        <p className="text-parchment text-lg">
          Session {progress.sessionsCounted} of {PRE_REGISTERED_SESSION_COUNT} · {progress.sessionsRemaining} remaining ·{" "}
          {progress.survivedCount} SURVIVED · {formatUsd(progress.eveRecordedUsd + progress.adamRecordedUsd)} recorded
        </p>
        <p className="text-muted text-sm mt-2">
          Budgeted for the full pre-registered campaign: {progress.sessionsBudgetedText || "not yet reporting"}.
          {(progress.eveUnknownCount > 0 || progress.adamUnknownCount > 0) && (
            <>
              {" "}
              This does NOT include {progress.eveUnknownCount} Eve call{progress.eveUnknownCount === 1 ? "" : "s"} (
              {formatUsd(progress.eveUnknownProjectedUsd)} conservatively projected, real cost unknown — crashed mid-call,
              see Session Health below) and {progress.adamUnknownCount} Adam call{progress.adamUnknownCount === 1 ? "" : "s"} of
              unknown cost — never mixed into the recorded total above.
            </>
          )}
        </p>
        <p className="text-muted text-xs mt-2">
          Crashed sessions are counted separately in the total above (they cost real, conservatively-estimated money and
          produce zero data points toward the 5%-OOS-survival bar) — see{" "}
          <span className="text-parchment">{eveRegistry?.pre_registration.eve_must_clear || "the pre-registration criterion"}</span>.
        </p>
      </section>

      <section>
        <h2 className="font-serif text-2xl text-parchment mb-4">Funnel, side by side</h2>
        <p className="text-muted text-sm mb-3">
          Eve&apos;s funnel is scoped to session {eveFunnelSessionId ?? "(none yet)"}
          {countableSession ? " — the one countable session so far" : " — the most recent attempt (not yet counted)"}.
          Adam&apos;s is cumulative across every real run on file.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <FunnelCard funnel={eveFunnel} />
          <FunnelCard funnel={adamFunnel} />
        </div>
      </section>

      <section>
        <h2 className="font-serif text-2xl text-parchment mb-4">Session health</h2>
        {sessions.length === 0 ? (
          <p data-testid="session-health-empty" className="text-muted">
            No session registry data available yet.
          </p>
        ) : (
          <>
            <p className="text-muted text-sm mb-3">
              {crashedSessions.length} of {sessions.length} recorded session attempt{sessions.length === 1 ? "" : "s"} crashed
              before completion — shown here, not hidden.
            </p>
            <ul className="flex flex-col gap-2">
              {sessions.map((entry) => (
                <SessionHealthRow key={entry.session_id} entry={entry} />
              ))}
            </ul>
          </>
        )}
      </section>

      <section>
        <h2 className="font-serif text-2xl text-parchment mb-4">Claimed vs. measured frequency</h2>
        <p className="text-muted text-sm mb-3">
          This platform independently measures how often a proposed entry condition actually fires in real
          history — every real TOO_SLOW rejection on file compares the agent&apos;s own claim against that
          measurement. The direction (overestimation) is consistent so far; the magnitude, on this few data
          points, is not something to trust yet.
        </p>
        {frequencyClaims.length === 0 ? (
          <p data-testid="frequency-claims-empty" className="text-muted">
            No TOO_SLOW rejections with a recorded claim vs. measurement yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {frequencyClaims.map((c) => (
              <li key={c.hypothesisName} data-testid="frequency-claim-row" className="rounded-lg border border-gold/30 bg-ink p-3 text-sm">
                <span className="text-parchment">{c.hypothesisName}</span>
                <span className="text-muted">
                  {" "}
                  — claimed {c.claimedPerYear.toFixed(1)}/yr, measured {c.measuredPerYear.toFixed(1)}/yr
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="font-serif text-2xl text-parchment mb-4">Cost</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-gold/30 bg-ink p-4">
            <h3 className="font-serif text-parchment mb-1">Eve</h3>
            <p className="text-parchment text-lg">{formatUsd(progress.eveRecordedUsd)} recorded</p>
            {progress.eveUnknownCount > 0 && (
              <p data-testid="eve-unknown-cost-note" className="text-muted text-xs mt-1">
                {progress.eveUnknownCount} call{progress.eveUnknownCount === 1 ? "" : "s"} of unknown cost (
                {formatUsd(progress.eveUnknownProjectedUsd)} conservatively projected), not included above
              </p>
            )}
          </div>
          <div className="rounded-lg border border-gold/30 bg-ink p-4">
            <h3 className="font-serif text-parchment mb-1">Adam</h3>
            <p className="text-parchment text-lg">{formatUsd(progress.adamRecordedUsd)} recorded</p>
            {progress.adamUnknownCount > 0 && (
              <p data-testid="adam-unknown-cost-note" className="text-muted text-xs mt-1">
                {progress.adamUnknownCount} call{progress.adamUnknownCount === 1 ? "" : "s"} of unknown cost, not included above
              </p>
            )}
          </div>
        </div>
      </section>

      <section>
        <p className="text-muted text-xs">
          Last updated: Adam — {adamPerformance?.last_updated ?? "not yet reporting"}. Eve&apos;s own session data has no
          single last-updated stamp; the most recent session attempt on file is{" "}
          {mostRecentSession?.session_id ?? "none yet"}.
        </p>
      </section>
    </div>
  );
}
