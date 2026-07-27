import { fireEvent, render, screen } from "@testing-library/react";
import ResearchScoreboard from "@/components/ResearchScoreboard";
import type { ScoreboardRow } from "@/lib/researchScoreboard";

const ROWS: ScoreboardRow[] = [
  { name: "BREAKOUT_MOMENTUM", family: "BREAKOUT_MOMENTUM", asset: "GOLD", timeframe: "1week", status: "verified", winRate: 0.6, sourceDoc: "docs/a.md" },
  { name: "TREND_PULLBACK", family: "TREND_PULLBACK", asset: "BNB", timeframe: "12h", status: "watchlist", winRate: 0.4, sourceDoc: null },
  { name: "FVG_REVERSION", family: "Fair Value Gap", asset: null, timeframe: null, status: "died", winRate: null, sourceDoc: "docs/fvg.md" },
  { name: "LIQUIDATION_PREDICTOR", family: "Order-Book / Liquidation", asset: null, timeframe: null, status: "blocked", winRate: null, sourceDoc: "docs/liq.md" },
];

describe("ResearchScoreboard", () => {
  it("renders a no-history message when there are no rows", () => {
    render(<ResearchScoreboard rows={[]} />);
    expect(screen.getByText("No research history recorded yet.")).toBeInTheDocument();
  });

  it("renders one row per strategy across verified, watchlist, died, and blocked", () => {
    render(<ResearchScoreboard rows={ROWS} />);
    expect(screen.getAllByTestId("scoreboard-row")).toHaveLength(4);
  });

  it("filters to only the selected status", () => {
    render(<ResearchScoreboard rows={ROWS} />);
    fireEvent.click(screen.getByTestId("scoreboard-filter-died"));
    const rows = screen.getAllByTestId("scoreboard-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute("data-status", "died");
  });

  it("shows an empty-filter message when a status has no matching rows", () => {
    render(<ResearchScoreboard rows={ROWS.filter((r) => r.status !== "died")} />);
    fireEvent.click(screen.getByTestId("scoreboard-filter-died"));
    expect(screen.getByTestId("scoreboard-empty")).toBeInTheDocument();
  });

  it("returns to showing all rows when 'All' is clicked again", () => {
    render(<ResearchScoreboard rows={ROWS} />);
    fireEvent.click(screen.getByTestId("scoreboard-filter-blocked"));
    expect(screen.getAllByTestId("scoreboard-row")).toHaveLength(1);
    fireEvent.click(screen.getByTestId("scoreboard-filter-All"));
    expect(screen.getAllByTestId("scoreboard-row")).toHaveLength(4);
  });

  it("sorts by win rate descending on first click, ascending on second click", () => {
    render(<ResearchScoreboard rows={ROWS} />);
    const sortButton = screen.getByTestId("scoreboard-sort-winrate");

    fireEvent.click(sortButton);
    let names = screen.getAllByTestId("scoreboard-row").map((r) => r.textContent);
    expect(names[0]).toContain("BREAKOUT_MOMENTUM");
    expect(names[1]).toContain("TREND_PULLBACK");

    fireEvent.click(sortButton);
    names = screen.getAllByTestId("scoreboard-row").map((r) => r.textContent);
    expect(names[0]).toContain("TREND_PULLBACK");
    expect(names[1]).toContain("BREAKOUT_MOMENTUM");
  });

  it("shows a dash for asset/timeframe/win-rate/source when null, never a fabricated value", () => {
    render(<ResearchScoreboard rows={[ROWS[2]]} />);
    const row = screen.getByTestId("scoreboard-row");
    expect(row.textContent).toContain("—");
  });

  it("links to the source report only when sourceDoc is present", () => {
    render(<ResearchScoreboard rows={[ROWS[1]]} />);
    expect(screen.queryByRole("link", { name: "report" })).not.toBeInTheDocument();
  });
});
