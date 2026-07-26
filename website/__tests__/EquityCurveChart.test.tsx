import { render, screen } from "@testing-library/react";
import EquityCurveChart from "@/components/EquityCurveChart";
import type { EquityCurve } from "@/lib/equityCurve";

describe("EquityCurveChart", () => {
  it("renders nothing for an empty curve", () => {
    const curve: EquityCurve = { unit: "r_multiple", points: [] };
    const { container } = render(<EquityCurveChart curve={curve} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one point per trade, colored by result", () => {
    const curve: EquityCurve = {
      unit: "r_multiple",
      points: [
        { index: 1, cumulativeValue: 1, tradeResult: "win" },
        { index: 2, cumulativeValue: 0, tradeResult: "loss" },
        { index: 3, cumulativeValue: 2, tradeResult: "win" },
      ],
    };
    render(<EquityCurveChart curve={curve} />);

    const points = screen.getAllByTestId("equity-curve-point");
    expect(points).toHaveLength(3);
    expect(points[0]).toHaveAttribute("data-result", "win");
    expect(points[0]).toHaveAttribute("fill", "#2ec4b6");
    expect(points[1]).toHaveAttribute("data-result", "loss");
    expect(points[1]).toHaveAttribute("fill", "#d47a6a");
  });

  it("labels the axis with the curve's unit", () => {
    const curve: EquityCurve = {
      unit: "pct_return",
      points: [{ index: 1, cumulativeValue: 5, tradeResult: "win" }],
    };
    render(<EquityCurveChart curve={curve} />);
    expect(screen.getByText("Cumulative % return")).toBeInTheDocument();
  });

  it("labels an r_multiple curve's axis correctly", () => {
    const curve: EquityCurve = {
      unit: "r_multiple",
      points: [{ index: 1, cumulativeValue: 1, tradeResult: "win" }],
    };
    render(<EquityCurveChart curve={curve} />);
    expect(screen.getByText("Cumulative R")).toBeInTheDocument();
  });

  it("renders a single point without dividing by zero", () => {
    const curve: EquityCurve = {
      unit: "r_multiple",
      points: [{ index: 1, cumulativeValue: 3, tradeResult: "win" }],
    };
    render(<EquityCurveChart curve={curve} />);
    const points = screen.getAllByTestId("equity-curve-point");
    expect(points).toHaveLength(1);
    expect(points[0]).toHaveAttribute("cx", "320");
  });
});
