export type Tier = "verified" | "watchlist" | "experimental";

export const TIER_ORDER: Tier[] = ["verified", "watchlist", "experimental"];

export const TIER_LABELS: Record<Tier, string> = {
  verified: "Verified",
  watchlist: "Watchlist",
  experimental: "Experimental",
};

// strategies.json carries a free-text verification_status (see
// nero_core/execution/verification_status.py) rather than a fixed enum.
// This buckets the leading phrase into the three display tiers used for
// card styling and the hero "verified" count. "promising-watchlist"
// collapses into "watchlist" and "forward-test-only" (no backtest exists)
// collapses into "experimental" -- both are honest groupings of the
// existing wording, not new claims about the strategy.
export function classifyTier(verificationStatus: string): Tier {
  const status = verificationStatus.toLowerCase().trim();
  if (status.startsWith("experimental")) return "experimental";
  if (status.startsWith("forward-test-only")) return "experimental";
  if (status.startsWith("watchlist") || status.startsWith("promising-watchlist")) {
    return "watchlist";
  }
  if (status.startsWith("verified") || status.startsWith("triple-verified")) {
    return "verified";
  }
  return "experimental";
}
