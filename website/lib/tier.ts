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
//
// CC-1 overnight directive, Part 3: the ONE list every real
// verification_status prefix must appear in -- classifyTier and
// isRecognizedVerificationStatus both derive from this single source, so
// they can never silently disagree. Confirmed exhaustive against every
// real value in docs/site_data/strategies.json as of 2026-08-08 (see
// __tests__/tier.test.ts's own RealDataClosedVocabularyTest).
const PREFIX_TO_TIER: ReadonlyArray<{ prefix: string; tier: Tier }> = [
  { prefix: "experimental", tier: "experimental" },
  { prefix: "forward-test-only", tier: "experimental" },
  { prefix: "promising-watchlist", tier: "watchlist" },
  { prefix: "watchlist", tier: "watchlist" },
  { prefix: "triple-verified", tier: "verified" },
  { prefix: "verified", tier: "verified" },
];

// Runtime behavior UNCHANGED from before this directive -- an unrecognized
// value still safely falls through to "experimental" rather than crashing
// the live site (a strategy's card must always render something). The real
// enforcement against silent misclassification is isRecognizedVerificationStatus
// below, checked by a test against every real committed value -- "fail loudly
// in CI," never "fail loudly for a live visitor."
export function classifyTier(verificationStatus: string): Tier {
  const status = verificationStatus.toLowerCase().trim();
  const match = PREFIX_TO_TIER.find((p) => status.startsWith(p.prefix));
  return match?.tier ?? "experimental";
}

// CC-1 overnight directive, Part 3: the closed-vocabulary check itself.
// Returns false for anything classifyTier would have to silently default --
// a typo'd or genuinely new verification_status wording that was never
// added to PREFIX_TO_TIER. This function makes that silent case detectable
// (and test-enforced against real data) without changing classifyTier's own
// safe runtime fallback.
export function isRecognizedVerificationStatus(verificationStatus: string): boolean {
  const status = verificationStatus.toLowerCase().trim();
  return PREFIX_TO_TIER.some((p) => status.startsWith(p.prefix));
}
