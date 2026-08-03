import { render, screen } from "@testing-library/react";
import HeroStats from "@/components/HeroStats";
import type { SiteSummary, StrategyRosterEntry } from "@/lib/types";

function makeEntry(overrides: Partial<StrategyRosterEntry>): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "verified",
    source_report: null,
    ...overrides,
  };
}

const SUMMARY: SiteSummary = {
  configs_tested: 1515,
  strategies_survived: 17,
  strategy_families_verified: 4,
  tracking_since: "2026-07-17",
  last_curated: "2026-07-25",
};

// Mirrors the real contradiction this fix resolves: 14 PEAD ticker/threshold
// variants (one family) + one config each of 3 other families = 17 verified
// configs, 4 distinct families.
const ROSTER: StrategyRosterEntry[] = [
  makeEntry({ name: "BREAKOUT_MOMENTUM", asset: "GOLD", verification_status: "triple-verified" }),
  makeEntry({
    name: "TREND_PULLBACK",
    asset: "BNB",
    verification_status: "verified — sample-limited",
  }),
  makeEntry({
    name: "COINTEGRATION_PAIRS",
    asset: "BTC-ETH",
    verification_status: "verified — weakest, live-proving",
  }),
  ...Array.from({ length: 14 }, (_, i) =>
    makeEntry({ name: "PEAD", asset: `TICKER${i}`, verification_status: "verified" })
  ),
  makeEntry({
    name: "ORDERFLOW_IMBALANCE",
    asset: "ETH",
    verification_status: "experimental — snapshot-based, forward-testing only, no backtest exists",
  }),
];

describe("HeroStats verified-configs tile", () => {
  it("shows the verified config count matching the roster, with a distinct-family subtext", () => {
    render(<HeroStats summary={SUMMARY} roster={ROSTER} />);

    expect(screen.getByText("Under Trial configs")).toBeInTheDocument();
    expect(screen.getByText("4 distinct families")).toBeInTheDocument();
  });

  it("does not show a family subtext when there are no verified configs", () => {
    const noneVerified = ROSTER.map((entry) => ({
      ...entry,
      verification_status: "experimental — no backtest exists",
    }));
    render(<HeroStats summary={SUMMARY} roster={noneVerified} />);
    expect(screen.queryByText(/distinct famil/)).not.toBeInTheDocument();
  });

  it("uses singular 'family' for exactly one verified family", () => {
    const oneFamily = [
      makeEntry({ name: "BREAKOUT_MOMENTUM", asset: "GOLD", verification_status: "verified" }),
      makeEntry({ name: "BREAKOUT_MOMENTUM", asset: "SILVER", verification_status: "verified" }),
    ];
    render(<HeroStats summary={SUMMARY} roster={oneFamily} />);
    expect(screen.getByText("1 distinct family")).toBeInTheDocument();
  });

  it("renders the live-signals tile as the roster count, independent of summary", () => {
    render(<HeroStats summary={SUMMARY} roster={ROSTER} />);
    expect(screen.getByText("Live signals")).toBeInTheDocument();
  });
});
