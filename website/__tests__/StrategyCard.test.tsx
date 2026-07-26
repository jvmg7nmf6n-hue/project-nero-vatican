import { render, screen } from "@testing-library/react";
import StrategyCard from "@/components/StrategyCard";
import type { LedgerRow, StrategyRosterEntry } from "@/lib/types";

function makeEntry(overrides: Partial<StrategyRosterEntry> = {}): StrategyRosterEntry {
  return {
    name: "BREAKOUT_MOMENTUM",
    version: "breakout-momentum-v1.2.0-gold-calibrated-1week",
    asset: "GOLD",
    timeframe: "1week",
    verification_status: "triple-verified",
    ...overrides,
  };
}

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-26T00:00:00Z",
    strategy: "BREAKOUT_MOMENTUM",
    asset: "GOLD",
    signal_type: "ENTRY",
    entry_price: 100,
    exit_price: null,
    reasoning: "",
    candle_timestamp: "1000",
    ...overrides,
  };
}

describe("StrategyCard: research status and current signal are two separate elements", () => {
  it("renders a research-status block and a current-signal block independently", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);

    expect(screen.getByTestId("research-status")).toBeInTheDocument();
    expect(screen.getByTestId("current-signal")).toBeInTheDocument();
  });

  it("shows the tier badge inside research-status, not inside current-signal", () => {
    render(<StrategyCard entry={makeEntry({ verification_status: "triple-verified" })} recentRows={[]} stats={[]} />);

    const researchStatus = screen.getByTestId("research-status");
    const currentSignal = screen.getByTestId("current-signal");

    expect(researchStatus).toHaveTextContent("Verified");
    expect(researchStatus).toHaveTextContent("Research status");
    expect(currentSignal).not.toHaveTextContent("Verified");
    expect(currentSignal).not.toHaveTextContent("Research status");
  });

  it("shows the 'Current signal:' prefix inside current-signal, not inside research-status", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);

    const researchStatus = screen.getByTestId("research-status");
    const currentSignal = screen.getByTestId("current-signal");

    expect(currentSignal).toHaveTextContent("Current signal:");
    expect(researchStatus).not.toHaveTextContent("Current signal:");
  });

  it("keeps tier styling and signal styling on separate elements (no blending)", () => {
    render(
      <StrategyCard
        entry={makeEntry({ verification_status: "watchlist — forward-testing, not verified" })}
        recentRows={[makeRow({ signal_type: "EXIT" })]}
        stats={[]}
      />
    );

    const card = screen.getByTestId("strategy-card");
    const currentSignal = screen.getByTestId("current-signal");

    // The card's own border reflects the tier (watchlist = gold dashed)...
    expect(card.className).toContain("border-gold/60");
    expect(card.className).toContain("border-dashed");
    // ...while the signal's color (EXIT = amber) lives only on the signal row,
    // never merged into the card-level tier border classes.
    expect(card.className).not.toContain("amber");
    expect(currentSignal.innerHTML).toContain("amber");
  });
});

describe("StrategyCard current-signal color per state", () => {
  // Assert on the state-label span's own className (not innerHTML substring
  // matching) -- the "Current signal:" prefix always carries text-muted, so a
  // loose innerHTML.includes("text-muted") check would pass even for a broken
  // no_signal_yet state.
  it("colors ENTRY teal", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "ENTRY" })]} stats={[]} />);
    expect(screen.getByText("ENTRY").className).toContain("text-teal");
  });

  it("colors EXIT amber", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "EXIT" })]} stats={[]} />);
    expect(screen.getByText("EXIT").className).toContain("text-amber-400");
  });

  it("colors WATCH as neutral-gray WATCHING", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "WATCH" })]} stats={[]} />);
    expect(screen.getByText("WATCHING").className).toContain("text-gray-300");
  });

  it("colors NO_TRADE as neutral-gray WATCHING too", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[makeRow({ signal_type: "NO_TRADE" })]} stats={[]} />);
    expect(screen.getByText("WATCHING").className).toContain("text-gray-300");
  });

  it("colors an unlogged strategy muted NO SIGNAL YET", () => {
    render(<StrategyCard entry={makeEntry()} recentRows={[]} stats={[]} />);
    const label = screen.getByText("NO SIGNAL YET");
    expect(label.className).toContain("text-muted");
    expect(label.className).not.toContain("text-teal");
    expect(label.className).not.toContain("text-amber-400");
    expect(label.className).not.toContain("text-gray-300");
  });

  it("gives each of the 4 signal states a visually distinct label color class", () => {
    const cases: Array<[LedgerRow[], string, string]> = [
      [[makeRow({ signal_type: "ENTRY" })], "ENTRY", "text-teal"],
      [[makeRow({ signal_type: "EXIT" })], "EXIT", "text-amber-400"],
      [[makeRow({ signal_type: "WATCH" })], "WATCHING", "text-gray-300"],
      [[], "NO SIGNAL YET", "text-muted"],
    ];
    const seenClasses = new Set<string>();
    cases.forEach(([rows, expectedLabel, expectedClass]) => {
      const { unmount } = render(<StrategyCard entry={makeEntry()} recentRows={rows} stats={[]} />);
      const label = screen.getByText(expectedLabel);
      expect(label.className).toContain(expectedClass);
      seenClasses.add(expectedClass);
      unmount();
    });
    expect(seenClasses.size).toBe(4);
  });
});
