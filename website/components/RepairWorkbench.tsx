import type { RepairCandidate } from "@/lib/types";

const STATUS_LABELS: Record<RepairCandidate["status"], string> = {
  candidate: "Candidate",
  testing: "Testing",
  watchlist: "Watchlist",
  promoted: "Promoted",
};

// Hardcoded per the Day 6/7 task's own instruction: this lineage is already
// fully documented across docs/rmr_variant_research_*.md and
// docs/ranging_regime_batch_r{1,2,3}_*.md -- re-deriving it from JSON would
// just re-encode the same four already-committed reports.
const RMR_LINEAGE = [
  {
    label: "RANGE_MEAN_REVERSION v1.0.0 (base)",
    detail: "GOLD/1week & SILVER/1week reached watchlist; every other config DIED.",
  },
  {
    label: "Variant research, Stage 1-4",
    detail:
      "4 variants vs fresh baselines: BTC/1d long-only + confirmation reached watchlist (LOW SAMPLE); EUR/USD long-only and ETH adx-falling stayed DIED. Nothing promoted.",
  },
  {
    label: "R1 — REGIME_TRANSITION",
    detail: "New strategy testing the range-ending transition itself. 3/14 watchlist, all LOW SAMPLE. Not promoted.",
  },
  {
    label: "R2 — RANGE_MATURITY gate",
    detail:
      "ADX<25-for-N-candles gate bolted onto v1.0.0. Never rescued a DIED config; worsened GOLD/1week, RMR's own best result. Not promoted.",
  },
  {
    label: "R3 — REGIME_ALLOCATOR",
    detail:
      "ADX-gating applied to already-live survivors (GOLD/1week, BNB/12h). Neither config's classification changed. Not promoted.",
  },
];

export interface RepairWorkbenchProps {
  candidates: RepairCandidate[];
}

export default function RepairWorkbench({ candidates }: RepairWorkbenchProps) {
  return (
    <div data-testid="repair-workbench" className="flex flex-col gap-8">
      <div data-testid="rmr-lineage">
        <h3 className="font-serif text-lg text-parchment mb-2">
          Worked example: RANGE_MEAN_REVERSION lineage
        </h3>
        <p className="text-muted text-sm mb-3">
          The most-diagnosed family in the graveyard — a base strategy, one variant-research
          cycle, and three ranging-regime follow-ups, none promoted to live yet.
        </p>
        <ol className="flex flex-col gap-2">
          {RMR_LINEAGE.map((step, index) => (
            <li key={step.label} data-testid="rmr-lineage-step" className="flex gap-3 text-sm">
              <span className="text-muted">{index + 1}.</span>
              <div>
                <span className="text-parchment">{step.label}</span>
                <span className="text-muted"> — {step.detail}</span>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <div>
        <h3 className="font-serif text-lg text-parchment mb-2">Active repair candidates</h3>
        {candidates.length === 0 ? (
          <p data-testid="repair-candidates-empty" className="text-muted">
            No repair candidates registered yet.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {candidates.map((candidate) => (
              <div
                key={candidate.hypothesis_name}
                data-testid="repair-candidate-card"
                data-status={candidate.status}
                className="rounded-lg border border-gold/30 bg-ink p-4"
              >
                <h4 className="font-serif text-parchment">{candidate.hypothesis_name}</h4>
                <p className="text-muted text-xs mt-1">Parent: {candidate.parent_strategy}</p>
                <p className="mt-2 text-sm text-loss">{candidate.diagnosis}</p>
                <p className="mt-2 text-sm text-teal">{candidate.proposed_fix}</p>
                <span className="mt-3 inline-block rounded-full border border-gold/40 px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                  {STATUS_LABELS[candidate.status]}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
