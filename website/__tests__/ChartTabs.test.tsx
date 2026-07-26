import { fireEvent, render, screen } from "@testing-library/react";
import ChartTabs from "@/components/ChartTabs";
import type { Candle } from "@/lib/candleData";
import type { EquityCurve } from "@/lib/equityCurve";

const CANDLES: Candle[] = [{ time: 1, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 }];
const EQUITY_CURVE: EquityCurve = { unit: "r_multiple", points: [{ index: 1, cumulativeValue: 1, tradeResult: "win" }] };

describe("ChartTabs", () => {
  it("defaults to the Price Chart tab when candle data is available", () => {
    render(<ChartTabs candles={CANDLES} markers={[]} equityCurve={EQUITY_CURVE} />);
    expect(screen.getByTestId("tab-price-chart")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
  });

  it("defaults to the Equity Curve tab when no candle data is available", () => {
    render(<ChartTabs candles={null} markers={[]} equityCurve={EQUITY_CURVE} />);
    expect(screen.getByTestId("tab-equity-curve")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
  });

  it("switches between tabs on click", () => {
    render(<ChartTabs candles={CANDLES} markers={[]} equityCurve={EQUITY_CURVE} />);

    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("equity-curve-chart")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tab-equity-curve"));
    expect(screen.getByTestId("equity-curve-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("candlestick-chart")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tab-price-chart"));
    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
  });

  it("shows 'Price chart coming soon' when the candle file was never in Day 1's export scope", () => {
    render(<ChartTabs candles={null} markers={[]} equityCurve={null} priceChartUnavailableReason="missing" />);
    fireEvent.click(screen.getByTestId("tab-price-chart"));
    expect(screen.getByTestId("price-chart-unavailable")).toHaveTextContent("Price chart coming soon.");
  });

  it("shows 'Price data temporarily unavailable' when the candle fetch failed", () => {
    render(<ChartTabs candles={null} markers={[]} equityCurve={null} priceChartUnavailableReason="error" />);
    fireEvent.click(screen.getByTestId("tab-price-chart"));
    expect(screen.getByTestId("price-chart-unavailable")).toHaveTextContent("Price data temporarily unavailable.");
  });

  it("shows the awaiting state on the Equity Curve tab when there are zero resolved trades", () => {
    render(<ChartTabs candles={null} markers={[]} equityCurve={null} />);
    expect(screen.getByTestId("equity-curve-awaiting")).toBeInTheDocument();
  });

  it("still renders the chart (with no markers) when there are zero resolved trades but candle data exists", () => {
    render(<ChartTabs candles={CANDLES} markers={[]} equityCurve={null} />);
    expect(screen.getByTestId("candlestick-chart")).toBeInTheDocument();
  });
});
