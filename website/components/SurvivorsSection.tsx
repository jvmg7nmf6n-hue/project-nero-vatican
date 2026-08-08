import Link from "next/link";
import SurvivorDistanceBar from "./SurvivorDistanceBar";
import { daysLive, formatDaysLive, SURVIVORS, SURVIVORS_FRAMING_LINE, type SurvivorMeta } from "@/lib/survivors";
import { buildStrategyId } from "@/lib/strategyId";
import type { SurvivorDistanceExport } from "@/lib/types";

const REPO_BLOB_BASE = "https://github.com/jvmg7nmf6n-hue/project-nero-vatican/blob/main";

// B2e: ORDERFLOW_IMBALANCE's own real active-trades / real-frequency page --
// the other half of the honest picture (a strategy that HAS taken real
// trades, shown with its own real, short-window-disclosed frequency figure).
const ORDERFLOW_IMBALANCE_STRATEGY_PATH = "/strategy/orderflow-imbalance--btc--orderflow-imbalance-v1-0-0";

function SurvivorCard({ meta, now, distanceEntry }: { meta: SurvivorMeta; now: Date; distanceEntry: SurvivorDistanceExport["distances"][number] | undefined }) {
  const strategyId = buildStrategyId({ name: meta.name, asset: meta.asset, version: meta.version });
  const days = daysLive(meta.liveSinceIso, now);

  return (
    <div data-testid="survivor-card" className="rounded-lg border-2 border-teal/70 bg-ink p-4 flex flex-col gap-3">
      <div>
        <h3 className="font-serif text-lg text-parchment">{meta.name}</h3>
        <p className="text-muted text-sm">
          {meta.asset} &middot; {meta.timeframe}
        </p>
        <p className="mt-1 text-xs text-teal">{meta.verificationStatus}</p>
      </div>

      {/* Backtest metrics, clearly labeled as backtest -- B2d: never presented
          as a live/current performance claim. */}
      <div data-testid="survivor-backtest-metrics" className="text-xs text-muted">
        <p className="text-parchment text-[10px] uppercase tracking-wide mb-1">Backtest (historical, not live)</p>
        <p>
          Train: N={meta.train.n}, {meta.train.winPct}% win, {meta.train.expectancyR.toFixed(3)} ExpR, PF{" "}
          {meta.train.profitFactor.toFixed(2)}
        </p>
        <p>
          Test: N={meta.test.n}, {meta.test.winPct}% win, {meta.test.expectancyR.toFixed(3)} ExpR, PF{" "}
          {meta.test.profitFactor.toFixed(2)}
        </p>
      </div>

      {/* Live status -- B2b/B2d: the real, current, honest fact stated plainly,
          never softened or omitted. */}
      <div data-testid="survivor-live-status" className="text-xs">
        <p className="text-parchment">{formatDaysLive(days)}</p>
        <p className="text-gold mt-0.5">0 live entries yet</p>
      </div>

      {/* Live distance-to-trigger -- B3: real, present-tense only, per
          condition, never combined, never a time prediction. */}
      {distanceEntry ? (
        <div data-testid="survivor-distance-conditions" className="flex flex-col gap-2 border-t border-muted/20 pt-3">
          <p className="text-[10px] uppercase tracking-wide text-muted">
            Live distance to entry (as of {new Date(distanceEntry.computed_at).toUTCString()})
          </p>
          {distanceEntry.conditions.map((c) => (
            <SurvivorDistanceBar key={c.label} condition={c} />
          ))}
        </div>
      ) : (
        <p data-testid="survivor-distance-unavailable" className="text-xs text-muted border-t border-muted/20 pt-3">
          Live distance data unavailable right now.
        </p>
      )}

      <div className="mt-1 flex flex-wrap gap-3 text-xs">
        <Link href={`/strategy/${strategyId}`} className="text-teal underline">
          Strategy detail
        </Link>
        <a
          href={`${REPO_BLOB_BASE}/${meta.sourceReport}`}
          target="_blank"
          rel="noreferrer"
          className="text-teal underline"
        >
          Verification report
        </a>
      </div>
    </div>
  );
}

export default function SurvivorsSection({
  survivorDistance,
  now = new Date(),
}: {
  survivorDistance: SurvivorDistanceExport | null;
  now?: Date;
}) {
  const distancesByStrategy = new Map(
    (survivorDistance?.distances ?? []).map((d) => [d.strategy_id, d])
  );

  return (
    <section data-testid="survivors-section">
      <h2 className="font-serif text-2xl text-parchment mb-2">The verified survivors</h2>
      <p className="text-muted text-sm mb-4">{SURVIVORS_FRAMING_LINE}</p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SURVIVORS.map((meta) => (
          <SurvivorCard key={meta.name + meta.asset} meta={meta} now={now} distanceEntry={distancesByStrategy.get(meta.name)} />
        ))}
      </div>
      <p className="mt-4 text-xs text-muted">
        For a strategy that HAS taken real trades, with its own real (short-window) frequency figure, see{" "}
        <Link href={ORDERFLOW_IMBALANCE_STRATEGY_PATH} className="text-teal underline">
          ORDERFLOW_IMBALANCE&apos;s live activity
        </Link>
        .
      </p>
    </section>
  );
}
