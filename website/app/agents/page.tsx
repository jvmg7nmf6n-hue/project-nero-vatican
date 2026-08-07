import LearningCurveSection from "@/components/LearningCurveSection";
import PageHeader from "@/components/PageHeader";
import {
  computeAdamFunnel,
  computeEveCrashStats,
  computeEveDslGapRate,
  computeEveFunnel,
  computeEveSessionCostStats,
  computePreRegistrationProgress,
  extractFrequencyClaims,
  PRE_REGISTERED_SESSION_COUNT,
} from "@/lib/agentsPage";
import {
  fetchAgentPerformance,
  fetchAgentRunSummaries,
  fetchEveBudgetLedger,
  fetchEveHypotheses,
  fetchEveSessionRecord,
  fetchEveSessionRegistry,
  fetchForwardTrial,
} from "@/lib/data";
import type { AgentFunnel } from "@/lib/agentsPage";
import {
  computeAdamHypothesisQuality,
  computeAdamReliability,
  computeEveHypothesisQuality,
  computeEveReliability,
  computeNearMissFunnel,
} from "@/lib/learningCurve";
import type { EveSessionRecord, EveSessionRegistryEntry } from "@/lib/types";

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

// CC-1 directive, item 5a: the strongest evidence this project has that its
// own bar is real, not decorative — a random-hypothesis baseline run against
// every pair in the search universe, scored by the EXACT SAME harness a real
// Adam/Eve hypothesis goes through. Static data, not live-fetched: these are
// five completed, one-time investigations (K=200 each), not something that
// changes run to run, so hardcoding the real, already-committed numbers here
// matches this site's own /methodology "static-prose" convention rather than
// building a live export pipeline for numbers that will not move. Source,
// verbatim, re-read directly from each file this directive (2026-08-06):
// docs/investigations/{btc,eth,sol,paxg}_4h_random_baseline_result.json and
// docs/investigations/btc_24h_random_baseline_result.json, each file's own
// verdict_counts field.
const RANDOM_BASELINES = [
  { asset: "BTC", timeframe: "4h", k: 200, survived: 0, promisingWatchlist: 0, died: 69, skipped: 131 },
  { asset: "BTC", timeframe: "24h", k: 200, survived: 0, promisingWatchlist: 0, died: 64, skipped: 136 },
  { asset: "ETH", timeframe: "4h", k: 200, survived: 0, promisingWatchlist: 3, died: 63, skipped: 134 },
  { asset: "SOL", timeframe: "4h", k: 200, survived: 0, promisingWatchlist: 0, died: 70, skipped: 130 },
  { asset: "PAXG", timeframe: "4h", k: 200, survived: 0, promisingWatchlist: 8, died: 63, skipped: 129 },
] as const;
const RANDOM_BASELINE_TOTAL_K = RANDOM_BASELINES.reduce((sum, b) => sum + b.k, 0);
const RANDOM_BASELINE_TOTAL_SURVIVED = RANDOM_BASELINES.reduce((sum, b) => sum + b.survived, 0);

function RandomBaselinePanel() {
  return (
    <section data-testid="random-baseline-panel" className="rounded-lg border border-gold/40 bg-ink p-5">
      <h2 className="font-serif text-xl text-parchment mb-3">The random baselines</h2>
      <p className="text-parchment text-lg">
        {RANDOM_BASELINE_TOTAL_SURVIVED} SURVIVED out of {RANDOM_BASELINE_TOTAL_K} random hypotheses
      </p>
      <p className="text-muted text-sm mt-2">
        Before trusting any real Adam/Eve hypothesis that clears this project&apos;s own bar, we asked: how often does a
        completely random entry rule clear it by chance alone? {RANDOM_BASELINE_TOTAL_K} randomly-generated hypotheses
        (K=200 per pair, five baselines across every pair in the current research universe) were scored through the
        exact same harness — same train/test split, same MIN_SAMPLE_SIZE, same bootstrap CI, same SURVIVED bar — as a
        real proposal. Zero cleared it. This is the number that makes the bar real rather than decorative: a bar
        nothing random can pass by luck is a bar that means something when a real hypothesis does clear it.
      </p>
      <ul className="mt-3 flex flex-col gap-1 text-sm">
        {RANDOM_BASELINES.map((b) => (
          <li key={`${b.asset}-${b.timeframe}`} className="text-muted">
            <span className="text-parchment">
              {b.asset}/{b.timeframe}
            </span>{" "}
            (K={b.k}): {b.survived} SURVIVED, {b.promisingWatchlist} PROMISING-WATCHLIST, {b.died} DIED, {b.skipped}{" "}
            SKIPPED (too rare to measure)
          </li>
        ))}
      </ul>
      <p className="text-muted text-xs mt-3">
        PROMISING-WATCHLIST occurring by chance (11 of {RANDOM_BASELINE_TOTAL_K}, concentrated in ETH/4h and PAXG/4h)
        is expected and honest — it is the SURVIVED bar specifically (adequate sample AND a bootstrap CI that clears
        zero on both halves) that no random hypothesis reached, in any of the five baselines.
      </p>
    </section>
  );
}

