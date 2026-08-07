import Link from "next/link";
import HeroStats from "@/components/HeroStats";
import LedgerTable from "@/components/LedgerTable";
import MarketsSection from "@/components/MarketsSection";
import Panel from "@/components/Panel";
import SectionHeader from "@/components/SectionHeader";
import SplashScreen from "@/components/SplashScreen";
import {
  fetchCandleData,
  fetchGraveyard,
  fetchHeartbeat,
  fetchLedgerRecent,
  fetchQuantCrossAsset,
  fetchSiteSummary,
  fetchStats,
  fetchStrategies,
} from "@/lib/data";
import { buildMarketAssetList, buildMarketTiles } from "@/lib/marketsOverview";

export const revalidate = 300;

export default async function HomePage({
  searchParams,
}: {
  searchParams?: { asset?: string };
}) {
  const [ledger, strategies, summary, graveyard, stats, heartbeat, quantCrossAsset] = await Promise.all([
    fetchLedgerRecent(),
    fetchStrategies(),
    fetchSiteSummary(),
    fetchGraveyard(),
    fetchStats(),
    fetchHeartbeat(),
    fetchQuantCrossAsset(),
  ]);

  const rows = ledger?.rows ?? [];
  const roster = strategies?.strategies ?? [];
  const graveyardEntries = graveyard ?? [];
  const strategyStats = stats?.strategies ?? [];
  // Set by /heatmap's "?asset=" tile links -- narrows the dashboard to one asset.
  const assetFilter = typeof searchParams?.asset === "string" ? searchParams.asset : null;

  // Markets Overview terminal (Day 3): one tile per distinct single asset, each
  // fetched independently -- fetchCandleData never throws (see lib/data.ts), so one
  // asset's fetch failing can never take down Promise.all or any other tile.
  const marketAssetSpecs = buildMarketAssetList(roster);
  const candleResults = await Promise.all(
    marketAssetSpecs.map((spec) => fetchCandleData(spec.asset, spec.timeframe))
  );
  const marketTiles = buildMarketTiles(marketAssetSpecs, candleResults, roster);

  return (
    <div className="flex flex-col gap-16">
      <SplashScreen />

      <HeroStats summary={summary} roster={roster} heartbeat={heartbeat} />

      <MarketsSection
        roster={roster}
        recentRows={rows}
        stats={strategyStats}
        tiles={marketTiles}
        volatilityRegimes={quantCrossAsset?.volatility_regimes ?? []}
        initialAssetFilter={assetFilter}
      />

      <section id="ledger">
        <SectionHeader title="Truth Ledger" />
        <LedgerTable rows={rows} trackingSince={summary?.tracking_since} />
      </section>

      <section>
        <Panel tone="loss" className="flex items-center justify-between gap-4">
          <div>
            <h2 className="font-serif text-xl text-parchment">The graveyard</h2>
            <p className="text-muted text-sm mt-1">
              {graveyardEntries.length} strategy famil
              {graveyardEntries.length === 1 ? "y" : "ies"} killed by the evidence so
              far.
            </p>
          </div>
          <Link
            href="/graveyard"
            className="rounded-md border border-gold/50 px-4 py-2 text-sm text-parchment hover:bg-gold/10 whitespace-nowrap"
          >
            View graveyard
          </Link>
        </Panel>
      </section>
    </div>
  );
}
