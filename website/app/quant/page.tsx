import CorrelationHeatmap from "@/components/CorrelationHeatmap";
import { fetchQuantCrossAsset, fetchStrategies } from "@/lib/data";
import { buildMarketAssetList } from "@/lib/marketsOverview";

export const revalidate = 300;

export const metadata = {
  title: "Quant Intelligence — Vatican",
};

function formatPvalue(pvalue: number | null): string {
  return pvalue === null ? "n/a" : pvalue.toFixed(4);
}

export default async function QuantPage() {
  const [strategiesExport, quantCrossAsset] = await Promise.all([fetchStrategies(), fetchQuantCrossAsset()]);
  const roster = strategiesExport?.strategies ?? [];
  const assets = buildMarketAssetList(roster).map((spec) => spec.asset);
  const pairs = quantCrossAsset?.correlation_matrix ?? [];
  const cointegration = quantCrossAsset?.cointegration ?? [];
  const leadLag = quantCrossAsset?.lead_lag ?? [];

  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="font-serif text-3xl text-parchment">Quant Intelligence</h1>
        <p className="text-muted mt-2 max-w-2xl">
          Cross-asset relationships for research and educational context only -- not a trade
          instruction. Every number below is an independent descriptive statistic; there is no
          combined score or rating anywhere on this page.
        </p>
      </div>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-2">Correlation matrix</h2>
        <p className="text-muted text-sm mb-4 max-w-2xl">
          Rolling 30-period return correlation, most recent value only. Only pairs sharing the
          same candle timeframe are compared -- everything else (including pairs that share a
          timeframe label but no real overlapping dates) shows as N/A, never a fabricated number.
        </p>
        {quantCrossAsset ? (
          <CorrelationHeatmap assets={assets} pairs={pairs} />
        ) : (
          <p data-testid="quant-page-unavailable" className="text-muted text-sm">
            Cross-asset data coming soon.
          </p>
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-2">Cointegration</h2>
        <p className="text-muted text-sm mb-4 max-w-2xl">
          A descriptive statistic (Engle-Granger test) on a small set of economically-related
          pairs -- not a trading signal on its own.
        </p>
        {cointegration.length === 0 ? (
          <p data-testid="cointegration-empty" className="text-muted text-sm">
            No cointegration data available yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table data-testid="cointegration-table" className="w-full text-left text-sm">
              <thead>
                <tr className="text-muted border-b border-muted/30">
                  <th className="py-2 pr-4">Pair</th>
                  <th className="py-2 pr-4">p-value</th>
                  <th className="py-2 pr-4">Cointegrated?</th>
                  <th className="py-2 pr-4">Note</th>
                </tr>
              </thead>
              <tbody>
                {cointegration.map((entry) => (
                  <tr key={`${entry.asset_a}-${entry.asset_b}`} className="border-b border-muted/10">
                    <td className="py-2 pr-4 text-parchment">
                      {entry.asset_a} ({entry.timeframe_a}) / {entry.asset_b} ({entry.timeframe_b})
                    </td>
                    <td className="py-2 pr-4">{formatPvalue(entry.pvalue)}</td>
                    <td className="py-2 pr-4">
                      {entry.cointegrated === null ? "n/a" : entry.cointegrated ? "Yes" : "No"}
                    </td>
                    <td className="py-2 pr-4 text-muted text-xs max-w-md">{entry.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="font-serif text-xl text-parchment mb-2">Lead-lag (BTC benchmark)</h2>
        <p className="text-muted text-sm mb-4 max-w-2xl">
          Does BTC lead other crypto-class assets by 1-4 periods? A descriptive statistic, not a
          trading signal.
        </p>
        {leadLag.length === 0 ? (
          <p data-testid="lead-lag-empty" className="text-muted text-sm">
            No lead-lag data available yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table data-testid="lead-lag-table" className="w-full text-left text-sm">
              <thead>
                <tr className="text-muted border-b border-muted/30">
                  <th className="py-2 pr-4">Asset</th>
                  <th className="py-2 pr-4">Lags {leadLag[0]?.benchmark ?? "BTC"} by</th>
                  <th className="py-2 pr-4">Correlation at that lag</th>
                </tr>
              </thead>
              <tbody>
                {leadLag.map((entry) => (
                  <tr key={entry.asset} className="border-b border-muted/10">
                    <td className="py-2 pr-4 text-parchment">{entry.asset}</td>
                    <td className="py-2 pr-4">{entry.best_lag === null ? "n/a" : `${entry.best_lag} period(s)`}</td>
                    <td className="py-2 pr-4">{entry.correlation === null ? "n/a" : entry.correlation.toFixed(2)}</td>
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