// CC-1 directive, "Detailed Adam/Eve briefing": real, traced mechanism only
// -- every claim below cites the file/function that implements it. Static
// prose (like /factory-loop's own "Who proposes ideas" section), because
// this describes CODE STRUCTURE, not a number that moves run to run; the
// numbers that DO move (DSL gap rate, crash count, cost) are computed live
// below in MeasuredCharacteristicsSection, not here.
function HowItWorksSection() {
  return (
    <section data-testid="how-it-works" className="flex flex-col gap-6">
      <h2 className="font-serif text-2xl text-parchment">How Adam and Eve actually work</h2>
      <p className="text-muted text-sm">
        Not a marketing description — the real control flow, traced from the code that runs today.
      </p>

      <div className="rounded-lg border border-gold/30 bg-ink p-5">
        <h3 className="font-serif text-lg text-parchment mb-2">Adam (nero_core/research_agent/)</h3>
        <p className="text-muted text-sm">
          Adam runs on two independent channels, both feeding the same shared pipeline. The{" "}
          <span className="text-parchment">scanner-triggered channel</span> turns each real statistical anomaly this
          project&apos;s own scanner finds in already-exported market data — an extreme z-score, a regime transition,
          a correlation breakdown, thin strategy coverage on a pair — into one Claude call proposing a hypothesis for
          it, up to 10 calls per run (<code>hypothesis_gen.py</code>&apos;s <code>DEFAULT_MAX_CALLS_PER_RUN</code>).
          The <span className="text-parchment">web-search channel</span> is separate and unconditional — it runs up
          to 3 times per run regardless of what the scanner finds, each call letting Claude search the web (up to 5
          searches per call) for a real documented strategy idea — an academic paper, published research, a known
          technical pattern — and adapt it to one of this project&apos;s tracked pairs. Both channels share the same
          streamed API call and the same JSON-parsing path into a plain hypothesis record; a record that resembles a
          known-dead mechanism is flagged, never silently discarded. Every hypothesis, from either channel, is then
          checked against the frequency gate before it ever reaches a backtest (see &quot;The shared harness&quot;
          below). Adam&apos;s run itself is human-triggered only — the GitHub Actions workflow that runs it has no
          schedule, only manual dispatch.
        </p>
        <p className="text-muted text-sm mt-3">
          A real, previously-shipped fix worth naming: Adam&apos;s prompts once hand-listed which data fields a
          hypothesis could reference, and drifted out of sync with the DSL&apos;s own real field list (the scanner
          prompt was missing <code>adx14</code>/<code>bb_lower</code>/<code>bb_upper</code>; the web-search prompt was
          missing <code>bb_lower</code>/<code>bb_upper</code>) — a mismatch that would silently reject a correct
          hypothesis as unmeasurable. Both prompts now interpolate the DSL&apos;s own <code>ALLOWED_FIELDS</code> list
          directly rather than hand-typing it, with a dedicated test (
          <code>test_research_agent_rule_dsl_prompt_sync.py</code>) asserting every field appears in both prompts —
          insurance against the same drift recurring.
        </p>
      </div>

      <div className="rounded-lg border border-gold/30 bg-ink p-5">
        <h3 className="font-serif text-lg text-parchment mb-2">Eve (nero_core/eve/)</h3>
        <p className="text-muted text-sm">
          Eve runs a multi-turn agentic session (up to 40 turns, a safety cap not a target) in which Claude freely
          chooses, turn by turn, whether to search the web, propose a hypothesis, or end the session — there is no
          fixed order and no cap on how many hypotheses she proposes (zero is a valid, honest answer). A real,
          honest correction worth stating plainly: this project once described Eve as always searching before
          proposing anything. Checked directly against three real sessions&apos; own turn-by-turn logs, that held for
          only one of them — the other two genuinely interleaved searching and proposing across turns. The accurate
          claim is that she is free to do either, and has been observed doing both.
        </p>
        <p className="text-muted text-sm mt-3">
          A proposed hypothesis can optionally declare <code>derived_from</code> a specific earlier hypothesis (by
          name) — validated against real known hypothesis names, with all four required fields (what changed, why)
          or none. A validly-declared refinement is tagged <span className="text-teal">REFINEMENT</span> and stays
          inside this project&apos;s statistical (FDR) correction family; an unrelated, undeclared near-duplicate is
          tagged <code>SELF_DERIVATIVE</code> and is excluded from it instead — declaring one real parent does not
          launder a different, unrelated similarity. At the start of each session Eve is also given a real
          &quot;near-miss&quot; list (shipped, session 2 onward): hypotheses that survived in-sample but haven&apos;t
          yet been confirmed out-of-sample, presented explicitly as an invitation to refine, not a verdict. (A
          separate &quot;proven-mechanism&quot; context channel was checked for directly in the code and not
          found — it is not part of what Eve sees today, and is not claimed here.)
        </p>
        <p className="text-muted text-sm mt-3">
          Every session is budget-checked before every single turn, not just at the start: a hard $1.50 per-session
          cap and a hard $20/month ceiling, both enforced in code, neither configurable via an environment variable
          that could silently raise them. When a session ends — normally or by crashing — the full record (every
          turn, every tool call, every hypothesis) is written to its own file; a crash writes everything produced up
          to that point rather than losing it. A session only counts toward the pre-registered 8-session evaluation
          if it produced at least one hypothesis that was actually eligible to be scored against real data — an
          unscoreable session is treated as an unknown, never as a measured zero.
        </p>
      </div>

      <div className="rounded-lg border border-gold/20 bg-ink/60 p-5">
        <h3 className="font-serif text-lg text-parchment mb-2">The shared harness</h3>
        <p className="text-muted text-sm">
          Every hypothesis from either agent runs through the exact same pipeline: DSL validation, then a frequency
          gate that rejects anything that would fire too rarely to ever measure — before either agent&apos;s
          proposal ever reaches a backtest — then a chronological train/test backtest with a percentile bootstrap
          confidence interval, then a verdict. <span className="text-parchment">SURVIVED</span> requires positive
          expectancy on both the train and test half, at least 20 trades on each, and a bootstrap CI that clears
          zero on both — anything short of that but still positive on both halves is{" "}
          <span className="text-parchment">PROMISING-WATCHLIST</span>, not SURVIVED. DSL validity alone — not the
          backtest verdict — is what gates admission to Forward Trial; a DIED hypothesis can still be tracked
          forward, because the backtest verdict is a label, not a gate. See the{" "}
          <a href="/factory-loop" className="underline">
            Factory Loop
          </a>{" "}
          page for the full pipeline diagram and the{" "}
          <a href="/methodology" className="underline">
            methodology page
          </a>{" "}
          for how the bootstrap CI and verdict categories work — not repeated here to avoid two descriptions drifting
          apart.
        </p>
      </div>
    </section>
  );
}

