import Link from "next/link";
import { notFound } from "next/navigation";
import EquityCurveChart from "@/components/EquityCurveChart";
import TierBadge from "@/components/TierBadge";
import { formatTimestamp } from "@/components/LedgerTable";
import {
  fetchLedgerFull,
  fetchStats,
  fetchStrategies,
  fetchStrategyDescriptions,
} from "@/lib/data";
import { buildEquityCurve } from "@/lib/equityCurve";
import { findEntryByStrategyId } from "@/lib/strategyId";
import { classifyTier } from "@/lib/tier";
import { buildTradeHistory, type ResolvedTrade, type TradeResult } from "@/lib/tradeHistory";

export const revalidate = 300;

const REPO_BLOB_BASE = "https://github.com/jvmg7nmf6n-hue/project-nero-vatican/blob/main";

const FALLBACK_DESCRIPTION = "A written description for this strategy hasn't been added yet.";

const RESULT_STYLES: Record<TradeResult, string> = {
  win: "text-teal",
  loss: "text-loss",
  flat: "text-muted",
};

interface StatTileProps {
  label: string;
  value: string;
}

function StatTile({ label, value }: StatTileProps) {
  return (
    <div className="rounded-lg border border-gold/40 px-4 py-3 text-center">
      <div className="font-serif text-2xl text-parchment">{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}

function TradeRow({ trade }: { trade: ResolvedTrade }) {
  return (
    <tr className="border-b border-muted/10">
      <td className="py-2 pr-4">
        {formatTimestamp(trade.entryTimestamp)}
        {trade.entryPrice !== null ? ` @ ${trade.entryPrice}` : ""}
      </td>
      <td className="py-2 pr-4">
        {formatTimestamp(trade.exitTimestamp)}
        {trade.exitPrice !== null ? ` @ ${trade.exitPrice}` : ""}
      </td>
      <td className={`py-2 pr-4 font-medium ${RESULT_STYLES[trade.result]}`}>
        {trade.result.toUpperCase()}
      </td>
      <td className="py-2 pr-4">{trade.rMultiple !== null ? `${trade.rMultiple.toFixed(2)}R` : "n/a"}</td>
    </tr>
  );
}

export default async function StrategyDetailPage({ params }: { params: { id: string } }) {
  const [strategiesExport, statsExport, ledgerExport, descriptions] = await Promise.all([
    fetchStrategies(),
    fetchStats(),
    fetchLedgerFull(),
    fetchStrategyDescriptions(),
  ]);

  const roster = strategiesExport?.strategies ?? [];
  const entry = findEntryByStrategyId(roster, params.id);

  if (!entry) {
    notFound();
  }

  const tier = classifyTier(entry.verification_status);
  const description = descriptions?.[entry.name] ?? FALLBACK_DESCRIPTION;

  const statsRow = (statsExport?.strategies ?? []).find(
    (s) => s.strategy === entry.name && s.strategy_version === entry.version && s.asset === entry.asset
  );
  const trades = buildTradeHistory(entry, ledgerExport?.rows ?? []);
  const hasResolvedTrades = (statsRow?.resolved_trades ?? 0) > 0;
  const equityCurve = hasResolvedTrades ? buildEquityCurve(trades) : null;

  return (
    <div className="flex flex-col gap-10">
      <Link href="/" className="text-sm text-muted hover:text-parchment">
        &larr; Back to all strategies
      </Link>

      <section>
        <h1 className="font-serif text-3xl text-parchment">{entry.name}</h1>
        <p className="text-muted mt-1">
          {entry.asset} &middot; {entry.timeframe}
        </p>
        <div className="mt-3">
          <TierBadge tier={tier} />
        </div>
        <p className="mt-4 max-w-2xl text-parchment">{description}</p>
      </section>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-4">Performance summary</h2>
        {!statsRow || statsRow.resolved_trades <= 0 ? (
          <p data-testid="performance-awaiting" className="text-muted">
            Awaiting first signal &mdash; no resolved trades yet.
          </p>
        ) : (
          <div data-testid="performance-summary" className="grid grid-cols-2 sm:grid-cols-4 gap-4 max-w-2xl">
            <StatTile label="Resolved trades" value={String(statsRow.resolved_trades)} />
            <StatTile
              label="Win rate"
              value={statsRow.win_rate !== null ? `${(statsRow.win_rate * 100).toFixed(1)}%` : "n/a"}
            />
            <StatTile
              label="Avg return"
              value={statsRow.avg_return_pct !== null ? `${statsRow.avg_return_pct.toFixed(2)}%` : "n/a"}
            />
            <StatTile
              label="Expectancy (R)"
              value={statsRow.expectancy_r !== null ? statsRow.expectancy_r.toFixed(3) : "n/a"}
            />
          </div>
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-4">Equity curve</h2>
        {!equityCurve ? (
          <p data-testid="equity-curve-awaiting" className="text-muted">
            Awaiting first trade for chart.
          </p>
        ) : (
          <EquityCurveChart curve={equityCurve} />
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-4">Trade history</h2>
        {trades.length === 0 ? (
          <p data-testid="trade-history-empty" className="text-muted">
            No resolved trades to show yet.
          </p>
        ) : (
          <div data-testid="trade-history-table" className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-muted border-b border-muted/30">
                  <th className="py-2 pr-4">Entry</th>
                  <th className="py-2 pr-4">Exit</th>
                  <th className="py-2 pr-4">Result</th>
                  <th className="py-2 pr-4">R-multiple</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, index) => (
                  <TradeRow key={`${trade.entryTimestamp}-${trade.exitTimestamp}-${index}`} trade={trade} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-2">Backtest evidence</h2>
        {entry.source_report ? (
          <a
            href={`${REPO_BLOB_BASE}/${entry.source_report}`}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-teal underline"
          >
            View the original research report
          </a>
        ) : (
          <p data-testid="no-source-report" className="text-muted text-sm">
            No backtest report available for this configuration.
          </p>
        )}
      </section>
    </div>
  );
}
