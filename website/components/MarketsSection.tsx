"use client";

import { useRef, useState } from "react";
import AssetTabs from "./AssetTabs";
import MarketsOverview from "./MarketsOverview";
import type { MarketTile } from "@/lib/marketsOverview";
import type { LedgerRow, StrategyRosterEntry, StrategyStats } from "@/lib/types";

export interface MarketsSectionProps {
  roster: StrategyRosterEntry[];
  recentRows: LedgerRow[];
  stats: StrategyStats[];
  tiles: MarketTile[];
  // Set when arriving from /heatmap's "?asset=" link -- still honored as the
  // initial filter, same as before this component existed.
  initialAssetFilter?: string | null;
}

// Owns the one piece of state a tile click and AssetTabs both need to share.
// AssetTabs itself is untouched and only ever reads its `initialAssetFilter` prop
// once, at mount (see that component) -- remounting it via `key` whenever the
// filter changes is what makes a later tile click actually take effect, without
// risking any of AssetTabs' own existing behavior or tests.
export default function MarketsSection({
  roster,
  recentRows,
  stats,
  tiles,
  initialAssetFilter = null,
}: MarketsSectionProps) {
  const [assetFilter, setAssetFilter] = useState<string | null>(initialAssetFilter);
  const tabsSectionRef = useRef<HTMLDivElement>(null);

  function handleSelectAsset(asset: string) {
    setAssetFilter(asset);
    tabsSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="flex flex-col gap-16">
      <MarketsOverview tiles={tiles} onSelectAsset={handleSelectAsset} />

      <section ref={tabsSectionRef} data-testid="asset-tabs-section">
        <h2 className="font-serif text-2xl text-parchment mb-4">Live council verdicts</h2>
        <AssetTabs
          key={assetFilter ?? "all"}
          roster={roster}
          recentRows={recentRows}
          stats={stats}
          initialAssetFilter={assetFilter}
        />
      </section>
    </div>
  );
}
