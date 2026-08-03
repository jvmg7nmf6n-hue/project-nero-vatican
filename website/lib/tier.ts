export type Tier = "verified" | "watchlist" | "experimental";

export const TIER_ORDER: Tier[] = ["verified", "watchlist", "experimental"];

// Display labels only -- the underlying Tier VALUES ("verified"/"watchlist"/
// "experimental") and classifyTier's own classification logic are untouched.
// "Verified" -> "Under Trial" (2026-08-03, display-only rename): this project
// makes no claim that a "verified" config is proven in any final sense --
// every one of them keeps trading and keeps accruing evidence, so a label
// implying a closed, finished judgment was never quite honest. The
// underlying tier (still internally "verified", still classified the exact
// same way) is unchanged; only the word shown to a reader changes.
export const TIER_LABELS: Record<Tier, string> = {
  verified: "Under Trial",
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
