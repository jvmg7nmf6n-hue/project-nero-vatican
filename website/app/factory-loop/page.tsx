import FactoryLoopDiagram from "@/components/FactoryLoopDiagram";
import { fetchAgentPerformance, fetchFactoryLoopStatus, fetchGraveyard } from "@/lib/data";

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
export default async function FactoryLoopPage() {
  const [graveyard, factoryLoopStatus, agentPerformance] = await Promise.all([
    fetchGraveyard(),
    fetchFactoryLoopStatus(),
    fetchAgentPerformance(),
  ]);

  const graveyardCount = graveyard?.length ?? 0;
  const forwardTrialCount = factoryLoopStatus?.forward_trial.count ?? 0;
  const repairChainCount = factoryLoopStatus?.repair.count ?? 0;
  const statusIsLive = factoryLoopStatus !== null;

  const adamSurvived = agentPerformance?.cumulative.survived ?? 0;
  const adamPromisingWatchlist = agentPerformance?.cumulative.promising_watchlist ?? 0;

  return (
    <div className="prose-vatican max-w-2xl">
      <h1 className="font-serif text-3xl text-parchment">Factory Loop</h1>
      <p className="text-muted mt-2">
        How a trading idea moves through this project, end to end: proposed, tested,
        and either watched forward or retired — honestly, with every stage labeled by
        whether it is live today or still just designed.
      </p>

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
