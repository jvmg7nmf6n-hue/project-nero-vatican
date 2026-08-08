// CC-1 directive Part B1/B2: real, static verification metrics for this
// project's 3 fully-verified survivor strategies. Static prose (like
// /agents's own RANDOM_BASELINES convention) rather than a live export,
// because these are one-time, already-completed backtest measurements that
// do not change run to run -- only the LIVE fields (days live, real distance)
// are computed fresh. Source, verbatim, re-read directly from each real file
// this directive (2026-08-08):
//   docs/statistical_harness_upgrade.md (bootstrap/random-baseline pass)
//   docs/trail_exit_ab_report.md (BREAKOUT_MOMENTUM win%/PF detail)
//   docs/grid_shift_robustness_followup.md (TREND_PULLBACK/COINTEGRATION_PAIRS win%/PF detail)
// "Zero live trades" and each go-live date reconfirmed fresh against
// data/truth_ledger.db's own execution_log table, not assumed from an older
// report -- see this directive's own closing report for the real query.
export interface SurvivorMeta {
  name: string;
  asset: string;
  timeframe: string;
  version: string;
  verificationStatus: string;
  sourceReport: string;
  // ISO date of the first real, successfully-logged evaluation for this
  // exact (strategy, version, asset) -- NOT the code/workflow deploy date
  // (2026-07-18), which is earlier: a real infrastructure gap (Binance 451
  // errors on GitHub's US runner IPs for BNB; weekly cadence for GOLD)
  // delayed the first real evaluation for all three. See closing report.
  liveSinceIso: string;
  train: { n: number; winPct: number; expectancyR: number; profitFactor: number };
  test: { n: number; winPct: number; expectancyR: number; profitFactor: number };
  zeroLiveEntriesConfirmedAsOf: string;
}

export const SURVIVORS: SurvivorMeta[] = [
  {
    name: "BREAKOUT_MOMENTUM",
    asset: "GOLD",
    timeframe: "1week",
    version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    verificationStatus: "triple-verified",
    sourceReport: "docs/statistical_harness_upgrade.md",
    liveSinceIso: "2026-07-31",
    train: { n: 63, winPct: 63.5, expectancyR: 0.395, profitFactor: 2.06 },
    test: { n: 31, winPct: 64.5, expectancyR: 0.426, profitFactor: 2.15 },
    zeroLiveEntriesConfirmedAsOf: "2026-08-08",
  },
  {
    name: "TREND_PULLBACK",
    asset: "BNB",
    timeframe: "12h",
    version: "trend-pullback-v1.0.0",
    verificationStatus: "verified — sample-limited",
    sourceReport: "docs/statistical_harness_upgrade.md",
    liveSinceIso: "2026-07-28",
    train: { n: 57, winPct: 50.9, expectancyR: 0.147, profitFactor: 1.27 },
    test: { n: 30, winPct: 56.7, expectancyR: 0.243, profitFactor: 1.55 },
    zeroLiveEntriesConfirmedAsOf: "2026-08-08",
  },
  {
    name: "COINTEGRATION_PAIRS",
    asset: "BTC-ETH",
    timeframe: "12h",
    version: "cointegration-pairs-v1.0.0",
    verificationStatus: "verified — weakest, live-proving",
    sourceReport: "docs/statistical_harness_upgrade.md",
    liveSinceIso: "2026-07-28",
    train: { n: 61, winPct: 49.2, expectancyR: 0.047, profitFactor: 3.65 },
    test: { n: 22, winPct: 50.0, expectancyR: 0.003, profitFactor: 1.2 },
    zeroLiveEntriesConfirmedAsOf: "2026-08-08",
  },
];

export function daysLive(liveSinceIso: string, now: Date): number {
  const liveSince = new Date(`${liveSinceIso}T00:00:00Z`);
  const diffMs = now.getTime() - liveSince.getTime();
  return Math.max(0, Math.floor(diffMs / (24 * 60 * 60 * 1000)));
}

export function formatDaysLive(days: number): string {
  if (days < 1) return "less than a day live";
  if (days === 1) return "1 day live";
  return `${days} days live`;
}

// One honest framing line -- accuracy, not enthusiasm (B2c). States what IS
// real (the verification) and what is NOT yet real (a live track record)
// in the same sentence, deliberately, so neither can be read alone.
export const SURVIVORS_FRAMING_LINE =
  "These 3 strategies cleared this project's own backtest verification bar — real historical edge over a random-entry baseline, on real market data. None has taken a real (paper) trade yet: their entry conditions simply haven't fired since going live.";
