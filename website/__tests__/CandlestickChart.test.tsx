import { render } from "@testing-library/react";
import CandlestickChart from "@/components/CandlestickChart";
import { createChart } from "lightweight-charts";
import type { Candle } from "@/lib/candleData";
import type { ChartMarker } from "@/lib/chartMarkers";

const mockCreateChart = jest.mocked(createChart);

function latestChart() {
  const chart = mockCreateChart.mock.results[mockCreateChart.mock.results.length - 1].value;
  const series = chart.addCandlestickSeries.mock.results[chart.addCandlestickSeries.mock.results.length - 1].value;
  return { chart, series };
}

const CANDLES: Candle[] = [
  { time: 1, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 },
  { time: 2, open: 100.5, high: 102, low: 100, close: 101.5, volume: 1200 },
];

const MARKERS: ChartMarker[] = [{ time: 1, position: "belowBar", color: "#2ec4b6", shape: "arrowUp", text: "ENTRY" }];

describe("CandlestickChart", () => {
  beforeEach(() => {
    mockCreateChart.mockClear();
  });

  it("renders a container div", () => {
    const { getByTestId } = render(<CandlestickChart candles={CANDLES} markers={[]} />);
    expect(getByTestId("candlestick-chart")).toBeInTheDocument();
  });

  it("creates the chart with the design-system colors and loads the candle data", () => {
    render(<CandlestickChart candles={CANDLES} markers={MARKERS} />);

    expect(mockCreateChart).toHaveBeenCalledTimes(1);
    const chartOptions = mockCreateChart.mock.calls[0][1];
    expect(chartOptions?.layout?.background).toMatchObject({ color: "#0a0e27" });
    expect(chartOptions?.grid?.vertLines).toMatchObject({ color: "#1a2040" });

    const { chart, series } = latestChart();
    expect(chart.addCandlestickSeries).toHaveBeenCalledWith(
      expect.objectContaining({ upColor: "#2ec4b6", downColor: "#d47a6a" })
    );
    expect(series.setData).toHaveBeenCalledWith(CANDLES);
    expect(series.setMarkers).toHaveBeenCalledWith(MARKERS);
  });

  it("does not call setMarkers when there are no markers", () => {
    render(<CandlestickChart candles={CANDLES} markers={[]} />);
    const { series } = latestChart();
    expect(series.setMarkers).not.toHaveBeenCalled();
  });

  it("does not create a chart at all when there are no candles", () => {
    render(<CandlestickChart candles={[]} markers={[]} />);
    expect(mockCreateChart).not.toHaveBeenCalled();
  });

  it("removes the chart on unmount", () => {
    const { unmount } = render(<CandlestickChart candles={CANDLES} markers={[]} />);
    const { chart } = latestChart();
    unmount();
    expect(chart.remove).toHaveBeenCalledTimes(1);
  });

  it("adds no overlay line series when no overlays are requested", () => {
    render(<CandlestickChart candles={CANDLES} markers={[]} />);
    const { chart } = latestChart();
    expect(chart.addLineSeries).not.toHaveBeenCalled();
  });

  it("adds a line series per requested overlay, with distinct colors", () => {
    render(<CandlestickChart candles={CANDLES} markers={[]} overlays={{ ma: true, ema: true }} />);
    const { chart } = latestChart();
    expect(chart.addLineSeries).toHaveBeenCalledTimes(2);
    const colors = chart.addLineSeries.mock.calls.map((c: unknown[]) => (c[0] as { color: string }).color);
    expect(new Set(colors).size).toBe(2);
  });

  it("bollinger overlay adds two line series (upper + lower)", () => {
    render(<CandlestickChart candles={CANDLES} markers={[]} overlays={{ bollinger: true }} />);
    const { chart } = latestChart();
    expect(chart.addLineSeries).toHaveBeenCalledTimes(2);
  });

  it("vwap overlay adds no series when any candle has null volume (never fabricates)", () => {
    const candlesWithNullVolume: Candle[] = [
      { time: 1, open: 100, high: 101, low: 99, close: 100.5, volume: null },
      { time: 2, open: 100.5, high: 102, low: 100, close: 101.5, volume: 1200 },
    ];
    render(<CandlestickChart candles={candlesWithNullVolume} markers={[]} overlays={{ vwap: true }} />);
    const { chart } = latestChart();
    expect(chart.addLineSeries).not.toHaveBeenCalled();
  });
});
