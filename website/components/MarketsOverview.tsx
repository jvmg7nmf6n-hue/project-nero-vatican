"use client";

import type { MarketTile } from "@/lib/marketsOverview";
import { findVolatilityRegime, REGIME_COLOR } from "@/lib/quantCrossAsset";
import type { VolatilityRegimeEntry } from "@/lib/types";

export interface MarketsOverviewProps {
  tiles: MarketTile[];
  onSelectAsset: (asset: string) => void;
  // Day 5/7: optional so this component still works standalone in isolation (and
  // in every pre-Day-5 test) -- defaults to no regimes, which renders no badge at
  // all, never a broken tile.
  volatilityRegimes?: VolatilityRegimeEntry[];
}

// Values below 10 (mostly forex pairs, e.g. EUR/USD ~1.08) need more decimal
// precision to be meaningfully readable than large-denomination assets (BTC,
// stocks) do -- a fixed 2-decimal format would print forex pairs as "1.08" on
// every tile, discarding the digits that actually move.
function formatPrice(price: number): string {
  const precision = Math.abs(price) < 10 ? 4 : 2;
  return price.toLocaleString("en-US", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}

function formatChangePct(changePct: number): string {
  return `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`;
}

// The homepage centerpiece -- an at-a-glance terminal, not a data table. Every
// tile is a plain <button> (clickable, keyboard-accessible) rather than a <Link>:
// per the task spec this must never navigate, only update the asset filter below
// and smooth-scroll to it (see MarketsSection, the client wrapper that owns that
// shared state).
export default function MarketsOverview({ tiles, onSelectAsset, volatilityRegimes = [] }: MarketsOverviewProps) {
  if (tiles.length === 0) {
    return null;
  }

  return (
    <section>
      <h2 className="font-serif text-2xl text-parchment mb-4">Markets overview</h2>
      <div
        data-testid="markets-overview-grid"
        className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3"
      >
        {tiles.map((tile) => (
          <button
            key={tile.asset}
            type="button"
            data-testid="market-tile"
            data-asset={tile.asset}
            data-status={tile.status}
            onClick={() => onSelectAsset(tile.asset)}
            className="rounded-lg border border-muted/20 bg-ink p-3 text-left transition hover:border-gold/60"
          >
            <div className="font-serif text-base text-parchment">{tile.asset}</div>

            {tile.status === "ok" ? (
              <>
                <div className="mt-1 text-sm text-parchment">{formatPrice(tile.price)}</div>
                <div
                  data-testid="market-tile-change"
                  className={`text-xs ${
                    tile.changePct === null ? "text-muted" : tile.changePct >= 0 ? "text-teal" : "text-loss"
                  }`}
                >
                  {tile.changePct === null ? "n/a" : formatChangePct(tile.changePct)}
                </div>
                <svg
                  data-testid="market-tile-sparkline"
                  viewBox="0 0 100 32"
                  preserveAspectRatio="none"
                  className="mt-2 h-8 w-full"
                  aria-hidden="true"
                >
                  <path
                    d={tile.sparklinePath}
                    fill="none"
                    stroke={tile.trend === "up" ? "#2ec4b6" : "#d47a6a"}
                    strokeWidth="1.5"
                  />
                </svg>
                {(() => {
                  const regime = findVolatilityRegime(volatilityRegimes, tile.asset, tile.timeframe);
                  if (!regime) {
                    return null; // graceful: no data -> no badge, never a broken tile
                  }
                  return (
                    <div
                      data-testid="market-tile-regime"
                      title="Volatility Context (descriptive, not a trade signal or recommendation)"
                      className="mt-1 flex items-center gap-1 text-[10px] text-muted"
                    >
                      <span
                        data-testid="market-tile-regime-dot"
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ backgroundColor: REGIME_COLOR[regime.regime] }}
                        aria-hidden="true"
                      />
                      {regime.regime}
                    </div>
                  );
                })()}
              </>
            ) : (
              <div data-testid="market-tile-placeholder" className="mt-1 text-xs text-muted">
                No price data yet
              </div>
            )}

            <div className="mt-2 text-[10px] uppercase tracking-wide text-muted">
              {tile.strategyCount} {tile.strategyCount === 1 ? "strategy" : "strategies"} watching
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
