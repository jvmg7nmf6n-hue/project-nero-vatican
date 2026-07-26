import { render, screen } from "@testing-library/react";
import QuantPanel from "@/components/QuantPanel";
import type { QuantMetricsEntry } from "@/lib/types";

const FULL_ENTRY: QuantMetricsEntry = {
  asset: "GOLD",
  timeframe: "1week",
  periods_per_year: 52,
  window_used: 199,
  rf_annual: 0.0363,
  rf_source: "fred_dff",
  log_return_annualized: 0.2335,
  zscore_current: -1.43,
  realized_vol_annualized: 17.18,
  sharpe: 1.15,
  sortino: 1.8,
  computed_at: "2026-07-27T00:00:00+00:00",
};

describe("QuantPanel", () => {
  it("shows a graceful unavailable message when there is no entry for this asset", () => {
    render(<QuantPanel entry={null} />);
    expect(screen.getByTestId("quant-panel-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("quant-panel-grid")).not.toBeInTheDocument();
  });

  it("renders exactly five metric cards, never a composite/overall score", () => {
    render(<QuantPanel entry={FULL_ENTRY} />);
    const grid = screen.getByTestId("quant-panel-grid");
    expect(grid.children).toHaveLength(5);
    expect(screen.queryByText(/overall/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/composite/i)).not.toBeInTheDocument();
  });

  it("shows the window and timeframe context text", () => {
    render(<QuantPanel entry={FULL_ENTRY} />);
    expect(screen.getByTestId("quant-panel-context")).toHaveTextContent("199");
    expect(screen.getByTestId("quant-panel-context")).toHaveTextContent("1week");
  });

  it("renders each card's label and formatted value", () => {
    render(<QuantPanel entry={FULL_ENTRY} />);
    expect(screen.getByText("Sharpe")).toBeInTheDocument();
    expect(screen.getByTestId("quant-card-sharpe-value")).toHaveTextContent("1.15");
    expect(screen.getByTestId("quant-card-sortino-value")).toHaveTextContent("1.80");
  });

  it("renders a muted em-dash for a null metric instead of a fabricated value", () => {
    render(<QuantPanel entry={{ ...FULL_ENTRY, sharpe: null }} />);
    expect(screen.getByTestId("quant-card-sharpe-value")).toHaveTextContent("—");
  });

  it("mentions research/education framing, not trade instruction", () => {
    render(<QuantPanel entry={FULL_ENTRY} />);
    expect(screen.getByText(/not a trade instruction/i)).toBeInTheDocument();
  });
});
