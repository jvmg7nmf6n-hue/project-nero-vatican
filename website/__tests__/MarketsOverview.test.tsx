import { fireEvent, render, screen } from "@testing-library/react";
import MarketsOverview from "@/components/MarketsOverview";
import type { MarketTile } from "@/lib/marketsOverview";
import type { VolatilityRegimeEntry } from "@/lib/types";

const OK_TILE: MarketTile = {
  status: "ok",
  asset: "BTC",
  timeframe: "24h",
  price: 65432.1,
  changePct: 2.5,
  sparklinePath: "M 0,32 L 100,0",
  trend: "up",
  strategyCount: 3,
};

const PLACEHOLDER_TILE: MarketTile = { status: "placeholder", asset: "ETH", strategyCount: 1 };

describe("MarketsOverview", () => {
  it("renders nothing when there are no tiles", () => {
    const { container } = render(<MarketsOverview tiles={[]} onSelectAsset={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a real tile with price, change%, sparkline, and strategy count", () => {
    render(<MarketsOverview tiles={[OK_TILE]} onSelectAsset={jest.fn()} />);

    const tile = screen.getByTestId("market-tile");
    expect(tile).toHaveAttribute("data-asset", "BTC");
    expect(tile).toHaveAttribute("data-status", "ok");
    expect(screen.getByText("BTC")).toBeInTheDocument();
    expect(screen.getByText("65,432.10")).toBeInTheDocument();
    expect(screen.getByText("+2.50%")).toBeInTheDocument();
    expect(screen.getByText("3 strategies watching")).toBeInTheDocument();
    expect(screen.getByTestId("market-tile-sparkline")).toBeInTheDocument();
    expect(screen.queryByTestId("market-tile-placeholder")).not.toBeInTheDocument();
  });

  it("colors a positive change% teal and a negative one loss-red", () => {
    const losing: MarketTile = { ...OK_TILE, asset: "XRP", changePct: -1.2 };
    render(<MarketsOverview tiles={[OK_TILE, losing]} onSelectAsset={jest.fn()} />);

    const changes = screen.getAllByTestId("market-tile-change");
    expect(changes[0]).toHaveClass("text-teal");
    expect(changes[1]).toHaveClass("text-loss");
    expect(changes[1]).toHaveTextContent("-1.20%");
  });

  it("shows 'n/a' without a color class when changePct is null", () => {
    const noChange: MarketTile = { ...OK_TILE, changePct: null };
    render(<MarketsOverview tiles={[noChange]} onSelectAsset={jest.fn()} />);
    const change = screen.getByTestId("market-tile-change");
    expect(change).toHaveTextContent("n/a");
    expect(change).toHaveClass("text-muted");
  });

  it("renders a neutral placeholder tile with no price or sparkline", () => {
    render(<MarketsOverview tiles={[PLACEHOLDER_TILE]} onSelectAsset={jest.fn()} />);

    const tile = screen.getByTestId("market-tile");
    expect(tile).toHaveAttribute("data-status", "placeholder");
    expect(screen.getByTestId("market-tile-placeholder")).toHaveTextContent("No price data yet");
    expect(screen.getByText("1 strategy watching")).toBeInTheDocument();
    expect(screen.queryByTestId("market-tile-sparkline")).not.toBeInTheDocument();
  });

  it("calls onSelectAsset with the tile's asset when clicked", () => {
    const onSelectAsset = jest.fn();
    render(<MarketsOverview tiles={[OK_TILE, PLACEHOLDER_TILE]} onSelectAsset={onSelectAsset} />);

    fireEvent.click(screen.getAllByTestId("market-tile")[1]);
    expect(onSelectAsset).toHaveBeenCalledWith("ETH");
    expect(onSelectAsset).toHaveBeenCalledTimes(1);
  });

  describe("volatility regime badge (Day 5)", () => {
    const REGIME: VolatilityRegimeEntry = {
      asset: "BTC",
      timeframe: "24h",
      regime: "HIGH",
      conditional_vol: 0.5,
      vol_ratio: 1.3,
      shock_score: 65,
      model_used: "EWMA fallback",
      computed_at: "x",
    };

    it("renders the regime badge with a colored dot and label when a matching entry exists", () => {
      render(<MarketsOverview tiles={[OK_TILE]} onSelectAsset={jest.fn()} volatilityRegimes={[REGIME]} />);
      const badge = screen.getByTestId("market-tile-regime");
      expect(badge).toHaveTextContent("HIGH");
      expect(screen.getByTestId("market-tile-regime-dot")).toBeInTheDocument();
    });

    it("shows nothing (no broken tile) when volatilityRegimes is empty", () => {
      render(<MarketsOverview tiles={[OK_TILE]} onSelectAsset={jest.fn()} />);
      expect(screen.queryByTestId("market-tile-regime")).not.toBeInTheDocument();
    });

    it("shows nothing when the regimes array has no entry for this asset", () => {
      const otherAssetRegime: VolatilityRegimeEntry = { ...REGIME, asset: "GOLD" };
      render(<MarketsOverview tiles={[OK_TILE]} onSelectAsset={jest.fn()} volatilityRegimes={[otherAssetRegime]} />);
      expect(screen.queryByTestId("market-tile-regime")).not.toBeInTheDocument();
    });

    it("shows nothing when the asset matches but the timeframe doesn't", () => {
      const wrongTimeframe: VolatilityRegimeEntry = { ...REGIME, timeframe: "1week" };
      render(<MarketsOverview tiles={[OK_TILE]} onSelectAsset={jest.fn()} volatilityRegimes={[wrongTimeframe]} />);
      expect(screen.queryByTestId("market-tile-regime")).not.toBeInTheDocument();
    });

    it("never renders a regime badge on a placeholder tile", () => {
      render(
        <MarketsOverview
          tiles={[PLACEHOLDER_TILE]}
          onSelectAsset={jest.fn()}
          volatilityRegimes={[{ ...REGIME, asset: "ETH" }]}
        />
      );
      expect(screen.queryByTestId("market-tile-regime")).not.toBeInTheDocument();
    });
  });
});
