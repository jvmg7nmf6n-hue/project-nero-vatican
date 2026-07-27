import { fireEvent, render, screen } from "@testing-library/react";
import MarketsSection from "@/components/MarketsSection";
import type { MarketTile } from "@/lib/marketsOverview";
import type { StrategyRosterEntry } from "@/lib/types";

const ROSTER: StrategyRosterEntry[] = [
  {
    name: "BREAKOUT_MOMENTUM",
    version: "v1",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "triple-verified",
    source_report: null,
  },
  {
    name: "MEAN_REVERSION",
    version: "v1",
    asset: "BTC",
    timeframe: "24h",
    verification_status: "verified",
    source_report: null,
  },
];

const TILES: MarketTile[] = [
  { status: "ok", asset: "GOLD", timeframe: "1week", price: 2000, changePct: 1.0, sparklinePath: "M 0,0", trend: "up", strategyCount: 1 },
  { status: "ok", asset: "BTC", timeframe: "24h", price: 65000, changePct: -0.5, sparklinePath: "M 0,0", trend: "down", strategyCount: 1 },
];

describe("MarketsSection", () => {
  const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;

  beforeEach(() => {
    HTMLElement.prototype.scrollIntoView = jest.fn();
  });

  afterEach(() => {
    HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
  });

  it("defaults to no asset filter when none is provided", () => {
    render(<MarketsSection roster={ROSTER} recentRows={[]} stats={[]} tiles={TILES} />);
    expect(screen.queryByTestId("asset-filter-banner")).not.toBeInTheDocument();
  });

  it("honors an initialAssetFilter (the /heatmap '?asset=' entry path)", () => {
    render(<MarketsSection roster={ROSTER} recentRows={[]} stats={[]} tiles={TILES} initialAssetFilter="BTC" />);
    expect(screen.getByTestId("asset-filter-banner")).toHaveTextContent("BTC");
  });

  it("clicking a market tile sets the AssetTabs filter to that asset, without navigating", () => {
    render(<MarketsSection roster={ROSTER} recentRows={[]} stats={[]} tiles={TILES} />);

    expect(screen.queryByTestId("asset-filter-banner")).not.toBeInTheDocument();

    const goldTile = screen.getAllByTestId("market-tile").find((t) => t.getAttribute("data-asset") === "GOLD")!;
    fireEvent.click(goldTile);

    expect(screen.getByTestId("asset-filter-banner")).toHaveTextContent("GOLD");
  });

  it("smooth-scrolls to the asset-tabs section on tile click", () => {
    render(<MarketsSection roster={ROSTER} recentRows={[]} stats={[]} tiles={TILES} />);

    const btcTile = screen.getAllByTestId("market-tile").find((t) => t.getAttribute("data-asset") === "BTC")!;
    fireEvent.click(btcTile);

    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });

  it("clicking a different tile re-filters (previous filter is replaced, not merged)", () => {
    render(<MarketsSection roster={ROSTER} recentRows={[]} stats={[]} tiles={TILES} />);
    const tiles = screen.getAllByTestId("market-tile");

    fireEvent.click(tiles.find((t) => t.getAttribute("data-asset") === "GOLD")!);
    expect(screen.getByTestId("asset-filter-banner")).toHaveTextContent("GOLD");

    fireEvent.click(tiles.find((t) => t.getAttribute("data-asset") === "BTC")!);
    expect(screen.getByTestId("asset-filter-banner")).toHaveTextContent("BTC");
  });
});
