import { render, screen } from "@testing-library/react";
import CorrelationHeatmap from "@/components/CorrelationHeatmap";
import type { CorrelationPair } from "@/lib/types";

const PAIRS: CorrelationPair[] = [
  { asset_a: "BTC", asset_b: "GOLD", timeframe: "24h", correlation: 0.42, window_used: 30, computed_at: "x" },
];

describe("CorrelationHeatmap", () => {
  it("renders a message when there are no assets", () => {
    render(<CorrelationHeatmap assets={[]} pairs={[]} />);
    expect(screen.getByText(/no assets available/i)).toBeInTheDocument();
  });

  it("renders a cell for every asset pair, including N/A for a missing pair", () => {
    render(<CorrelationHeatmap assets={["BTC", "GOLD", "AAPL"]} pairs={PAIRS} />);
    const cells = screen.getAllByTestId("heatmap-cell");
    // 3x3 grid = 9 cells (including the 3 self/diagonal cells)
    expect(cells).toHaveLength(9);
  });

  it("shows the correlation value to 2 decimal places for a real pair", () => {
    render(<CorrelationHeatmap assets={["BTC", "GOLD"]} pairs={PAIRS} />);
    const cells = screen.getAllByTestId("heatmap-cell");
    const btcGold = cells.find((c) => c.getAttribute("data-row") === "BTC" && c.getAttribute("data-col") === "GOLD");
    expect(btcGold).toHaveTextContent("0.42");
  });

  it("shows N/A for a pair with no data, never a fabricated number", () => {
    render(<CorrelationHeatmap assets={["BTC", "AAPL"]} pairs={PAIRS} />);
    const cells = screen.getAllByTestId("heatmap-cell");
    const btcAapl = cells.find((c) => c.getAttribute("data-row") === "BTC" && c.getAttribute("data-col") === "AAPL");
    expect(btcAapl).toHaveTextContent("N/A");
  });

  it("shows a dash on the diagonal (self), never a fabricated 1.00", () => {
    render(<CorrelationHeatmap assets={["BTC", "GOLD"]} pairs={PAIRS} />);
    const cells = screen.getAllByTestId("heatmap-cell");
    const btcBtc = cells.find((c) => c.getAttribute("data-row") === "BTC" && c.getAttribute("data-col") === "BTC");
    expect(btcBtc).toHaveTextContent("—");
    expect(btcBtc).not.toHaveTextContent("1.00");
  });
});
