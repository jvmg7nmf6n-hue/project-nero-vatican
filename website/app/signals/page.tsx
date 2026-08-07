import CandlestickChart from "@/components/CandlestickChart";
import Panel from "@/components/Panel";
import PageHeader from "@/components/PageHeader";
import { fetchCandleData, fetchTrialEntries } from "@/lib/data";
import type { ChartMarker } from "@/lib/chartMarkers";
import type { TrialEntry } from "@/lib/types";

export const revalidate = 300;

export const metadata = {
  title: "Signals — Vatican",
};

// CC-1 Part D6/D6a. A "signal" here is a genuine Forward Trial ENTRY -- an
// execution_log row (in data/repair_lab_forward_tracking.db) with strategy
// TRIAL:<trial_id> and signal_type ENTRY, meaning a Trial record actually
// transitioned from flat to an open position. This is deliberately NOT the
// same as a hypothesis merely being ADMITTED to Trial (ForwardTrialRecord's
// own status=="OPEN"/opened_at fields, shown elsewhere on /factory-loop) --
// see nero_core/execution/export_trial_entries.py's own module docstring
// for the full definition and the real, confirmed distinction (10 Trial
// admissions exist today; only 1 has ever produced a real ENTRY).
function entryMarker(entry: TrialEntry): ChartMarker[] {
  if (entry.entry_price === null) return [];
  const isLong = entry.direction === "LONG";
  return [{
    time: Math.floor(entry.candle_timestamp / 1000),
    position: isLong ? "belowBar" : "aboveBar",
    color: isLong ? "#2ec4b6" : "#d47a6a",
    shape: isLong ? "arrowUp" : "arrowDown",
    text: `ENTRY ${entry.direction ?? ""}`.trim(),
  }];
}

export default async function SignalsPage() {
  const trialEntriesExport = await fetchTrialEntries();
  const entries = [...(trialEntriesExport?.entries ?? [])].reverse(); // most recent first

  const candleResults = await Promise.all(
    entries.map((entry) => (entry.timeframe ? fetchCandleData(entry.asset, entry.timeframe) : Promise.resolve({ status: "not_found" as const })))
  );

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        eyebrow="Forward Trial"
        title="Signals"
        description="Every real Forward Trial ENTRY, as it opened — not a hypothesis merely being
          admitted to Trial, a genuine transition to an open position. Most Trial admissions
          have never fired one; this feed only shows the ones that did."
      />

      {entries.length === 0 ? (
        <p data-testid="signals-empty" className="text-muted text-sm">
          No Forward Trial has opened a real position yet. Every admitted hypothesis is
          watching; none have fired an entry so far — an honest zero, not a loading state.
        </p>
      ) : (
        <div className="flex flex-col gap-8">
          {entries.map((entry, i) => {
            const candleResult = candleResults[i];
            const candles = candleResult.status === "ok" ? candleResult.data.candles : null;
            return (
              <Panel key={entry.execution_log_id} tone={entry.direction === "LONG" ? "teal" : "loss"}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="font-serif text-xl text-parchment">
                    {entry.hypothesis_name ?? entry.trial_id}
                  </h2>
                  <span className="text-xs text-muted">
                    {new Date(entry.timestamp).toISOString().replace("T", " ").slice(0, 16)} UTC
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
                  <span>
                    Asset: <span className="text-parchment">{entry.asset}</span>
                  </span>
                  <span>
                    Direction:{" "}
                    <span className={entry.direction === "LONG" ? "text-teal" : "text-loss"}>
                      {entry.direction ?? "n/a"}
                    </span>
                  </span>
                  <span>
                    Entry: <span className="text-parchment">{entry.entry_price?.toFixed(4) ?? "n/a"}</span>
                  </span>
                  {entry.stop_loss !== null ? (
                    <span>
                      Stop: <span className="text-parchment">{entry.stop_loss.toFixed(4)}</span>
                    </span>
                  ) : null}
                  {entry.target !== null ? (
                    <span>
                      Target: <span className="text-parchment">{entry.target.toFixed(4)}</span>
                    </span>
                  ) : null}
                  <span>
                    Origin: <span className="text-parchment">{entry.origin_agent ?? "unknown"}</span>
                  </span>
                </div>

                <div className="mt-4">
                  {candles && candles.length > 0 ? (
                    <CandlestickChart
                      candles={candles}
                      markers={entryMarker(entry)}
                      overlays={{ ma: true, ema: true }}
                    />
                  ) : (
                    <p data-testid="signal-chart-unavailable" className="text-muted text-xs">
                      Price chart coming soon for {entry.asset}
                      {entry.timeframe ? `/${entry.timeframe}` : ""}.
                    </p>
                  )}
                </div>
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}
