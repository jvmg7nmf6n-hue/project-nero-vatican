"use client";

import { useMemo, useState } from "react";
import StrategyCard from "./StrategyCard";
import {
  ASSET_CLASS_ORDER,
  groupRosterByAssetClass,
  type AssetClass,
} from "@/lib/assetClass";
import { classifyTier, TIER_LABELS, TIER_ORDER, type Tier } from "@/lib/tier";
import type { LedgerRow, StrategyRosterEntry, StrategyStats } from "@/lib/types";

type TabKey = "All" | AssetClass;

const TABS: TabKey[] = ["All", ...ASSET_CLASS_ORDER];

export interface AssetTabsProps {
  roster: StrategyRosterEntry[];
  recentRows: LedgerRow[];
  stats: StrategyStats[];
}

export default function AssetTabs({ roster, recentRows, stats }: AssetTabsProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("All");
  const [visibleTiers, setVisibleTiers] = useState<Set<Tier>>(
    () => new Set(TIER_ORDER)
  );

  const groups = useMemo(() => groupRosterByAssetClass(roster), [roster]);

  const tabCounts = useMemo(() => {
    const counts = new Map<TabKey, number>();
    counts.set("All", roster.length);
    for (const group of groups) {
      counts.set(group.assetClass, group.primary.length + group.pairs.length);
    }
    return counts;
  }, [groups, roster.length]);

  function toggleTier(tier: Tier) {
    setVisibleTiers((prev) => {
      const next = new Set(prev);
      if (next.has(tier)) {
        next.delete(tier);
      } else {
        next.add(tier);
      }
      return next;
    });
  }

  function passesFilter(entry: StrategyRosterEntry): boolean {
    return visibleTiers.has(classifyTier(entry.verification_status));
  }

  const visibleGroups =
    activeTab === "All" ? groups : groups.filter((g) => g.assetClass === activeTab);

  const hasAnyVisibleCard = visibleGroups.some(
    (group) => group.primary.some(passesFilter) || group.pairs.some(passesFilter)
  );

  return (
    <div>
      <div data-testid="filter-chips" className="flex flex-wrap gap-2 mb-4">
        {TIER_ORDER.map((tier) => {
          const active = visibleTiers.has(tier);
          return (
            <button
              key={tier}
              type="button"
              data-testid={`filter-chip-${tier}`}
              aria-pressed={active}
              onClick={() => toggleTier(tier)}
              className={`rounded-full border px-3 py-1 text-xs transition ${
                active
                  ? "border-gold/60 text-parchment bg-gold/10"
                  : "border-muted/30 text-muted"
              }`}
            >
              {TIER_LABELS[tier]}
            </button>
          );
        })}
      </div>

      <div
        data-testid="asset-tabs"
        className="flex gap-2 overflow-x-auto pb-2 mb-6 sm:flex-wrap"
      >
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            data-testid={`tab-${tab}`}
            aria-pressed={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition ${
              activeTab === tab
                ? "bg-gold text-ink"
                : "border border-gold/30 text-muted hover:text-parchment"
            }`}
          >
            {tab} ({tabCounts.get(tab) ?? 0})
          </button>
        ))}
      </div>

      {!hasAnyVisibleCard ? (
        <p data-testid="asset-tabs-empty" className="text-muted">
          {roster.length === 0
            ? "No strategies registered yet."
            : "No strategies match the current filters."}
        </p>
      ) : (
        <div className="flex flex-col gap-10">
          {visibleGroups.map((group) => {
            const primary = group.primary.filter(passesFilter);
            const pairs = group.pairs.filter(passesFilter);
            if (primary.length === 0 && pairs.length === 0) {
              return null;
            }
            return (
              <div key={group.assetClass} data-testid={`asset-group-${group.assetClass}`}>
                {activeTab === "All" ? (
                  <h3 className="font-serif text-xl text-parchment mb-3">
                    {group.assetClass}
                  </h3>
                ) : null}
                {primary.length > 0 ? (
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {primary.map((entry) => (
                      <StrategyCard
                        key={`${entry.name}-${entry.version}-${entry.asset}`}
                        entry={entry}
                        recentRows={recentRows}
                        stats={stats}
                      />
                    ))}
                  </div>
                ) : null}
                {pairs.length > 0 ? (
                  <div className="mt-4">
                    <h4 className="font-serif text-sm text-muted mb-2 uppercase tracking-wide">
                      Pairs
                    </h4>
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      {pairs.map((entry) => (
                        <StrategyCard
                          key={`${entry.name}-${entry.version}-${entry.asset}`}
                          entry={entry}
                          recentRows={recentRows}
                          stats={stats}
                        />
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
