import { render, screen } from "@testing-library/react";
import LedgerTable, { isLoss, resultLabel } from "@/components/LedgerTable";
import type { LedgerRow } from "@/lib/types";

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-17T12:00:00Z",
    strategy: "BREAKOUT_MOMENTUM",
    asset: "GOLD",
    signal_type: "EXIT",
    entry_price: 100,
    exit_price: 90,
    reasoning: "Stop loss hit",
    candle_timestamp: "1752753600000",
    ...overrides,
  };
}

describe("LedgerTable empty state", () => {
  it("shows the tracking-since date when provided", () => {
    render(<LedgerTable rows={[]} trackingSince="2026-07-17" />);
    const empty = screen.getByTestId("ledger-empty-state");
    expect(empty.textContent).toContain("2026-07-17");
    expect(empty.textContent).toContain("No signals logged yet.");
  });

  it("shows a generic message when no tracking-since date is provided", () => {
    render(<LedgerTable rows={[]} />);
    const empty = screen.getByTestId("ledger-empty-state");
    expect(empty.textContent).toBe("No signals logged yet.");
  });
});

describe("LedgerTable populated state", () => {
  it("renders expected columns and row content", () => {
    const rows = [makeRow()];
    render(<LedgerTable rows={rows} />);

    expect(screen.getByTestId("ledger-table")).toBeInTheDocument();
    expect(screen.getByText("Timestamp")).toBeInTheDocument();
    expect(screen.getByText("Strategy")).toBeInTheDocument();
    expect(screen.getByText("Signal")).toBeInTheDocument();
    expect(screen.getByText("Result")).toBeInTheDocument();
    expect(screen.getByText(/BREAKOUT_MOMENTUM/)).toBeInTheDocument();
    expect(screen.getByText("EXIT")).toBeInTheDocument();
  });

  it("applies loss styling to a losing EXIT row", () => {
    const rows = [makeRow({ entry_price: 100, exit_price: 90 })];
    render(<LedgerTable rows={rows} />);
    const resultCell = screen.getByText("Stop loss hit");
    expect(resultCell.className).toContain("text-loss");
    expect(isLoss(rows[0])).toBe(true);
  });

  it("does not apply loss styling to a winning EXIT row", () => {
    const rows = [
      makeRow({ entry_price: 100, exit_price: 110, reasoning: "Target hit" }),
    ];
    render(<LedgerTable rows={rows} />);
    const resultCell = screen.getByText("Target hit");
    expect(resultCell.className).not.toContain("text-loss");
    expect(isLoss(rows[0])).toBe(false);
  });

  it("always shows the losses caption when rows are present", () => {
    render(<LedgerTable rows={[makeRow()]} />);
    expect(
      screen.getByText("Losses shown above are real and stay on the record.")
    ).toBeInTheDocument();
  });
});

describe("resultLabel", () => {
  it("labels ENTRY rows with the opening price", () => {
    const row = makeRow({ signal_type: "ENTRY", entry_price: 105, reasoning: "" });
    expect(resultLabel(row)).toBe("Opened @ 105");
  });
});
