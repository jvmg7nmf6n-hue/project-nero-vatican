import { fireEvent, render, screen } from "@testing-library/react";
import ChartDescription from "@/components/ChartDescription";
import type { ChartDescriptionData } from "@/lib/chartDescription";

function data(overrides: Partial<ChartDescriptionData> = {}): ChartDescriptionData {
  return {
    timeframeSentence: "Each candle represents 1 week of GOLD price action.",
    dataWindowSentence: "Showing 199 candles — approximately 3.8 years of history.",
    markerLegendLine: null,
    statusLine: "No completed trades yet — strategy is live and monitoring for setups.",
    openPositionEntryTimestamp: null,
    ...overrides,
  };
}

describe("ChartDescription", () => {
  it("starts collapsed, showing only the toggle", () => {
    render(<ChartDescription data={data()} />);
    expect(screen.getByTestId("chart-description-toggle")).toBeInTheDocument();
    expect(screen.queryByTestId("chart-description-body")).not.toBeInTheDocument();
  });

  it("expands to show all lines on toggle click", () => {
    render(<ChartDescription data={data()} />);
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.getByTestId("chart-description-body")).toBeInTheDocument();
    expect(screen.getByTestId("chart-description-timeframe")).toHaveTextContent(
      "Each candle represents 1 week of GOLD price action."
    );
    expect(screen.getByTestId("chart-description-window")).toHaveTextContent(
      "Showing 199 candles — approximately 3.8 years of history."
    );
  });

  it("collapses again on a second toggle click", () => {
    render(<ChartDescription data={data()} />);
    const toggle = screen.getByTestId("chart-description-toggle");
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(screen.queryByTestId("chart-description-body")).not.toBeInTheDocument();
  });

  it("renders the 'no trades yet' status line when resolved_trades is 0", () => {
    render(<ChartDescription data={data({ statusLine: "No completed trades yet — strategy is live and monitoring for setups." })} />);
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.getByTestId("chart-description-status")).toHaveTextContent("No completed trades yet");
  });

  it("renders the trade-count status line when resolved_trades > 0", () => {
    render(<ChartDescription data={data({ statusLine: "20 trades completed: 12 wins (60%), 8 losses." })} />);
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.getByTestId("chart-description-status")).toHaveTextContent("20 trades completed: 12 wins (60%), 8 losses.");
  });

  it("omits the marker legend line when null", () => {
    render(<ChartDescription data={data({ markerLegendLine: null })} />);
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.queryByTestId("chart-description-legend")).not.toBeInTheDocument();
  });

  it("shows the marker legend line when present", () => {
    render(
      <ChartDescription
        data={data({ markerLegendLine: "▲ Teal = Vatican entry signal | ▼ Teal = profitable exit | ▼ Red = stop-loss exit" })}
      />
    );
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.getByTestId("chart-description-legend")).toHaveTextContent("Vatican entry signal");
  });

  it("shows the formatted open-position line only when an open position exists", () => {
    render(<ChartDescription data={data({ openPositionEntryTimestamp: null })} />);
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.queryByTestId("chart-description-open-position")).not.toBeInTheDocument();
  });

  it("formats the open-position timestamp with the site's standard formatTimestamp helper", () => {
    render(<ChartDescription data={data({ openPositionEntryTimestamp: "2026-07-20T00:00:00Z" })} />);
    fireEvent.click(screen.getByTestId("chart-description-toggle"));
    expect(screen.getByTestId("chart-description-open-position")).toHaveTextContent("Active trade open since");
  });
});
