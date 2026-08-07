import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import SectionHeader from "@/components/SectionHeader";
import { fetchMacroReads } from "@/lib/data";
import { TABLE_BODY_CELL, TABLE_BODY_ROW, TABLE_HEADER_CELL, TABLE_HEADER_ROW } from "@/lib/designTokens";
import {
  AGENT_DISPLAY_NAMES,
  AGENT_REAL_DATA_SOURCE,
  conflictedFlags,
  flagsForAsset,
  latestReadForAsset,
  provenanceCounts,
} from "@/lib/macroReads";
import type { DataProvenanceLabel, MacroReadRecord } from "@/lib/types";

export const revalidate = 300;

export const metadata = {
  title: "Macro — Vatican",
};

// CC-1 Part E. Honest framing (E4): NOT "AI Macro Intelligence" -- a
// partially-wired macro engine (Bellwether, vendored in vatican/bellwether/)
// with a small, growing number of real inputs, shown transparently. Most of
// its 15 agents are still synthetic (random.uniform mock draws) -- that is
// disclosed prominently below, not hidden behind a confident-looking number.
const PROVENANCE_COLOR: Record<DataProvenanceLabel, string> = {
  real: "text-teal",
  mixed: "text-gold",
  synthetic: "text-muted",
  unavailable: "text-loss",
};

const BIAS_COLOR: Record<string, string> = {
  STRONG_BULLISH: "text-teal",
  BULLISH: "text-teal",
  NEUTRAL: "text-muted",
  BEARISH: "text-loss",
  STRONG_BEARISH: "text-loss",
};

