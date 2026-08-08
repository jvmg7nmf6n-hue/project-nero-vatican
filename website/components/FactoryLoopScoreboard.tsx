import Link from "next/link";
import type { FactoryLoopScoreboard as ScoreboardData } from "@/lib/types";

// CC-1 directive, 2026-08-08: the glanceable summary the owner asked for --
// "what has the factory loop actually done recently, how many hypotheses
// went through Repair Lab and came out healthy, how many are ACTIVE right
// now vs merely LIVE/tracked, how many strategies total." Every number here
// is read directly from docs/site_data/factory_loop_scoreboard.json (see
// nero_core/execution/export_factory_loop_scoreboard.py's own docstring for
// the full real-data reasoning behind each field) -- this component never
// recomputes or guesses any of it.

function StatTile({ label, value, sub, href }: { label: string; value: React.ReactNode; sub?: string; href?: string }) {
  const inner = (
    <div className="rounded-lg border border-gold/30 bg-ink p-4 h-full">
      <p className="text-[10px] uppercase tracking-wide text-muted">{label}</p>
      <p className="text-2xl text-parchment font-serif mt-1">{value}</p>
      {sub ? <p className="text-xs text-muted mt-1">{sub}</p> : null}
    </div>
  );
  return href ? (
    <a href={href} className="block hover:opacity-90">
      {inner}
    </a>
  ) : (
    inner
  );
}

function timeAgo(iso: string, now: Date): string {
  const diffMs = now.getTime() - new Date(iso).getTime();
  const hours = diffMs / (1000 * 60 * 60);
  if (hours < 1) return "less than an hour ago";
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function FactoryLoopScoreboard({ scoreboard, now = new Date() }: { scoreboard: ScoreboardData | null; now?: Date }) {
  if (!scoreboard) {
    return (
      <section data-testid="factory-loop-scoreboard-unavailable" className="rounded-lg border border-loss/30 bg-ink p-4">
        <p className="text-muted text-sm">
          Scoreboard data is not available right now — the underlying export hasn&apos;t run yet, or the fetch
          failed. Nothing below is estimated or guessed to fill the gap.
        </p>
      </section>
    );
  }

  const totalLive = scoreboard.live_scheduler.tracked_count + scoreboard.forward_trial.tracked_count;
  const totalActive =
    scoreboard.live_scheduler.active_count + (scoreboard.forward_trial.active_count ?? 0);

  return (
    <section data-testid="factory-loop-scoreboard" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h2 className="font-serif text-xl text-parchment">Scoreboard</h2>
        <p className="text-xs text-muted">Live as of {new Date(scoreboard.last_updated).toUTCString()}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Currently ACTIVE (open position)"
          value={totalActive}
          sub={`of ${totalLive} tracked — most tracked strategies are flat most of the time, by design`}
        />
        <StatTile
          label="Forward Trial"
          value={`${scoreboard.forward_trial.active_count ?? "—"} active / ${scoreboard.forward_trial.tracked_count} tracked`}
          sub={`Adam ${scoreboard.forward_trial.by_origin.adam ?? 0} · Eve ${scoreboard.forward_trial.by_origin.eve ?? 0} · repaired ${scoreboard.forward_trial.by_origin.repaired ?? 0}`}
        />
        <StatTile
          label="Live-scheduler strategies"
          value={`${scoreboard.live_scheduler.active_count} active / ${scoreboard.live_scheduler.tracked_count} tracked`}
        />
        <StatTile label="Graveyard" value={scoreboard.graveyard.count} sub="mechanism families killed" href="/graveyard" />
      </div>

      {/* Repair Lab -- manual candidates and automated chains are DELIBERATELY
          two separate tiles, never merged into one number (see the export
          script's own module docstring: they are structurally different
          systems, and merging them would misattribute one system's real
          result to the other). */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div data-testid="repair-lab-manual" className="rounded-lg border border-gold/20 bg-ink/60 p-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Repair Lab — manual candidates</p>
          <p className="text-lg text-parchment mt-1">
            {scoreboard.repair_lab.manual_candidates.count} on file, {scoreboard.repair_lab.manual_candidates.launchable_count}{" "}
            launchable right now
          </p>
          <p className="text-xs text-muted mt-1">
            Hand-curated <code>repair_candidates.json</code> entries — a different system from the automated chains
            below. {scoreboard.repair_lab.manual_candidates.launchable_count === 0 ? "None currently resolve to a real Adam/Eve parent hypothesis." : ""}
          </p>
        </div>
        <div data-testid="repair-lab-automated" className="rounded-lg border border-gold/20 bg-ink/60 p-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Repair Lab — automated chains</p>
          <p className="text-lg text-parchment mt-1">
            {scoreboard.repair_lab.automated_chains.count} launched, {scoreboard.repair_lab.automated_chains.healthy_count} healthy
            (SURVIVED/PROMISING-WATCHLIST)
          </p>
          <p className="text-xs text-muted mt-1">
            {scoreboard.repair_lab.automated_chains.open_chains} open, {scoreboard.repair_lab.automated_chains.resolved_chains} resolved.{" "}
            {scoreboard.repair_lab.automated_chains.healthy_count === 0 && scoreboard.repair_lab.automated_chains.count > 0
              ? "An honest zero — real chains exist, none have resolved healthy yet."
              : null}
          </p>
          {scoreboard.repair_lab.automated_chains.chains.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {scoreboard.repair_lab.automated_chains.chains.map((c) => (
                <li key={c.repair_chain_id} className="text-xs text-muted">
                  <span className="text-parchment">{c.original_hypothesis_name}</span> — {c.chain_status}
                  {c.attempts.map((a) => ` (${a.attempt_id}: ${a.status})`).join("")}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Recent activity -- "what has the factory loop actually done
          recently," the owner's own original complaint this whole section
          exists to answer. */}
      <div data-testid="factory-loop-recent-activity" className="rounded-lg border border-gold/20 bg-ink/60 p-4">
        <p className="text-[10px] uppercase tracking-wide text-muted mb-2">Recent activity</p>
        {scoreboard.recent_activity.length === 0 ? (
          <p className="text-muted text-sm">No recent runs on file yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {scoreboard.recent_activity.map((e, i) => (
              <li key={i} className="text-xs flex items-start gap-2">
                <span className={`rounded px-1.5 py-0.5 uppercase tracking-wide shrink-0 ${e.source === "adam" ? "bg-teal/20 text-teal" : "bg-gold/20 text-gold"}`}>
                  {e.source}
                </span>
                <span className="text-muted">
                  {timeAgo(e.at, now)} — {e.summary}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
