import { TIER_LABELS, type Tier } from "@/lib/tier";

const TIER_BADGE_STYLES: Record<Tier, string> = {
  verified: "border-teal/70 text-teal",
  watchlist: "border-gold/60 text-gold",
  experimental: "border-muted/60 text-muted",
};

export default function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs ${TIER_BADGE_STYLES[tier]}`}
    >
      {TIER_LABELS[tier]}
    </span>
  );
}
