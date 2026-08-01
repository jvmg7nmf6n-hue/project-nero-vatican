import { buildQuantMetricCards, findQuantMetricsForAsset } from "@/lib/quantPanel";
import type { QuantMetricsEntry } from "@/lib/types";

function entry(overrides: Partial<QuantMetricsEntry> = {}): QuantMetricsEntry {
  return {
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
    ...overrides,
  };
}

describe("findQuantMetricsForAsset", () => {
  it("matches on exact asset and timeframe", () => {
    const metrics = [entry({ asset: "GOLD", timeframe: "1week" }), entry({ asset: "BTC", timeframe: "24h" })];
    expect(findQuantMetricsForAsset(metrics, "BTC", "24h")).toEqual(metrics[1]);
  });

  it("applies the same 'daily' -> '24h' alias Day 2's candle lookup uses", () => {
    const metrics = [entry({ asset: "GOLD", timeframe: "24h" })];
    expect(findQuantMetricsForAsset(metrics, "GOLD", "daily")).toEqual(metrics[0]);
  });

  it("returns null when no entry matches the (asset, timeframe) pair", () => {
    const metrics = [entry({ asset: "GOLD", timeframe: "1week" })];
    expect(findQuantMetricsForAsset(metrics, "GOLD", "24h")).toBeNull();
    expect(findQuantMetricsForAsset(metrics, "SILVER", "1week")).toBeNull();
  });

  it("finds SILVER's entry even though every annualized field on it is null — a null FIELD is not a missing ENTRY", () => {
    const silverEntry = entry({
      asset: "SILVER", timeframe: "24h", periods_per_year: null,
      log_return_annualized: null, realized_vol_annualized: null, sharpe: null, sortino: null,
    });
    const metrics = [silverEntry, entry({ asset: "GOLD", timeframe: "1week" })];
    expect(findQuantMetricsForAsset(metrics, "SILVER", "24h")).toEqual(silverEntry);
  });

  it("returns null for a pair asset (no candle file, so never a quant_metrics entry)", () => {
    const metrics = [entry({ asset: "BTC", timeframe: "12h" })];
    expect(findQuantMetricsForAsset(metrics, "BTC-ETH", "12h")).toBeNull();
  });

  it("lets two strategies sharing the same (asset, timeframe) resolve to the identical entry", () => {
    const metrics = [entry({ asset: "BTC", timeframe: "24h" })];
    const first = findQuantMetricsForAsset(metrics, "BTC", "24h");
    const second = findQuantMetricsForAsset(metrics, "BTC", "24h");
    expect(first).toEqual(second);
  });
});

describe("buildQuantMetricCards", () => {
  it("returns exactly five independent cards, never a composite score", () => {
    const cards = buildQuantMetricCards(entry());
    expect(cards).toHaveLength(5);
    expect(cards.map((c) => c.key)).toEqual([
      "log_return_annualized",
      "zscore_current",
      "realized_vol_annualized",
      "sharpe",
      "sortino",
    ]);
  });

  it("formats each metric's value", () => {
    const cards = buildQuantMetricCards(entry());
    const byKey = Object.fromEntries(cards.map((c) => [c.key, c.value]));
    expect(byKey.log_return_annualized).toBe("+23.4%");
    expect(byKey.zscore_current).toBe("-1.43");
    expect(byKey.realized_vol_annualized).toBe("17.2%");
    expect(byKey.sharpe).toBe("1.15");
    expect(byKey.sortino).toBe("1.80");
  });

  it("renders a null metric as a null value (never a fabricated number)", () => {
    const cards = buildQuantMetricCards(
      entry({ sharpe: null, sortino: null, zscore_current: null, log_return_annualized: null, realized_vol_annualized: null })
    );
    for (const card of cards) {
      expect(card.value).toBeNull();
    }
  });

  // feature/timeframe-periods-asset-aware follow-up: SILVER's real -> null
  // transition. Exact shape nero_core.execution.export_quant_metrics produces
  // for SILVER today (commodity_futures has zero periods_per_year entries) --
  // regenerated from this branch's code, not hand-typed.
  it("SILVER/1week and SILVER/24h: 4 annualization-dependent cards null, z-score stays real", () => {
    const silverEntries = [
      entry({
        asset: "SILVER", timeframe: "1week", periods_per_year: null,
        log_return_annualized: null, realized_vol_annualized: null, sharpe: null, sortino: null,
        zscore_current: -1.4844614028728775,
      }),
      entry({
        asset: "SILVER", timeframe: "24h", periods_per_year: null,
        log_return_annualized: null, realized_vol_annualized: null, sharpe: null, sortino: null,
        zscore_current: 0.13605750527994404,
      }),
    ];
    for (const silverEntry of silverEntries) {
      const cards = buildQuantMetricCards(silverEntry);
      const byKey = Object.fromEntries(cards.map((c) => [c.key, c.value]));
      expect(byKey.log_return_annualized).toBeNull();
      expect(byKey.realized_vol_annualized).toBeNull();
      expect(byKey.sharpe).toBeNull();
      expect(byKey.sortino).toBeNull();
      expect(byKey.zscore_current).not.toBeNull(); // no periods_per_year dependency -- stays real
    }
  });

  it("includes the risk-free rate in the Sharpe explanation line", () => {
    const cards = buildQuantMetricCards(entry({ rf_annual: 0.05 }));
    const sharpeCard = cards.find((c) => c.key === "sharpe")!;
    expect(sharpeCard.explanation).toContain("5.00%");
  });

  it("every card has a non-empty plain-English explanation", () => {
    const cards = buildQuantMetricCards(entry());
    for (const card of cards) {
      expect(card.explanation.length).toBeGreaterThan(10);
    }
  });
});
