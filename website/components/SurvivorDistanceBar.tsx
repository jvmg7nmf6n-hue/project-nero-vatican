import type { SurvivorDistanceCondition } from "@/lib/types";

// CC-1 directive Part B3b: one condition's real, live, present-tense
// distance -- NEVER a combined/blended score (see export_survivor_distance.py's
// own docstring), NEVER a time-to-trigger prediction. Server-rendered only
// (no client JS, no animation of any kind) -- the bar's fill is a pure
// function of the real number already fetched at this page's own 300s
// revalidate cadence; it cannot update faster than that by construction.

// Display range per unit -- clamps the VISUAL bar only (for a genuinely
// extreme reading, the bar simply pins to full); the real numeric value is
// always printed as text regardless of the clamp, so nothing is ever hidden.
const DISPLAY_RANGE: Record<string, number> = {
  pct: 20,
  rsi_points: 30,
  z_units: 2.5,
};

function clampToUnitInterval(distance: number, range: number): number {
  return Math.max(-1, Math.min(1, distance / range));
}

export default function SurvivorDistanceBar({ condition }: { condition: SurvivorDistanceCondition }) {
  if (condition.unit === "boolean_state") {
    return (
      <div className="text-xs text-muted" data-testid="survivor-distance-boolean">
        <span className="text-parchment">{condition.label}</span>
        {condition.note ? <span className="block mt-0.5">{condition.note}</span> : null}
      </div>
    );
  }

  if (condition.distance === null) {
    return (
      <div className="text-xs text-muted" data-testid="survivor-distance-unavailable">
        <span className="text-parchment">{condition.label}</span>
        <span className="block mt-0.5">not yet computable — indicator undefined on the current data</span>
      </div>
    );
  }

  const range = DISPLAY_RANGE[condition.unit] ?? 20;
  const unitValue = clampToUnitInterval(condition.distance, range);
  const met = condition.distance >= 0;
  const fillPct = Math.abs(unitValue) * 50; // half-width fill from the center threshold marker
  const suffix = condition.unit === "pct" ? "%" : condition.unit === "z_units" ? "z" : " pts";

  return (
    <div data-testid="survivor-distance-bar" data-met={met}>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-parchment">{condition.label}</span>
        <span className={met ? "text-teal" : "text-loss"}>
          {condition.distance > 0 ? "+" : ""}
          {condition.distance}
          {suffix}
        </span>
      </div>
      <div className="relative mt-1 h-2 w-full rounded-full bg-muted/20">
        <div className="absolute left-1/2 top-0 h-2 w-px bg-muted/60" aria-hidden="true" />
        {met ? (
          <div
            className="absolute top-0 h-2 rounded-full bg-teal"
            style={{ left: "50%", width: `${fillPct}%` }}
          />
        ) : (
          <div
            className="absolute top-0 h-2 rounded-full bg-loss"
            style={{ right: "50%", width: `${fillPct}%` }}
          />
        )}
      </div>
      {condition.note ? <p className="mt-0.5 text-[10px] text-muted">{condition.note}</p> : null}
    </div>
  );
}
