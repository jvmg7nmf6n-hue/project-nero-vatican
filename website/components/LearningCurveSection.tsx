"use client";

import { useState } from "react";
import type { HypothesisQualityPoint, NearMissFunnel, ReliabilityPoint } from "@/lib/learningCurve";

type LearningCurveTab = "reliability" | "quality" | "near-miss";

const TAB_LABELS: Record<LearningCurveTab, string> = {
  reliability: "Reliability",
  quality: "Hypothesis Quality",
  "near-miss": "Near-Miss Pipeline",
};

export interface LearningCurveSectionProps {
  eveReliability: ReliabilityPoint[];
  adamReliability: ReliabilityPoint[];
  eveQuality: HypothesisQualityPoint[];
  adamQuality: HypothesisQualityPoint[];
  nearMissFunnel: NearMissFunnel;
  refinementTaggedCount: number;
  totalHypothesesCount: number;
}

function ReliabilityRow({ label, points }: { label: string; points: ReliabilityPoint[] }) {
  return (
    <div>
      <h4 className="text-sm text-parchment mb-2">
        {label} &mdash; {points.length} run{points.length === 1 ? "" : "s"} recorded
      </h4>
      {points.length === 0 ? (
        <p className="text-muted text-xs">No runs recorded yet.</p>
      ) : (
        <div className="flex flex-wrap gap-2" data-testid={`reliability-dots-${label.toLowerCase()}`}>
          {points.map((p) => (
            <div
              key={p.label}
              title={`${p.label} — ${p.crashed ? "crashed" : "completed"} (source: ${p.source})`}
              className={`h-3 w-3 rounded-full ${p.crashed ? "bg-loss" : "bg-teal"}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function QualityRow({ label, points }: { label: string; points: HypothesisQualityPoint[] }) {
  return (
    <div>
      <h4 className="text-sm text-parchment mb-2">{label}</h4>
      {points.length === 0 ? (
        <p className="text-muted text-xs">No sessions/runs with a real hypothesis on file yet.</p>
      ) : (
        <ul className="flex flex-col gap-1" data-testid={`quality-points-${label.toLowerCase()}`}>
          {points.map((p) => {
            const pct = p.totalCount > 0 ? (100 * p.untestableCount) / p.totalCount : 0;
            return (
              <li key={p.label} className="text-xs text-muted">
                <span className="text-parchment">{p.label}</span>: {p.untestableCount} of {p.totalCount} DSL-invalid (
                {pct.toFixed(0)}%)
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function FunnelStage({ label, count }: { label: string; count: number }) {
  return (
    <div className="rounded-lg border border-gold/30 bg-ink p-3 text-center flex-1">
      <div className="font-serif text-2xl text-parchment">{count}</div>
      <div className="text-xs uppercase tracking-wide text-muted mt-1">{label}</div>
    </div>
  );
}

export default function LearningCurveSection({
  eveReliability,
  adamReliability,
  eveQuality,
  adamQuality,
  nearMissFunnel,
  refinementTaggedCount,
  totalHypothesesCount,
}: LearningCurveSectionProps) {
  const [activeTab, setActiveTab] = useState<LearningCurveTab>("reliability");

  return (
    <section data-testid="learning-curve-section">
      <h2 className="font-serif text-2xl text-parchment mb-2">Learning Curve</h2>
      <p className="text-muted text-sm mb-4 max-w-2xl">
        These charts track how reliably and cleanly Adam and Eve operate over time &mdash; not a claim that either
        agent is getting &quot;smarter.&quot; No model weights update between sessions.
      </p>

      <div data-testid="learning-curve-tabs" className="mb-4 flex gap-2">
        {(Object.keys(TAB_LABELS) as LearningCurveTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            data-testid={`learning-curve-tab-${tab}`}
            aria-pressed={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded px-3 py-1 text-sm ${
              activeTab === tab ? "bg-gold/20 text-parchment border border-gold/40" : "text-muted border border-gold/10"
            }`}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {activeTab === "reliability" && (
        <div data-testid="learning-curve-reliability" className="grid gap-4 sm:grid-cols-2 max-w-2xl">
          <ReliabilityRow label="Eve" points={eveReliability} />
          <ReliabilityRow label="Adam" points={adamReliability} />
          <p className="text-muted text-xs sm:col-span-2">
            A red dot is a real crash/error; a teal dot completed cleanly. Eve&apos;s 6 real crashes on file
            (2026-08-03/04) predate this project&apos;s crash-safety mechanism and have no auto-written session file
            of their own &mdash; sourced instead from the session registry as a one-time, disclosed historical
            exception; every session since is sourced live from its own auto-written record.
          </p>
        </div>
      )}

      {activeTab === "quality" && (
        <div data-testid="learning-curve-quality" className="grid gap-4 sm:grid-cols-2 max-w-2xl">
          <QualityRow label="Eve" points={eveQuality} />
          <QualityRow label="Adam" points={adamQuality} />
          <p className="text-muted text-xs sm:col-span-2">
            Eve&apos;s entire visible change here is one same-day fix on 2026-08-03 (Session 0&apos;s 4/4
            DSL-invalid hypotheses, 0 of 17 since) &mdash; a step change, not a gradual trend. Adam has never
            produced a DSL-invalid hypothesis across any real run on file &mdash; a real, flat 0% line, shown
            honestly rather than omitted for being uninteresting.
          </p>
        </div>
      )}

      {activeTab === "near-miss" && (
        <div data-testid="learning-curve-near-miss" className="max-w-2xl">
          <div className="flex gap-3">
            <FunnelStage label="Near-miss" count={nearMissFunnel.nearMissCount} />
            <FunnelStage label="Refined" count={nearMissFunnel.referencedInDerivedFromCount} />
            <FunnelStage label="Forward Trial" count={nearMissFunnel.reachedForwardTrialCount} />
            <FunnelStage label="Survived" count={nearMissFunnel.survivedCount} />
          </div>
          <p className="text-muted text-xs mt-3">
            A plain count funnel, not a percentage &mdash; the real sample ({nearMissFunnel.nearMissCount} near-miss
            {nearMissFunnel.nearMissCount === 1 ? "" : "es"} on file: {nearMissFunnel.nearMissNames.join(", ") || "none"}
            ) is too small for a rate to mean anything yet. Refinement Rate itself is not charted this pass:{" "}
            {refinementTaggedCount} of {totalHypothesesCount} real hypotheses carry a REFINEMENT tag &mdash; still a
            single real case, not enough to show as a trend. Generation tracking is not shown here at all: this
            project has no generation-lineage concept under any name.
          </p>
        </div>
      )}
    </section>
  );
}