interface CharacteristicEntry {
  text: React.ReactNode;
}

function CharacteristicQuadrant({ title, accent, entries }: { title: string; accent: string; entries: CharacteristicEntry[] }) {
  return (
    <div className="rounded-lg border border-gold/20 bg-ink/60 p-4">
      <h4 className={`font-serif text-sm uppercase tracking-wide mb-2 ${accent}`}>{title}</h4>
      <ul className="flex flex-col gap-2">
        {entries.map((e, i) => (
          <li key={i} className="text-muted text-xs leading-relaxed">
            {e.text}
          </li>
        ))}
      </ul>
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

// CC-1 directive, "Detailed Adam/Eve briefing": renamed away from "SWOT" per
// the directive's own instruction -- every entry here must be a real
// mechanism (cited) or a real measured number (live where the source file
// supports it, dated where it's a one-time historical measurement that
// isn't machine-readable). Never a narrative trait claim.
function MeasuredCharacteristicsSection({
  progress,
  eveDslGap,
  eveCrash,
  eveSessionCost,
  adamUntestableCount,
  adamHypothesesGenerated,
  adamLastUpdatedLabel,
  eveMostRecentSessionId,
}: {
  progress: ReturnType<typeof computePreRegistrationProgress>;
  eveDslGap: ReturnType<typeof computeEveDslGapRate>;
  eveCrash: ReturnType<typeof computeEveCrashStats>;
  eveSessionCost: ReturnType<typeof computeEveSessionCostStats>;
  adamUntestableCount: number;
  adamHypothesesGenerated: number;
  adamLastUpdatedLabel: string;
  eveMostRecentSessionId: string | null;
}) {
  return (
    <section data-testid="measured-characteristics" className="flex flex-col gap-6">
      <h2 className="font-serif text-2xl text-parchment">Measured characteristics</h2>
      <p className="text-muted text-sm">
        Not personality traits — every entry below is either a described real mechanism or a real number, with its
        source. Nothing here is a subjective judgment about which agent is &quot;better.&quot;
      </p>

      <div>
        <h3 className="font-serif text-lg text-parchment mb-3">Adam</h3>
        <p className="text-muted text-xs mb-2">Numbers below as of {adamLastUpdatedLabel} (agent_performance.json).</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CharacteristicQuadrant
            title="Strengths"
            accent="text-teal"
            entries={[
              {
                text: (
                  <>
                    The ALLOWED_FIELDS/prompt-sync mechanism (above) prevents a real, previously-shipped bug class —
                    a prompt referencing a field the DSL doesn&apos;t recognize — from recurring, guarded by a
                    dedicated test. <code>hypothesis_gen.py</code>, <code>test_research_agent_rule_dsl_prompt_sync.py</code>.
                  </>
                ),
              },
              {
                text: (
                  <>
                    {adamUntestableCount} of {adamHypothesesGenerated} of Adam&apos;s real hypotheses on file have
                    ever been rejected for a DSL-vocabulary gap — read live from{" "}
                    <code>agent_performance.json</code>&apos;s <code>cumulative.untestable</code> field.
                  </>
                ),
              },
              {
                text: (
                  <>
                    Unknown-cost calls are tracked and disclosed, never folded into the recorded total — see the Cost
                    section above ({progress.adamUnknownCount} such call{progress.adamUnknownCount === 1 ? "" : "s"}
                    {" "}on file right now).
                  </>
                ),
              },
            ]}
          />
          <CharacteristicQuadrant
            title="Weaknesses"
            accent="text-loss"
            entries={[
              {
                text: (
                  <>
                    No dollar cap of any kind on the web-search channel — only call-count caps (3 requests × 5
                    searches per run). <code>hypothesis_gen.py</code>&apos;s own <code>cost_limit_hit</code> field is
                    a call-count limit despite its name; there is no cost-in-dollars limit anywhere in this module.
                    Eve, by contrast, has a hard $1.50/session and $20/month dollar ceiling (see Eve&apos;s panel).
                  </>
                ),
              },
              {
                text: (
                  <>
                    Real cumulative API cost: {formatUsd(progress.adamRecordedUsd)} recorded (
                    <code>agent_performance.json</code>, as of {adamLastUpdatedLabel}), plus{" "}
                    {progress.adamUnknownCount} call{progress.adamUnknownCount === 1 ? "" : "s"} of genuinely unknown
                    cost never included in that figure.
                  </>
                ),
              },
              {
                text: <>Run cadence is human-gated, not automatic — the workflow that runs Adam has no schedule, only manual dispatch (<code>.github/workflows/research_agent_manual.yml</code>).</>,
              },
            ]}
          />
          <CharacteristicQuadrant
            title="Opportunities"
            accent="text-gold"
            entries={[
              {
                text: (
                  <>
                    Macro-conditioned hypotheses (4 real fields — 10-year real yield, DXY, VIX, funding rate — being
                    wired into the DSL): real, substantial code exists as of this writing but is{" "}
                    <span className="text-parchment">not yet committed or live</span>. Nothing to report as shipped
                    yet — flagged here honestly rather than overstated.
                  </>
                ),
              },
            ]}
          />
          <CharacteristicQuadrant
            title="Risks going forward"
            accent="text-loss"
            entries={[
              {
                text: (
                  <>
                    The uncapped web-search dollar exposure (Weaknesses, left) is a standing forward risk, not just a
                    historical one — nothing in code stops a future run&apos;s search cost from rising.
                  </>
                ),
              },
            ]}
          />
        </div>
      </div>

      <div>
        <h3 className="font-serif text-lg text-parchment mb-3">Eve</h3>
        <p className="text-muted text-xs mb-2" data-testid="eve-characteristics-data-age">
          Eve&apos;s own data has no single last-updated stamp; the numbers below are current as of the most recent
          session attempt on file, {eveMostRecentSessionId ?? "none yet"}.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CharacteristicQuadrant
            title="Strengths"
            accent="text-teal"
            entries={[
              {
                text: (
                  <>
                    A hard $1.50/session and $20/month dollar cap, checked before every single turn, not just at
                    session start — neither is overridable in a way that could silently raise it.{" "}
                    <code>budget_ledger.py</code>.
                  </>
                ),
              },
              {
                text: (
                  <>
                    The REFINEMENT/SELF_DERIVATIVE mechanism (above) keeps a genuinely declared refinement inside the
                    statistical (FDR) correction family while excluding an undeclared near-duplicate — real
                    protection against both unfairly penalizing iteration and laundering a duplicate as if declared.{" "}
                    <code>scoring.py</code>.
                  </>
                ),
              },
              {
                text: (
                  <>
                    Real per-completed-session average cost:{" "}
                    {eveSessionCost.averageUsd !== null ? formatUsd(eveSessionCost.averageUsd) : "not yet reporting"}{" "}
                    across {eveSessionCost.completedSessionCount} completed session
                    {eveSessionCost.completedSessionCount === 1 ? "" : "s"} — well under the $1.50 cap, read live from{" "}
                    <code>eve_budget_ledger.json</code>.
                  </>
                ),
              },
            ]}
          />
          <CharacteristicQuadrant
            title="Weaknesses"
            accent="text-loss"
            entries={[
              {
                text: (
                  <>
                    Real DSL-vocabulary-gap rate: {eveDslGap.untestableCount} of {eveDslGap.totalCount} hypotheses on
                    file ({eveDslGap.ratePct !== null ? `${eveDslGap.ratePct.toFixed(1)}%` : "n/a"}), computed live
                    from <code>eve_hypotheses.json</code>. All from Eve&apos;s very first session, before a same-day
                    fix — zero since.
                  </>
                ),
              },
              {
                text: (
                  <>
                    Real crash history: {eveCrash.crashedCount} of {eveCrash.totalCount} recorded session attempts
                    crashed before completion, live from <code>eve_session_registry.json</code>. Honest timeline
                    check: the last crash predates this project&apos;s switch to a streaming API connection by about
                    a day and a half — a timeout-ceiling increase (60s→120s→180s) is the better-supported explanation
                    for why crashes stopped, and only one real session has run since streaming itself shipped. Not
                    enough data yet to credit streaming specifically — better-bounded, not proven closed.
                  </>
                ),
              },
              {
                text: (
                  <>
                    Search-then-propose ordering is not reliably front-loaded — of the sessions examined in detail,
                    only one front-loaded all searching before any proposal; the others interleaved. An observation
                    from real session logs, not a guaranteed protocol.
                  </>
                ),
              },
            ]}
          />
          <CharacteristicQuadrant
            title="Opportunities"
            accent="text-gold"
            entries={[
              {
                text: (
                  <>
                    The near-miss context channel (above) is real and already shipped, session 2 onward — a genuine
                    new inheritance source that grows with every additional countable session.
                  </>
                ),
              },
              {
                text: (
                  <>
                    Macro-conditioned hypotheses (same 4 real fields as Adam&apos;s panel): real, substantial code
                    exists as of this writing but is <span className="text-parchment">not yet committed or live</span>.
                  </>
                ),
              },
            ]}
          />
          <CharacteristicQuadrant
            title="Risks going forward"
            accent="text-loss"
            entries={[
              {
                text: (
                  <>
                    The pre-registration kill criterion, stated in advance:{" "}
                    if Eve doesn&apos;t clear 5% OOS survival across 8 countable sessions, the open-ended-agent branch
                    is archived. Real current progress: {progress.sessionsCounted} of {PRE_REGISTERED_SESSION_COUNT}{" "}
                    countable sessions, {progress.survivedCount} SURVIVED among them so far.
                  </>
                ),
              },
              {
                text: (
                  <>
                    {progress.eveUnknownCount} orphaned budget reservation{progress.eveUnknownCount === 1 ? "" : "s"}{" "}
                    ({formatUsd(progress.eveUnknownProjectedUsd)}) remain unreconciled — real dollar exposure sitting
                    in a reserved-but-not-confirmed state, live from <code>eve_budget_ledger.json</code>. See the Cost
                    section above for the full recorded-vs-unknown breakdown.
                  </>
                ),
              },
            ]}
          />
        </div>
      </div>
    </section>
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
  const eveDslGap = computeEveDslGapRate(hypotheses);
  const eveCrash = computeEveCrashStats(eveRegistry);
  const eveSessionCost = computeEveSessionCostStats(ledger, eveRegistry);
  const adamUntestableCount = adamPerformance?.cumulative.untestable ?? 0;
  const adamHypothesesGenerated = adamPerformance?.cumulative.hypotheses_generated ?? 0;
  const adamLastUpdatedLabel = adamPerformance?.last_updated ?? "not yet reporting";

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

  // CC-1 overnight directive, Part 1 (Learning Curve): only sessions NOT
  // classified as crashed_before_completion have a real auto-written
  // eve_sessions/<id>.json (the 6 real crashes predate that mechanism
  // entirely -- see lib/learningCurve.ts's own module docstring). Fetching
  // only those avoids wasted requests for files that are known never to
  // exist.
  const sessionIdsWithFiles = sessions.filter((s) => s.classification !== "crashed_before_completion").map((s) => s.session_id);
  const sessionRecordResults = await Promise.all(sessionIdsWithFiles.map((id) => fetchEveSessionRecord(id)));
  const sessionRecordsById = new Map<string, EveSessionRecord | null>(
    sessionIdsWithFiles.map((id, i) => [id, sessionRecordResults[i]])
  );

  const forwardTrialRecords = await fetchForwardTrial();
  const forwardTrialHypothesisNames = new Set(
    (forwardTrialRecords ?? []).map((r) => r.source_hypothesis_ref.hypothesis_name)
  );

  const eveReliability = computeEveReliability(eveRegistry, sessionRecordsById);
  const adamReliability = computeAdamReliability(adamPerformance);
  const eveQuality = computeEveHypothesisQuality(hypotheses);
  const adamQuality = computeAdamHypothesisQuality(adamPerformance);
  const nearMissFunnel = computeNearMissFunnel(hypotheses, forwardTrialHypothesisNames);
  const refinementTaggedCount = hypotheses.filter((h) => h.contamination_tags.some((t) => t.tag === "REFINEMENT")).length;

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        title="Agents"
        description={
          <>
            What Adam and Eve are actually doing, in real numbers read directly from the same files
            this project&apos;s own harness writes — including the sessions that crashed and produced
            nothing. See the{" "}
            <a href="/factory-loop" className="underline">
              Factory Loop
            </a>{" "}
            page for how a hypothesis moves through this system end to end.
          </>
        }
      />

      <HowItWorksSection />

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
        {eveRegistry?.pre_registration.kill_criterion && (
          <p data-testid="kill-criterion" className="text-muted text-xs mt-2 border-t border-gold/20 pt-2">
            The condition under which we&apos;d call this wrong, stated in advance:{" "}
            <span className="text-parchment">{eveRegistry.pre_registration.kill_criterion}</span>.
          </p>
        )}
      </section>

      <RandomBaselinePanel />

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

      <MeasuredCharacteristicsSection
        progress={progress}
        eveDslGap={eveDslGap}
        eveCrash={eveCrash}
        eveSessionCost={eveSessionCost}
        adamUntestableCount={adamUntestableCount}
        adamHypothesesGenerated={adamHypothesesGenerated}
        adamLastUpdatedLabel={adamLastUpdatedLabel}
        eveMostRecentSessionId={mostRecentSession?.session_id ?? null}
      />

      <LearningCurveSection
        eveReliability={eveReliability}
        adamReliability={adamReliability}
        eveQuality={eveQuality}
        adamQuality={adamQuality}
        nearMissFunnel={nearMissFunnel}
        refinementTaggedCount={refinementTaggedCount}
        totalHypothesesCount={hypotheses.length}
      />

      <section>
        <p className="text-muted text-xs">
          Last updated: Adam — {adamLastUpdatedLabel}. Eve&apos;s own session data has no
          single last-updated stamp; the most recent session attempt on file is{" "}
          {mostRecentSession?.session_id ?? "none yet"}.
        </p>
      </section>
    </div>
  );
}
