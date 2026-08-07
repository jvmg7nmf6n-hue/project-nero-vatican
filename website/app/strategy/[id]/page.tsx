import Link from "next/link";
import { notFound } from "next/navigation";
import BacktestEvaluationPanel from "@/components/BacktestEvaluationPanel";
import ChartDescription from "@/components/ChartDescription";
import ChartTabs from "@/components/ChartTabs";
import ChatBot from "@/components/ChatBot";
import EquityCurveChart from "@/components/EquityCurveChart";
import MarketStatusWidget from "@/components/MarketStatusWidget";
import QuantPanel from "@/components/QuantPanel";
import TierBadge from "@/components/TierBadge";
import { formatTimestamp } from "@/components/LedgerTable";
import { candleFileTimeframe } from "@/lib/candleData";
import { buildChartDescription } from "@/lib/chartDescription";
import { buildChartMarkers } from "@/lib/chartMarkers";
import { buildFaqEntries } from "@/lib/chatFaq";
import {
  fetchCandleData,
  fetchLedgerFull,
  fetchLedgerRecent,
  fetchQuantCrossAsset,
  fetchQuantMetrics,
  fetchStats,
  fetchStrategies,
  fetchStrategyDescriptions,
} from "@/lib/data";
import { buildEquityCurve } from "@/lib/equityCurve";
import {
  formatPrice,
  latestPrice,
  mapSignalStateToMarketStatus,
  priceChangePercent,
} from "@/lib/marketStatus";
import { deriveProvenanceLine } from "@/lib/provenance";
import { findVolatilityRegime } from "@/lib/quantCrossAsset";
import { findQuantMetricsForAsset } from "@/lib/quantPanel";
import { deriveSignalState, SIGNAL_STATE_LABELS } from "@/lib/signalState";
import { findEntryByStrategyId } from "@/lib/strategyId";
import { classifyTier } from "@/lib/tier";
import { computeTradeFrequency } from "@/lib/tradeFrequency";
import { buildTradeHistory, type ResolvedTrade, type TradeResult } from "@/lib/tradeHistory";
import { DEFAULT_BACKTEST_EVALUATION, type StrategyChatContext } from "@/lib/types";

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
  const [strategiesExport, statsExport, ledgerExport, ledgerRecentExport, descriptions, quantMetricsExport, quantCrossAssetExport] =
    await Promise.all([
      fetchStrategies(),
      fetchStats(),
      fetchLedgerFull(),
      fetchLedgerRecent(),
      fetchStrategyDescriptions(),
      fetchQuantMetrics(),
      fetchQuantCrossAsset(),
    ]);

  const roster = strategiesExport?.strategies ?? [];
  const entry = findEntryByStrategyId(roster, params.id);

  if (!entry) {
    notFound();
  }

  const tier = classifyTier(entry.verification_status);
  const provenanceLine = deriveProvenanceLine(entry, statsExport?.strategies ?? []);
  // 2026-08-03 production incident: a currently-fetched export can genuinely
  // lack backtest_evaluation entirely (see DEFAULT_BACKTEST_EVALUATION's own
  // comment in lib/types.ts) -- never read entry.backtest_evaluation directly.
  const backtestEvaluation = entry.backtest_evaluation ?? DEFAULT_BACKTEST_EVALUATION;
  const description = descriptions?.[entry.name] ?? null;

  const statsRow = (statsExport?.strategies ?? []).find(
    (s) => s.strategy === entry.name && s.strategy_version === entry.version && s.asset === entry.asset
  );
  const trades = buildTradeHistory(entry, ledgerExport?.rows ?? []);
  const hasResolvedTrades = (statsRow?.resolved_trades ?? 0) > 0;
  const equityCurve = hasResolvedTrades ? buildEquityCurve(trades) : null;
  const tradeFrequency = computeTradeFrequency(ledgerExport?.rows ?? [], entry.name, entry.version, entry.asset);

  // Pair strategies (BTC-ETH, GOLD-SILVER) have no single price series -- Day 1's
  // export pipeline deliberately skips them (see nero_core/execution/
  // export_candle_data.py's module docstring) -- so there's no candle file to look
  // up and no "Price Chart" tab to offer; equity-curve-only, exactly as before.
  const isPairAsset = entry.asset.includes("-");
  const candleResult = isPairAsset ? null : await fetchCandleData(entry.asset, entry.timeframe);
  const candles = candleResult?.status === "ok" ? candleResult.data.candles : null;
  const priceChartUnavailableReason =
    candleResult?.status === "error" ? "error" : candleResult?.status === "not_found" ? "missing" : null;
  const markers = candles ? buildChartMarkers(trades, candles) : [];

  // Per-asset(+timeframe), not per-strategy -- see lib/quantPanel.ts's own
  // docstring for why two strategies sharing this same pair correctly resolve to
  // the identical entry, rather than showing two different panels.
  const quantMetricsEntry = findQuantMetricsForAsset(quantMetricsExport?.metrics ?? [], entry.asset, entry.timeframe);

  // Day 7 Live Market Status Widget -- all derived from data already fetched
  // above for other panels (candles, quant_cross_asset.json); only the signal
  // state below is new (added for ChatBot's current_signal) and is reused here
  // rather than recomputed. Skipped entirely for pair assets (BTC-ETH,
  // GOLD-SILVER), same as the price chart -- "current price" and "next candle"
  // don't have a single-asset meaning for a two-leg pair.
  const signalState = deriveSignalState(entry, ledgerRecentExport?.rows ?? []);
  const marketSignalStatus = mapSignalStateToMarketStatus(signalState);
  const price = candles ? latestPrice(candles) : null;
  const priceDisplay = price !== null ? formatPrice(entry.asset, price) : null;
  const changePercent = candles ? priceChangePercent(candles) : null;
  const lastCandleTimeSeconds = candles && candles.length > 0 ? candles[candles.length - 1].time : null;
  const regimeEntry = isPairAsset
    ? null
    : findVolatilityRegime(
        quantCrossAssetExport?.volatility_regimes ?? [],
        entry.asset,
        candleFileTimeframe(entry.timeframe)
      );

  // Day 7 Chart Description -- only meaningful alongside an actual candlestick
  // chart (non-pair asset with a real candle file). Reuses quantMetricsEntry
  // (already fetched above for the Quant Panel) for its time-span estimate --
  // no new data source.
  const chartDescriptionData =
    !isPairAsset && candles
      ? buildChartDescription({
          asset: entry.asset,
          timeframe: entry.timeframe,
          candleCount: candles.length,
          periodsPerYear: quantMetricsEntry?.periods_per_year ?? null,
          statsRow: statsRow ?? null,
        })
      : null;

  // Day 7 ChatBot -- FAQ answers are computed server-side from data already on
  // this page (never fetched by the client). Live chat is enabled only when the
  // server has ANTHROPIC_API_KEY configured; process.env is read here (a Server
  // Component) and only the resulting boolean crosses into the client bundle --
  // see app/api/chat/route.ts's own header comment for the server-only rule.
  const faqEntries = buildFaqEntries(entry, description, statsRow ?? null);
  const hasLiveChat = Boolean(process.env.ANTHROPIC_API_KEY);
  const strategyChatContext: StrategyChatContext = {
    strategy_name: entry.name,
    asset: entry.asset,
    timeframe: entry.timeframe,
    mechanism: description?.mechanism ?? "No description has been written for this strategy yet.",
    verification_note: description?.verification_note ?? "Not yet verified.",
    win_rate: statsRow?.win_rate ?? null,
    current_signal: SIGNAL_STATE_LABELS[signalState],
  };

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
        <p data-testid="provenance-line" className="mt-1 text-xs text-muted">
          {provenanceLine}
        </p>
        {description ? (
          <div data-testid="strategy-description" className="mt-4 max-w-2xl">
            <p className="text-parchment">{description.mechanism}</p>
            <p className="mt-2 text-sm text-muted">{description.verification_note}</p>
          </div>
        ) : (
          <p data-testid="strategy-description-fallback" className="mt-4 max-w-2xl text-muted">
            {FALLBACK_DESCRIPTION}
          </p>
        )}
        {description?.entry_rule || description?.exit_rule ? (
          <div data-testid="strategy-rules" className="mt-4 max-w-2xl grid gap-3 sm:grid-cols-2">
            {description.entry_rule ? (
              <div className="rounded-lg border border-gold/30 bg-ink p-3">
                <h3 className="text-xs uppercase tracking-wide text-muted mb-1">Entry rule</h3>
                <p className="text-sm text-parchment">{description.entry_rule}</p>
              </div>
            ) : null}
            {description.exit_rule ? (
              <div className="rounded-lg border border-gold/30 bg-ink p-3">
                <h3 className="text-xs uppercase tracking-wide text-muted mb-1">Exit rule</h3>
                <p className="text-sm text-parchment">{description.exit_rule}</p>
              </div>
            ) : null}
          </div>
        ) : (
          <p data-testid="strategy-rules-fallback" className="mt-4 max-w-2xl text-muted text-sm">
            The exact entry/exit rule detail for this strategy hasn&apos;t been transcribed onto this page yet
            &mdash; see the mechanism description above for the general approach.
          </p>
        )}
      </section>

      {!isPairAsset ? (
        <MarketStatusWidget
          priceDisplay={priceDisplay}
          changePercent={changePercent}
          regime={regimeEntry}
          lastCandleTimeSeconds={lastCandleTimeSeconds}
          timeframe={entry.timeframe}
          signalStatus={marketSignalStatus}
        />
      ) : null}

      <section>
        <h2 className="font-serif text-xl text-parchment mb-4">Performance summary</h2>
        {!statsRow || (statsRow.resolved_trades <= 0 && (statsRow.unverified_trades ?? 0) <= 0) ? (
          <p data-testid="performance-awaiting" className="text-muted">
            Awaiting first signal &mdash; no resolved trades yet.
          </p>
        ) : statsRow.resolved_trades <= 0 ? (
          <p data-testid="performance-pending-verification" className="text-muted">
            {statsRow.unverified_trades} trade{statsRow.unverified_trades === 1 ? "" : "s"} pending source
            verification &mdash; not enough confirmed data to report a performance number yet.
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
        <h2 className="font-serif text-xl text-parchment mb-4">Trade frequency</h2>
        {tradeFrequency.sinceIso === null ? (
          <p data-testid="frequency-unknown" className="text-muted text-sm">
            No ledger history exists yet for this configuration.
          </p>
        ) : tradeFrequency.ratePerYear !== null ? (
          <p data-testid="frequency-measured" className="text-parchment text-sm">
            Real measured rate: <strong>{tradeFrequency.ratePerYear.toFixed(1)} trades/year</strong>, extrapolated
            from {tradeFrequency.entryCount} real entries over {tradeFrequency.spanDays!.toFixed(1)} real days
            (since {formatTimestamp(tradeFrequency.sinceIso)}) &mdash; a short observation window, not yet a
            stable long-run average.
          </p>
        ) : (
          <p data-testid="frequency-zero" className="text-muted text-sm">
            {tradeFrequency.entryCount} trade{tradeFrequency.entryCount === 1 ? "" : "s"} since going live on{" "}
            {formatTimestamp(tradeFrequency.sinceIso)}
            {tradeFrequency.entryCount === 0
              ? " — not enough real activity yet to estimate a frequency."
              : " — a single entry isn't enough to estimate a rate yet."}
          </p>
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-4">
          {isPairAsset ? "Equity curve" : "Charts"}
        </h2>
        {isPairAsset ? (
          !equityCurve ? (
            <p data-testid="equity-curve-awaiting" className="text-muted">
              Awaiting first trade for chart.
            </p>
          ) : (
            <EquityCurveChart curve={equityCurve} />
          )
        ) : (
          <ChartTabs
            candles={candles}
            markers={markers}
            equityCurve={equityCurve}
            priceChartUnavailableReason={priceChartUnavailableReason}
          />
        )}
        {!isPairAsset && chartDescriptionData ? <ChartDescription data={chartDescriptionData} /> : null}
      </section>

      <QuantPanel entry={quantMetricsEntry} />

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
        <div className="mb-3">
          <BacktestEvaluationPanel evaluation={backtestEvaluation} />
        </div>
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

      <ChatBot faqEntries={faqEntries} strategyContext={strategyChatContext} hasLiveChat={hasLiveChat} />
    </div>
  );
}
