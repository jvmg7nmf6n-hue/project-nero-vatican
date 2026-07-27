import { render, screen } from "@testing-library/react";
import MarketStatusWidget from "@/components/MarketStatusWidget";
import type { VolatilityRegimeEntry } from "@/lib/types";

function regime(overrides: Partial<VolatilityRegimeEntry> = {}): VolatilityRegimeEntry {
  return {
    asset: "GOLD",
    timeframe: "1week",
    regime: "NORMAL",
    conditional_vol: 0.1,
    vol_ratio: 1.0,
    shock_score: 0.2,
    model_used: "GARCH",
    computed_at: "x",
    ...overrides,
  };
}

const BASE_PROPS = {
  priceDisplay: "$3,287.50",
  changePercent: 1.25,
  regime: regime(),
  lastCandleTimeSeconds: Math.floor(Date.UTC(2026, 6, 20, 0, 0, 0) / 1000),
  timeframe: "1week",
  signalStatus: "WATCHING" as const,
};

describe("MarketStatusWidget", () => {
  it("renders the current price from candle data", () => {
    render(<MarketStatusWidget {...BASE_PROPS} />);
    expect(screen.getByTestId("status-price")).toHaveTextContent("$3,287.50");
  });

  it("shows a dash for price when unavailable, never a fabricated value", () => {
    render(<MarketStatusWidget {...BASE_PROPS} priceDisplay={null} />);
    expect(screen.getByTestId("status-price")).toHaveTextContent("—");
  });

  it("renders a positive change in teal with a + sign", () => {
    render(<MarketStatusWidget {...BASE_PROPS} changePercent={1.25} />);
    const change = screen.getByTestId("status-change");
    expect(change).toHaveTextContent("+1.25%");
    expect(change.className).toContain("text-teal");
  });

  it("renders a negative change in loss-red with a - sign", () => {
    render(<MarketStatusWidget {...BASE_PROPS} changePercent={-2.5} />);
    const change = screen.getByTestId("status-change");
    expect(change).toHaveTextContent("-2.50%");
    expect(change.className).toContain("text-loss");
  });

  it("shows a dash for change when null", () => {
    render(<MarketStatusWidget {...BASE_PROPS} changePercent={null} />);
    expect(screen.getByTestId("status-change")).toHaveTextContent("—");
  });

  it.each([
    ["LOW", "#2ec4b6"],
    ["NORMAL", "#8a94ad"],
    ["HIGH", "#d4af37"],
    ["EXTREME", "#d47a6a"],
  ] as const)("renders the %s regime badge with its correct color", (regimeValue, expectedColor) => {
    render(<MarketStatusWidget {...BASE_PROPS} regime={regime({ regime: regimeValue })} />);
    const badge = screen.getByTestId("status-regime");
    expect(badge).toHaveAttribute("data-regime", regimeValue);
    expect(badge).toHaveTextContent(regimeValue);
    expect(badge.querySelector("span")).toHaveStyle({ color: expectedColor });
  });

  it("shows 'NO DATA' when no regime entry is available", () => {
    render(<MarketStatusWidget {...BASE_PROPS} regime={null} />);
    const badge = screen.getByTestId("status-regime");
    expect(badge).toHaveAttribute("data-regime", "NO_DATA");
    expect(badge).toHaveTextContent("NO DATA");
  });

  it("initializes the countdown with a computed 'Next candle' label", () => {
    render(<MarketStatusWidget {...BASE_PROPS} />);
    expect(screen.getByTestId("status-countdown")).toHaveTextContent("Next candle:");
  });

  it("shows a dash for countdown when there's no last candle time", () => {
    render(<MarketStatusWidget {...BASE_PROPS} lastCandleTimeSeconds={null} />);
    expect(screen.getByTestId("status-countdown")).toHaveTextContent("—");
  });

  it.each([
    ["ENTRY ACTIVE"],
    ["WATCHING"],
    ["NO SIGNAL"],
  ] as const)("renders the %s signal pill", (status) => {
    render(<MarketStatusWidget {...BASE_PROPS} signalStatus={status} />);
    const pill = screen.getByTestId("status-signal-pill");
    expect(pill).toHaveAttribute("data-status", status);
    expect(pill).toHaveTextContent(status);
  });

  it("registers a 60-second interval on mount and clears it on unmount (never lets it fire in tests)", () => {
    const setIntervalSpy = jest.spyOn(window, "setInterval");
    const clearIntervalSpy = jest.spyOn(window, "clearInterval");

    const { unmount } = render(<MarketStatusWidget {...BASE_PROPS} />);
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 60_000);

    unmount();
    expect(clearIntervalSpy).toHaveBeenCalled();

    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  });
});