function AssetReadCard({ asset, read }: { asset: "GOLD" | "BITCOIN"; read: MacroReadRecord | null }) {
  if (!read) {
    return (
      <Panel>
        <h3 className="font-serif text-lg text-parchment">{asset}</h3>
        <p data-testid={`macro-read-unavailable-${asset}`} className="text-muted text-sm mt-2">
          No macro read yet for {asset}. The overlay job hasn&apos;t run, or every
          contributing agent came back synthetic-only this cycle (Bellwether&apos;s
          circuit breaker fails silent and open in that case — no read is recorded
          rather than one built on nothing real).
        </p>
      </Panel>
    );
  }

  const counts = provenanceCounts(read.provenance_breakdown);
  const lowCoverage = read.coverage < 0.15;

  return (
    <Panel tone={asset === "GOLD" ? "gold" : "teal"}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-serif text-lg text-parchment">{asset}</h3>
        <span className="text-xs text-muted">
          {new Date(read.timestamp).toISOString().replace("T", " ").slice(0, 16)} UTC
        </span>
      </div>
      <div className={`mt-2 text-2xl font-serif ${BIAS_COLOR[read.bias] ?? "text-muted"}`}>{read.bias}</div>
      {read.bias === "NEUTRAL" && lowCoverage ? (
        <p className="text-loss text-xs mt-1">
          Neutral because coverage is low ({(read.coverage * 100).toFixed(0)}%) — this is an
          under-covered read, not a considered market view.
        </p>
      ) : null}
      <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-muted text-xs">Agreement</div>
          <div className="text-parchment">{(read.agreement * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-muted text-xs">Coverage</div>
          <div className={lowCoverage ? "text-loss" : "text-parchment"}>{(read.coverage * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-muted text-xs">P(up)</div>
          <div className="text-parchment">{(read.probability_up * 100).toFixed(0)}%</div>
        </div>
      </div>
      <div className="mt-3 text-xs text-muted">
        {counts.real} real · {counts.mixed} mixed · {counts.synthetic} synthetic
        {counts.unavailable > 0 ? ` · ${counts.unavailable} unavailable` : ""} of {counts.total} agents
      </div>
    </Panel>
  );
}

function ProvenanceTable({ read }: { read: MacroReadRecord }) {
  const rows = Object.entries(read.provenance_breakdown);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className={TABLE_HEADER_ROW}>
            <th className={TABLE_HEADER_CELL}>Agent</th>
            <th className={TABLE_HEADER_CELL}>Provenance</th>
            <th className={TABLE_HEADER_CELL}>Real data source (when real/mixed)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([agent, provenance]) => (
            <tr key={agent} className={TABLE_BODY_ROW}>
              <td className={`${TABLE_BODY_CELL} text-parchment`}>{AGENT_DISPLAY_NAMES[agent] ?? agent}</td>
              <td className={`${TABLE_BODY_CELL} ${PROVENANCE_COLOR[provenance]} uppercase text-xs`}>
                {provenance}
              </td>
              <td className={`${TABLE_BODY_CELL} text-muted text-xs`}>
                {provenance === "real" || provenance === "mixed" ? AGENT_REAL_DATA_SOURCE[agent] ?? "—" : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function MacroPage() {
  const macroReadsExport = await fetchMacroReads();
  const reads = macroReadsExport?.macro_reads ?? [];
  const flags = macroReadsExport?.conflict_flags ?? [];

  const goldRead = latestReadForAsset(reads, "GOLD");
  const btcRead = latestReadForAsset(reads, "BITCOIN");
  const btcFlags = flagsForAsset(flags, "BTC");
  const btcConflicts = conflictedFlags(btcFlags);

  const history = [...reads].sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        eyebrow="Bellwether — partially wired"
        title="Macro"
        description="A macro-intelligence engine (Bellwether) with a small, growing number of REAL
          inputs, shown transparently — not an 'AI macro intelligence' framing while most of its
          15 agents are still synthetic. Every read below discloses exactly which agents were
          real, mixed, or synthetic that cycle, named individually. Used to annotate — never
          resize, skip, or suppress — ORDERFLOW_IMBALANCE/BTC entries when the two disagree."
      />

      {reads.length === 0 ? (
        <p data-testid="macro-page-unavailable" className="text-muted text-sm">
          No macro read has been recorded yet — the overlay job (
          <code className="text-xs">.github/workflows/bellwether_overlay.yml</code>, every 8h)
          hasn&apos;t run, or every attempt has hit the circuit breaker. Nothing is fabricated in
          its place.
        </p>
      ) : (
        <>
          <section>
            <SectionHeader
              title="Current read"
              description="Gold and BTC, most recent Bellwether cycle."
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <AssetReadCard asset="GOLD" read={goldRead} />
              <AssetReadCard asset="BITCOIN" read={btcRead} />
            </div>
          </section>

          {btcRead ? (
            <section>
              <SectionHeader
                title="Provenance breakdown (BTC)"
                description="Of Bellwether's 15 agents, exactly which ones fed this BTC read with real
                data this cycle — the most honest thing on this page. Most macro tools show a
                number and hide where it came from."
              />
              <ProvenanceTable read={btcRead} />
            </section>
          ) : null}

          {btcRead ? (
            <section>
              <SectionHeader title="Reasoning, risks, alternative scenarios (BTC)" />
              <Panel>
                <p className="text-parchment text-sm">{btcRead.reasoning || "No reasoning text this cycle."}</p>
                {btcRead.risks.length > 0 ? (
                  <ul className="mt-3 text-sm text-muted list-disc list-inside">
                    {btcRead.risks.map((risk, i) => (
                      <li key={i}>{risk}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-muted text-xs mt-3">No risks flagged this cycle.</p>
                )}
                {btcRead.alternative_scenarios.length > 0 ? (
                  <div className="mt-4 grid gap-2 sm:grid-cols-3">
                    {btcRead.alternative_scenarios.map((s) => (
                      <div key={s.name} className="rounded-md border border-muted/20 p-3 text-xs">
                        <div className="text-parchment font-medium">
                          {s.name} ({(s.probability * 100).toFixed(0)}%)
                        </div>
                        <div className="text-muted mt-1">
                          Gold {s.gold_bias} · BTC {s.btc_bias}
                        </div>
                        <div className="text-muted mt-1">{s.narrative}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </Panel>
            </section>
          ) : null}

          <section>
            <SectionHeader
              title="ORDERFLOW_IMBALANCE/BTC macro-conflict annotations"
              description={`${btcConflicts.length} of ${btcFlags.length} evaluated entries flagged
              macro_conflicted so far. Annotate-only — never resizes, skips, or suppresses a
              trade.`}
            />
            {btcFlags.length === 0 ? (
              <p data-testid="macro-conflicts-empty" className="text-muted text-sm">
                No ORDERFLOW_IMBALANCE/BTC entries have been evaluated yet.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className={TABLE_HEADER_ROW}>
                      <th className={TABLE_HEADER_CELL}>Entry direction</th>
                      <th className={TABLE_HEADER_CELL}>Status</th>
                      <th className={TABLE_HEADER_CELL}>Conflicted?</th>
                      <th className={TABLE_HEADER_CELL}>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {btcFlags.slice(0, 20).map((flag) => (
                      <tr key={flag.execution_log_id} className={TABLE_BODY_ROW}>
                        <td className={`${TABLE_BODY_CELL} text-parchment`}>{flag.entry_direction ?? "n/a"}</td>
                        <td className={`${TABLE_BODY_CELL} text-muted text-xs`}>{flag.status}</td>
                        <td className={`${TABLE_BODY_CELL} ${flag.conflicted ? "text-loss" : "text-muted"}`}>
                          {flag.conflicted ? "Yes" : "No"}
                        </td>
                        <td className={`${TABLE_BODY_CELL} text-muted text-xs max-w-md`}>{flag.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {btcFlags.length > 20 ? (
                  <p className="text-muted text-xs mt-2">Showing the most recent 20 of {btcFlags.length}.</p>
                ) : null}
              </div>
            )}
            <p className="text-muted text-xs mt-2">
              See the flagged trades themselves on the{" "}
              <Link href="/#ledger" className="underline">
                Truth Ledger
              </Link>
              .
            </p>
          </section>

          <section>
            <SectionHeader
              title="History"
              description="Every macro read ever recorded, most recent first — grows as the overlay
              job (every 8h) accumulates more cycles."
            />
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className={TABLE_HEADER_ROW}>
                    <th className={TABLE_HEADER_CELL}>Timestamp</th>
                    <th className={TABLE_HEADER_CELL}>Asset</th>
                    <th className={TABLE_HEADER_CELL}>Bias</th>
                    <th className={TABLE_HEADER_CELL}>Agreement</th>
                    <th className={TABLE_HEADER_CELL}>Coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {history.slice(0, 30).map((r) => (
                    <tr key={`${r.run_id}-${r.asset}`} className={TABLE_BODY_ROW}>
                      <td className={`${TABLE_BODY_CELL} text-muted text-xs`}>
                        {new Date(r.timestamp).toISOString().replace("T", " ").slice(0, 16)}
                      </td>
                      <td className={`${TABLE_BODY_CELL} text-parchment`}>{r.asset}</td>
                      <td className={`${TABLE_BODY_CELL} ${BIAS_COLOR[r.bias] ?? "text-muted"}`}>{r.bias}</td>
                      <td className={TABLE_BODY_CELL}>{(r.agreement * 100).toFixed(0)}%</td>
                      <td className={TABLE_BODY_CELL}>{(r.coverage * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {history.length < 5 ? (
                <p data-testid="macro-history-sparse" className="text-muted text-xs mt-2">
                  Only {history.length} cycle{history.length === 1 ? "" : "s"} recorded so far —
                  too early to show a meaningful trend. This will fill in as the overlay job runs.
                </p>
              ) : null}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
