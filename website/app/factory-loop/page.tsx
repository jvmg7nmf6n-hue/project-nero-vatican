import FactoryLoopDiagram from "@/components/FactoryLoopDiagram";
import PageHeader from "@/components/PageHeader";
import { fetchAgentPerformance, fetchFactoryLoopStatus, fetchForwardTrial, fetchGraveyard, fetchTrialEntries } from "@/lib/data";
import type { TrialEntry } from "@/lib/types";

export const revalidate = 300;

export const metadata = {
  title: "Factory Loop — Vatican",
};

// CC-1 Factory Loop directive, item 8: following app/methodology/page.tsx's
// static-prose pattern, PLUS the two counts (graveyard, forward trial/repair)
// that ARE live-fetchable today (fetchGraveyard always has real data;
// fetchFactoryLoopStatus is null until tools/factory_loop_status_summary.py
// has run at least once -- item 9). Per docs/investigations/
// factory_loop_specification.md's own B8 recommendation: this page can ship
// now, independent of whether item 9's aggregate export has real non-zero
// data yet, as long as it states plainly what's live vs. designed-not-yet-
// populated -- never implying more exists than does.
// CC-1 directive, "Show real trial-entry activity on /factory-loop": a
// Trial ADMISSION (forward_trial.json's own status=="OPEN") is not the
// same real-world fact as a genuine Forward Trial ENTRY (trial_entries.json,
// already correctly surfaced on /signals) -- see nero_core/execution/
// export_trial_entries.py's own module docstring for the confirmed,
// precise distinction (10 admissions on file, only 1 has ever produced a
// real entry). Reuses fetchTrialEntries() unchanged -- the exact same
// function /signals already calls -- rather than a second, independently-
// maintained read of the same file, so the two pages can never disagree
// about which admissions have a real position.
function latestEntryByTrialId(entries: TrialEntry[]): Map<string, TrialEntry> {
  const byTrial = new Map<string, TrialEntry>();
  for (const entry of entries) {
    const existing = byTrial.get(entry.trial_id);
    if (!existing || new Date(entry.timestamp).getTime() > new Date(existing.timestamp).getTime()) {
      byTrial.set(entry.trial_id, entry);
    }
  }
  return byTrial;
}

