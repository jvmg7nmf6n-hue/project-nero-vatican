import Link from "next/link";
import PageHeader from "@/components/PageHeader";
import { buildAssetHeatmap, heatmapTileColor } from "@/lib/assetHeatmap";
import { fetchStats, fetchStrategies } from "@/lib/data";

export const revalidate = 300;

export const metadata = {
  title: "Asset Heatmap — Vatican",
};

export default async function HeatmapPage() {
  const [strategiesExport, statsExport] = await Promise.all([fetchStrategies(), fetchStats()]);
  const roster = strategiesExport?.strategies ?? [];
  const stats = statsExport?.strategies ?? [];
  const tiles = buildAssetHeatmap(roster, stats);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Cross-asset"
        title="Asset Heatmap"
        description="At-a-glance aggregate win rate per asset, across every strategy wired to it.
          Gray tiles have no resolved trades yet — never a fabricated color. Click a
          tile to jump to that asset on the dashboard."
      />

      {tiles.length === 0 ? (
        <p className="text-muted">No assets registered yet.</p>
      ) : (
        <div
          data-testid="heatmap-grid"
          className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3"
        >
          {tiles.map((tile) => (
            <Link
              key={tile.asset}
              href={`/?asset=${encodeURIComponent(tile.asset)}`}
              data-testid="heatmap-tile"
              data-asset={tile.asset}
              data-has-data={tile.winRate !== null}
              className="rounded-lg border-2 p-3 text-center transition hover:opacity-90"
              style={{
                borderColor: heatmapTileColor(tile.winRate, 0.9),
                backgroundColor: heatmapTileColor(tile.winRate, 0.12),
              }}
            >
              <div className="font-serif text-sm text-parchment">{tile.asset}</div>
              <div className="mt-1 text-xs text-muted">
                {tile.winRate !== null ? `${(tile.winRate * 100).toFixed(0)}% win` : "no data yet"}
              </div>
              <div className="text-[10px] text-muted/70">
                {tile.resolvedTrades} trade{tile.resolvedTrades === 1 ? "" : "s"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
