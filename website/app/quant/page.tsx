import CorrelationHeatmap from "@/components/CorrelationHeatmap";
import Correlation3DSurface from "@/components/Correlation3DSurface";
import PageHeader from "@/components/PageHeader";
import SectionHeader from "@/components/SectionHeader";
import type { Candle } from "@/lib/candleData";
import { fetchCandleData, fetchQuantCrossAsset, fetchStrategies } from "@/lib/data";
import { TABLE_BODY_CELL, TABLE_BODY_ROW, TABLE_HEADER_CELL, TABLE_HEADER_ROW } from "@/lib/designTokens";
import { buildMarketAssetList } from "@/lib/marketsOverview";

// CC-1 Part D4/D5: the 7-equity 1day group -- confirmed via docs/site_data/
// quant_cross_asset.json that every pair among these 7 already has a real,
// non-null correlation (fully overlapping calendar, unlike most cross-asset-
// class pairs, e.g. SILVER's business-days-only futures grid vs BTC's 24/7
// one) -- the best real candidate for a gap-free 3D surface. See
// docs/investigations/website_3d4d_correlation_d4d5.md.
const SURFACE_ASSETS = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA"];
const SURFACE_TIMEFRAME = "1day";

export const revalidate = 300;

export const metadata = {
  title: "Quant Intelligence — Vatican",
};

function formatPvalue(pvalue: number | null): string {
  return pvalue === null ? "n/a" : pvalue.toFixed(4);
}

export default async function QuantPage() {
  const [strategiesExport, quantCrossAsset, surfaceCandleResults] = await Promise.all([
    fetchStrategies(),
    fetchQuantCrossAsset(),
    Promise.all(SURFACE_ASSETS.map((asset) => fetchCandleData(asset, SURFACE_TIMEFRAME))),
  ]);
  const roster = strategiesExport?.strategies ?? [];
  const assets = buildMarketAssetList(roster).map((spec) => spec.asset);
  const pairs = quantCrossAsset?.correlation_matrix ?? [];
  const cointegration = quantCrossAsset?.cointegration ?? [];
  const leadLag = quantCrossAsset?.lead_lag ?? [];

  // Only assets whose candle fetch actually succeeded -- fetchCandleData never
  // throws (see lib/data.ts), so a single asset's fetch failing narrows the
  // surface rather than blanking the whole section.
  const surfaceCandlesByAsset: Record<string, Candle[]> = {};
  SURFACE_ASSETS.forEach((asset, i) => {
    const result = surfaceCandleResults[i];
    if (result.status === "ok") surfaceCandlesByAsset[asset] = result.data.candles;
  });
  const surfaceAssetsAvailable = SURFACE_ASSETS.filter((a) => surfaceCandlesByAsset[a]);

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        title="Quant Intelligence"
        description="Cross-asset relationships for research and educational context only -- not a trade
          instruction. Every number below is an independent descriptive statistic; there is no
          combined score or rating anywhere on this page."
      />

      <section>
        <SectionHeader
          title="Correlation matrix"
          description="Rolling 30-period return correlation, most recent value only. Only pairs sharing the
          same candle timeframe are compared -- everything else (including pairs that share a
          timeframe label but no real overlapping dates) shows as N/A, never a fabricated number."
        />
        {quantCrossAsset ? (
          <CorrelationHeatmap assets={assets} pairs={pairs} />
        ) : (
          <p data-testid="quant-page-unavailable" className="text-muted text-sm">
            Cross-asset data coming soon.
          </p>
        )}
      </section>

      <section>
        <SectionHeader
          title="3D correlation surface (animated over time)"
          description={`Same rolling 30-return-period Pearson correlation as the matrix above, computed
          across ${surfaceAssetsAvailable.length} mega-cap tech equities (${surfaceAssetsAvailable.join(", ")}) --
          the one group in this project's roster where every pair shares a fully-overlapping
          real calendar grid, so the surface has no N/A gaps to render. Drag the slider for a
          real 4th dimension: each frame is an independently computed rolling window ending at
          a different real historical date -- never interpolated between two real points.`}
        />
        {surfaceAssetsAvailable.length >= 2 ? (
          <Correlation3DSurface assets={surfaceAssetsAvailable} candlesByAsset={surfaceCandlesByAsset} />
        ) : (
          <p data-testid="correlation-3d-unavailable-page" className="text-muted text-sm">
            Not enough candle data available yet for the 3D surface.
          </p>
        )}
      </section>

      <section>
        <SectionHeader
          title="Cointegration"
          description="A descriptive statistic (Engle-Granger test) on a small set of economically-related
          pairs -- not a trading signal on its own."
        />
        {cointegration.length === 0 ? (
          <p data-testid="cointegration-empty" className="text-muted text-sm">
            No cointegration data available yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table data-testid="cointegration-table" className="w-full text-left text-sm">
              <thead>
                <tr className={TABLE_HEADER_ROW}>
                  <th className={TABLE_HEADER_CELL}>Pair</th>
                  <th className={TABLE_HEADER_CELL}>p-value</th>
                  <th className={TABLE_HEADER_CELL}>Cointegrated?</th>
                  <th className={TABLE_HEADER_CELL}>Note</th>
                </tr>
              </thead>
              <tbody>
                {cointegration.map((entry) => (
                  <tr key={`${entry.asset_a}-${entry.asset_b}`} className={TABLE_BODY_ROW}>
                    <td className={`${TABLE_BODY_CELL} text-parchment`}>
                      {entry.asset_a} ({entry.timeframe_a}) / {entry.asset_b} ({entry.timeframe_b})
                    </td>
                    <td className={TABLE_BODY_CELL}>{formatPvalue(entry.pvalue)}</td>
                    <td className={TABLE_BODY_CELL}>
                      {entry.cointegrated === null ? "n/a" : entry.cointegrated ? "Yes" : "No"}
                    </td>
                    <td className={`${TABLE_BODY_CELL} text-muted text-xs max-w-md`}>{entry.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <SectionHeader
          title="Lead-lag (BTC benchmark)"
          description="Does BTC lead other crypto-class assets by 1-4 periods? A descriptive statistic, not a
          trading signal."
        />
        {leadLag.length === 0 ? (
          <p data-testid="lead-lag-empty" className="text-muted text-sm">
            No lead-lag data available yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table data-testid="lead-lag-table" className="w-full text-left text-sm">
              <thead>
                <tr className={TABLE_HEADER_ROW}>
                  <th className={TABLE_HEADER_CELL}>Asset</th>
                  <th className={TABLE_HEADER_CELL}>Lags {leadLag[0]?.benchmark ?? "BTC"} by</th>
                  <th className={TABLE_HEADER_CELL}>Correlation at that lag</th>
                </tr>
              </thead>
              <tbody>
                {leadLag.map((entry) => (
                  <tr key={entry.asset} className={TABLE_BODY_ROW}>
                    <td className={`${TABLE_BODY_CELL} text-parchment`}>{entry.asset}</td>
                    <td className={TABLE_BODY_CELL}>{entry.best_lag === null ? "n/a" : `${entry.best_lag} period(s)`}</td>
                    <td className={TABLE_BODY_CELL}>{entry.correlation === null ? "n/a" : entry.correlation.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
