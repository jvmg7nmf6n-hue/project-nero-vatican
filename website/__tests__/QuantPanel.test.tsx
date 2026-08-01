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

// feature/timeframe-periods-asset-aware follow-up: the EXACT shape
// nero_core.execution.export_quant_metrics.export_quant_metrics() produces for
// SILVER today (regenerated directly from this branch's code against real
// docs/site_data/candles/ files and copied verbatim -- not hand-typed) --
// SILVER is commodity_futures, which has zero periods_per_year entries (see
// quant_panel.py's own TIMEFRAME_PERIODS_PER_YEAR docstring), so every
// annualized field is null while window_used/rf_annual/zscore_current (which
// has no periods_per_year dependency at all) stay real. Before this branch,
// these two entries carried real (but per the branch's own investigation,
// unverified/likely-incorrect) numbers -- this is the real -> null direction
// Task 3 didn't yet cover (only null -> real, for the newly-enabled non-forex
// "4h" entries, was checked there).
const SILVER_1WEEK_ENTRY: QuantMetricsEntry = {
  asset: "SILVER",
  timeframe: "1week",
  periods_per_year: null,
  window_used: 199,
  rf_annual: 0.0363,
  rf_source: "fred_dff",
  log_return_annualized: null,
  zscore_current: -1.4844614028728775,
  realized_vol_annualized: null,
  sharpe: null,
  sortino: null,
  computed_at: "2026-08-01T08:13:40.781137+00:00",
};

const SILVER_24H_ENTRY: QuantMetricsEntry = {
  ...SILVER_1WEEK_ENTRY,
  timeframe: "24h",
  zscore_current: 0.13605750527994404,
};

describe("QuantPanel — SILVER real -> null transition (feature/timeframe-periods-asset-aware follow-up)", () => {
  it.each([
    ["SILVER/1week", SILVER_1WEEK_ENTRY],
    ["SILVER/24h", SILVER_24H_ENTRY],
  ])("%s: renders all 4 annualization-dependent cards as an em-dash, never a raw null/undefined/blank", (_label, entry) => {
    render(<QuantPanel entry={entry} />);
    for (const key of ["log_return_annualized", "realized_vol_annualized", "sharpe", "sortino"]) {
      const el = screen.getByTestId(`quant-card-${key}-value`);
      expect(el).toHaveTextContent("—");
      expect(el.textContent).not.toMatch(/null|undefined|NaN/i);
      expect(el.textContent?.trim().length).toBeGreaterThan(0); // never blank
    }
  });

  it.each([
    ["SILVER/1week", SILVER_1WEEK_ENTRY],
    ["SILVER/24h", SILVER_24H_ENTRY],
  ])("%s: still renders the real z-score (no periods_per_year dependency) — a mixed null/real record doesn't break", (_label, entry) => {
    render(<QuantPanel entry={entry} />);
    const zscoreEl = screen.getByTestId("quant-card-zscore_current-value");
    expect(zscoreEl).not.toHaveTextContent("—");
    expect(zscoreEl.textContent).toMatch(/^[+-]\d+\.\d{2}$/);
  });

  it.each([
    ["SILVER/1week", SILVER_1WEEK_ENTRY],
    ["SILVER/24h", SILVER_24H_ENTRY],
  ])("%s: layout is not broken — still exactly 5 cards, grid and context both present", (_label, entry) => {
    render(<QuantPanel entry={entry} />);
    expect(screen.getByTestId("quant-panel-grid").children).toHaveLength(5);
    expect(screen.getByTestId("quant-panel-context")).toBeInTheDocument();
    expect(screen.queryByTestId("quant-panel-unavailable")).not.toBeInTheDocument();
  });
});

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
