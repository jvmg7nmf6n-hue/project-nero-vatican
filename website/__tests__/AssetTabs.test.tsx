import { fireEvent, render, screen, within } from "@testing-library/react";
import AssetTabs from "@/components/AssetTabs";
import type { StrategyRosterEntry } from "@/lib/types";

function makeEntry(overrides: Partial<StrategyRosterEntry>): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.0.0",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "verified",
    ...overrides,
  };
}

const ROSTER: StrategyRosterEntry[] = [
  makeEntry({ name: "BREAKOUT_MOMENTUM", asset: "GOLD", verification_status: "triple-verified" }),
  makeEntry({
    name: "TREND_PULLBACK",
    asset: "BNB",
    verification_status: "watchlist — forward-testing, not verified",
  }),
  makeEntry({
    name: "ORDERFLOW_IMBALANCE",
    asset: "BTC",
    verification_status: "experimental — snapshot-based, forward-testing only, no backtest exists",
  }),
  makeEntry({
    name: "COINTEGRATION_PAIRS",
    asset: "BTC-ETH",
    verification_status: "verified — weakest, live-proving",
  }),
];

describe("AssetTabs tab switching", () => {
  it("shows all strategies under the All tab by default", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    expect(screen.getAllByTestId("strategy-card")).toHaveLength(4);
  });

  it("switches to only the Crypto strategies when the Crypto tab is clicked", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    fireEvent.click(screen.getByTestId("tab-Crypto"));

    const cards = screen.getAllByTestId("strategy-card");
    // BTC (ORDERFLOW_IMBALANCE) + BTC-ETH pair (COINTEGRATION_PAIRS), not GOLD/BNB.
    expect(cards).toHaveLength(2);
    expect(screen.getByText("ORDERFLOW_IMBALANCE")).toBeInTheDocument();
    expect(screen.getByText("COINTEGRATION_PAIRS")).toBeInTheDocument();
    expect(screen.queryByText("BREAKOUT_MOMENTUM")).not.toBeInTheDocument();
  });

  it("shows asset-class section headers only on the All tab", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    expect(screen.getByText("Crypto")).toBeInTheDocument();
    expect(screen.getByText("Gold")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tab-Gold"));
    expect(screen.queryByText("Crypto")).not.toBeInTheDocument();
  });

  it("groups pair assets under a Pairs sub-heading within their dominant class", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    fireEvent.click(screen.getByTestId("tab-Crypto"));
    const cryptoGroup = screen.getByTestId("asset-group-Crypto");
    expect(within(cryptoGroup).getByText("Pairs")).toBeInTheDocument();
  });

  it("shows a tab count badge reflecting the roster size for that class", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    // BTC single asset + BTC-ETH pair = 2 Crypto entries.
    expect(screen.getByTestId("tab-Crypto")).toHaveTextContent("Crypto (2)");
    expect(screen.getByTestId("tab-All")).toHaveTextContent("All (4)");
  });
});

describe("AssetTabs filter chips", () => {
  it("hides watchlist cards when the Watchlist chip is toggled off", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    expect(screen.getByText("TREND_PULLBACK")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("filter-chip-watchlist"));
    expect(screen.queryByText("TREND_PULLBACK")).not.toBeInTheDocument();
    // Others remain visible.
    expect(screen.getByText("BREAKOUT_MOMENTUM")).toBeInTheDocument();
  });

  it("shows the card again when the chip is toggled back on", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    const chip = screen.getByTestId("filter-chip-experimental");

    fireEvent.click(chip);
    expect(screen.queryByText("ORDERFLOW_IMBALANCE")).not.toBeInTheDocument();

    fireEvent.click(chip);
    expect(screen.getByText("ORDERFLOW_IMBALANCE")).toBeInTheDocument();
  });
});

describe("AssetTabs empty states", () => {
  it("renders a no-strategies message when the roster is empty", () => {
    render(<AssetTabs roster={[]} recentRows={[]} stats={[]} />);
    expect(screen.getByTestId("asset-tabs-empty")).toHaveTextContent(
      "No strategies registered yet."
    );
  });

  it("renders a no-matches message when every tier filter is toggled off", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    fireEvent.click(screen.getByTestId("filter-chip-verified"));
    fireEvent.click(screen.getByTestId("filter-chip-watchlist"));
    fireEvent.click(screen.getByTestId("filter-chip-experimental"));

    expect(screen.getByTestId("asset-tabs-empty")).toHaveTextContent(
      "No strategies match the current filters."
    );
  });

  it("renders a no-matches message for a tab with no strategies in that class", () => {
    render(<AssetTabs roster={ROSTER} recentRows={[]} stats={[]} />);
    fireEvent.click(screen.getByTestId("tab-Stocks"));
    expect(screen.getByTestId("asset-tabs-empty")).toHaveTextContent(
      "No strategies match the current filters."
    );
  });
});
