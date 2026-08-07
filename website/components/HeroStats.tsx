"use client";

import Link from "next/link";
import Logo from "./Logo";
import SystemStatus from "./SystemStatus";
import { useCountUp } from "@/lib/useCountUp";
import { classifyTier } from "@/lib/tier";
import type { HeartbeatStatus, SiteSummary, StrategyRosterEntry } from "@/lib/types";

function daysSince(isoDate: string): number | null {
  const then = new Date(isoDate);
  if (Number.isNaN(then.getTime())) {
    return null;
  }
  const diffMs = Date.now() - then.getTime();
  return Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
}

interface StatTileProps {
  label: string;
  value: number | null;
  sublabel?: string;
}

function StatTile({ label, value, sublabel }: StatTileProps) {
  const displayValue = useCountUp(value ?? 0);

  return (
    <div
      data-testid="hero-stat-tile"
      className="rounded-lg border border-gold/40 px-4 py-5 text-center"
    >
      <div className="font-serif text-3xl sm:text-4xl text-parchment tabular-nums">
        {value === null ? "—" : displayValue}
      </div>
      <div className="mt-1 text-xs uppercase tracking-wide text-muted">{label}</div>
      {sublabel ? <div className="mt-0.5 text-[11px] text-muted/80">{sublabel}</div> : null}
    </div>
  );
}

export interface HeroStatsProps {
  summary: SiteSummary | null;
  roster: StrategyRosterEntry[];
  heartbeat?: HeartbeatStatus | null;
}

export default function HeroStats({ summary, roster, heartbeat = null }: HeroStatsProps) {
  const configsTested = summary?.configs_tested ?? null;
  const liveSignals = roster.length;
  const verifiedEntries = roster.filter(
    (entry) => classifyTier(entry.verification_status) === "verified"
  );
  // Computed live from the roster (not read from summary.strategy_families_verified)
  // so this can never drift out of sync with the cards rendered just below it -- the
  // exact class of contradiction that prompted adding this subtext in the first place.
  const verifiedConfigCount = verifiedEntries.length;
  const verifiedFamilyCount = new Set(verifiedEntries.map((entry) => entry.name)).size;
  const trackingDays = summary ? daysSince(summary.tracking_since) : null;

  return (
    <section className="text-center py-10">
      <Logo animated className="mx-auto h-16 w-16" />
      <h1 className="mt-4 font-serif text-4xl sm:text-5xl text-parchment">
        The book of records.
        <br className="hidden sm:block" /> Every signal. Every loss.
      </h1>
      <p className="mt-4 text-muted max-w-2xl mx-auto">
        Vatican is a paper-trading research platform for gold and crypto. Every
        signal our strategies generate — and every loss they take — is logged to a
        public Truth Ledger. Nothing is hidden after the fact.
      </p>
      <div className="mt-6 flex justify-center gap-4">
        <Link
          href="/ledger"
          className="rounded-md bg-gold px-5 py-2 text-ink font-medium hover:opacity-90"
        >
          View the live ledger
        </Link>
        <a
          href="/methodology"
          className="rounded-md border border-gold/50 px-5 py-2 text-parchment hover:bg-gold/10"
        >
          How we test
        </a>
      </div>
      <div
        data-testid="hero-stats"
        className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-4 max-w-3xl mx-auto"
      >
        <StatTile label="Configs tested" value={configsTested} />
        <StatTile label="Live signals" value={liveSignals} />
        <StatTile
          label="Under Trial configs"
          value={verifiedConfigCount}
          sublabel={
            verifiedConfigCount > 0
              ? `${verifiedFamilyCount} distinct famil${verifiedFamilyCount === 1 ? "y" : "ies"}`
              : undefined
          }
        />
        <StatTile label="Tracking days" value={trackingDays} />
      </div>
      <div className="mt-6 flex justify-center">
        <SystemStatus heartbeat={heartbeat} />
      </div>
    </section>
  );
}