export default async function FactoryLoopPage() {
  const [graveyard, factoryLoopStatus, agentPerformance, forwardTrialRecords, trialEntriesExport] = await Promise.all([
    fetchGraveyard(),
    fetchFactoryLoopStatus(),
    fetchAgentPerformance(),
    fetchForwardTrial(),
    fetchTrialEntries(),
  ]);

  const graveyardCount = graveyard?.length ?? 0;
  const forwardTrialCount = factoryLoopStatus?.forward_trial.count ?? 0;
  const unmeasurableCount = factoryLoopStatus?.forward_trial.unmeasurable_count ?? 0;
  const repairChainCount = factoryLoopStatus?.repair.count ?? 0;
  const statusIsLive = factoryLoopStatus !== null;
  const openTrialRecords = (forwardTrialRecords ?? []).filter((r) => r.status === "OPEN");
  const entryByTrialId = latestEntryByTrialId(trialEntriesExport?.entries ?? []);

  const adamSurvived = agentPerformance?.cumulative.survived ?? 0;
  const adamPromisingWatchlist = agentPerformance?.cumulative.promising_watchlist ?? 0;

  return (
    <div className="prose-vatican max-w-2xl">
      <PageHeader
        title="Factory Loop"
        description="How a trading idea moves through this project, end to end: proposed, tested,
        and either watched forward or retired — honestly, with every stage labeled by
        whether it is live today or still just designed."
      />

      <section className="mt-8">
        <FactoryLoopDiagram />
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Who proposes ideas: Adam and Eve</h2>
        <p className="text-muted mt-2">
          Every hypothesis in this loop comes from one of two AI research agents, openly
          — there is no hidden human curator picking winners before they reach the test
          harness. <span className="text-parchment font-medium">Adam</span> (the
          Research Agent, <code>nero_core/research_agent/</code>) scans this project&apos;s
          own live market data for statistical anomalies and proposes a rule-based
          hypothesis to test against them, plus an independent web-search discovery
          channel that reads outside research and proposes ideas from it. {" "}
          <span className="text-parchment font-medium">Eve</span> (
          <code>nero_core/eve/</code>) is a more open-ended research agent: given the
          project&apos;s own graveyard of already-failed mechanisms and a live web-search
          tool, she reasons freely about what to try next rather than following a fixed
          scan routine. Every hypothesis, from either agent, runs through the exact same
          statistical harness described on the{" "}
          <a href="/methodology" className="underline">
            methodology page
          </a>{" "}
          — no special treatment for either source.
        </p>
        <p className="text-muted mt-2">
          This is the first place on this site Eve&apos;s work is shown publicly. Her
          research is real and ongoing, but still early: as of this writing she is partway
          through a pre-registered, 8-session evaluation campaign (see{" "}
          <code>eve_session_registry.json</code>) before any conclusion is drawn about
          whether her more open-ended approach finds anything Adam&apos;s scan-driven one
          would not.
        </p>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Test → Graveyard, distilled</h2>
        <p className="text-muted mt-2">
          A hypothesis that dies is never just discarded. Once a family of related
          mechanisms accumulates enough DIED verdicts (3, currently), an LLM drafts a
          plain-language summary of why that family fails — reviewed and approved by a
          human before it&apos;s recorded, never written automatically. That summary is
          what Adam and Eve read, every single time, before proposing anything new — so
          the same dead idea is never rediscovered and retested from scratch.
        </p>
        <p className="text-parchment mt-2">
          <strong>{graveyardCount}</strong> mechanism families are recorded in the
          graveyard today —{" "}
          <a href="/graveyard" className="underline">
            see the full list
          </a>
          . This count is real and live, read directly from the same file Adam and Eve
          themselves read as context.
        </p>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Test → Forward Trial</h2>
        <p className="text-muted mt-2">
          A hypothesis that is DSL-valid — its entry and exit rules are machine-checkable
          — is admitted to Forward Trial and paper-tracked going forward, regardless of
          how it scored on its historical backtest. The backtest verdict travels with it
          as a label, not a gate: a DIED hypothesis can still enter Forward Trial, because
          the whole point is to measure it on data that didn&apos;t exist when it was
          proposed, never to gate on a verdict that could itself be a fluke of the sample
          available at the time.
        </p>
        <p className="text-muted mt-2">
          This is unrelated to the <code>&quot;Under Trial&quot;</code> label you may see
          elsewhere on this site next to a specific strategy config — that is a
          long-standing research-status tier for already-live strategies. This page&apos;s{" "}
          <span className="text-teal font-medium">Forward Trial</span> is a distinct,
          new concept: the automated paper-tracking queue every fresh Adam/Eve hypothesis
          (and every successfully repaired one) now passes through.
        </p>
        <p className="text-parchment mt-2">
          <strong>{forwardTrialCount}</strong> hypotheses are currently in Forward Trial
          {statusIsLive ? (
            <>
              {" "}
              ({factoryLoopStatus?.forward_trial.by_origin.adam ?? 0} from Adam,{" "}
              {factoryLoopStatus?.forward_trial.by_origin.eve ?? 0} from Eve,{" "}
              {factoryLoopStatus?.forward_trial.by_origin.repaired ?? 0} from a repaired
              chain).
            </>
          ) : (
            "."
          )}{" "}
          {statusIsLive
            ? "Zero is an honest, expected number this early — the admission mechanism only just shipped, not a sign anything is broken."
            : "The live count for this section has not started reporting yet — the mechanism that admits hypotheses to Forward Trial is built and tested, but no scheduled run has produced a status export yet."}
        </p>
        {statusIsLive && unmeasurableCount > 0 && (
          <p data-testid="unmeasurable-count" className="text-muted text-sm mt-2">
            <strong className="text-parchment">{unmeasurableCount}</strong> of these {forwardTrialCount} project a
            measurement time beyond our 2-year visibility horizon — shown here, not hidden or excluded, because
            admission to Forward Trial is DSL-validity only, never gated on how often a rule fires. A large number
            below is a real, honestly-measured result: it means this specific rule&apos;s trigger condition is
            genuinely rare at its currently-known rate, not a bug or a joke.
          </p>
        )}
        {openTrialRecords.length > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm" data-testid="forward-trial-table">
              <thead>
                <tr className="text-left text-muted border-b border-gold/20">
                  <th className="pr-3 py-1">Hypothesis</th>
                  <th className="pr-3 py-1">Origin</th>
                  <th className="pr-3 py-1">Entry verdict</th>
                  <th className="pr-3 py-1">Position</th>
                  <th className="py-1">Projected time to measure</th>
                </tr>
              </thead>
              <tbody>
                {openTrialRecords.map((r) => {
                  const entry = entryByTrialId.get(r.trial_id);
                  return (
                    <tr key={r.trial_id} data-testid="forward-trial-row" className="border-b border-gold/10">
                      <td className="pr-3 py-1 text-parchment">{r.source_hypothesis_ref.hypothesis_name}</td>
                      <td className="pr-3 py-1 text-muted">{r.source_hypothesis_ref.origin_agent}</td>
                      <td className="pr-3 py-1 text-muted">{String(r.entry_verdict.verdict ?? "—")}</td>
                      <td className="pr-3 py-1" data-testid="forward-trial-position">
                        {entry ? (
                          <span className={entry.direction === "LONG" ? "text-teal" : "text-loss"}>
                            OPEN {entry.direction ?? ""} @ {entry.entry_price?.toFixed(4) ?? "n/a"}
                          </span>
                        ) : (
                          <span className="text-muted">Waiting — no entry yet</span>
                        )}
                      </td>
                      <td className="py-1 text-muted">{r.projected_time_to_min_sample_label}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Repair: diagnosed failures, retried once</h2>
        <p className="text-muted mt-2">
          A DIED hypothesis can be repaired — but only by a human explicitly invoking the
          process, never automatically. An LLM diagnoses the aggregate failure (never
          re-shown the raw data an original run already used), proposes exactly one
          bounded modification, and that modification is retested on genuinely fresh data
          it has never touched before — capped at 4 attempts per hypothesis. A repair
          that passes enters Forward Trial with its full lineage intact, traceable back to
          its original DIED ancestor. A repair that still fails stays in the Graveyard.
        </p>
        <p className="text-parchment mt-2">
          <strong>{repairChainCount}</strong> repair chains have been opened
          {statusIsLive ? "." : " — this count is not yet reporting live (see above)."}
        </p>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Has anything survived?</h2>
        <p className="text-muted mt-2">
          Honestly: not yet, by the strictest reading. Across every completed Adam run,{" "}
          <strong>{adamSurvived}</strong> hypotheses have reached SURVIVED and{" "}
          <strong>{adamPromisingWatchlist}</strong> have reached PROMISING-WATCHLIST (both
          numbers read live from the same file this site&apos;s Research Agent panel
          shows). Eve&apos;s own hypotheses have not reached a combined SURVIVED or
          PROMISING-WATCHLIST verdict either, as of this writing — though several
          individual in-sample or out-of-sample halves have shown a positive signal that
          didn&apos;t hold up on the other half, which is exactly the kind of result this
          project&apos;s own train/test discipline exists to catch rather than hide. This
          page will be updated with real examples the first time that changes — until
          then, an honest zero is the correct number to show, not a reason to wait to
          publish this page.
        </p>
      </section>
    </div>
  );
}
