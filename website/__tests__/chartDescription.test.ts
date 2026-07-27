import {
  buildChartDescription,
  buildDataWindowSentence,
  buildMarkerLegendLine,
  buildTimeframeSentence,
  deriveWinLossCounts,
  timeframeLabel,
} from "@/lib/chartDescription";
import type { StrategyStats } from "@/lib/types";

function stats(overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy: "BREAKOUT_MOMENTUM",
    strategy_version: "v1",
    asset: "GOLD",
    resolved_trades: 0,
    win_rate: null,
    expectancy_r: null,
    avg_return_pct: null,
    signal_counts: { ENTRY: 0, EXIT: 0, WATCH: 0, NO_TRADE: 0 },
    open_position: null,
    ...overrides,
  };
}

describe("timeframeLabel", () => {
  it("maps roster timeframe strings to plain-language labels", () => {
    expect(timeframeLabel("1week")).toBe("1 week");
    expect(timeframeLabel("24h")).toBe("1 day");
    expect(timeframeLabel("12h")).toBe("12 hours");
    expect(timeframeLabel("1day")).toBe("1 day");
  });

  it("falls back to the raw string for an unrecognized timeframe (never fabricated)", () => {
    expect(timeframeLabel("snapshot")).toBe("snapshot");
  });
});

describe("buildTimeframeSentence", () => {
  it("builds line 1 with the asset and timeframe label", () => {
    expect(buildTimeframeSentence("GOLD", "1week")).toBe(
      "Each candle represents 1 week of GOLD price action."
    );
  });
});

describe("buildDataWindowSentence", () => {
  it("computes the time span as candleCount / periodsPerYear (years), not the literal task wording", () => {
    // 199 weekly candles / 52 periods/year ≈ 3.8 years
    expect(buildDataWindowSentence(199, "1week", 52)).toBe(
      "Showing 199 candles — approximately 3.8 years of history."
    );
  });

  it("renders a week-scale span for a shorter history", () => {
    expect(buildDataWindowSentence(20, "1week", 52)).toContain("weeks of history");
  });

  it("renders a day-scale span for a very short daily history", () => {
    expect(buildDataWindowSentence(5, "24h", 365)).toContain("days of history");
  });

  it("falls back to the calendar-derived periods_per_year when quant_metrics.json has no entry", () => {
    // No quant metrics entry (null) -- falls back to the 12h calendar constant (730/year).
    const withFallback = buildDataWindowSentence(200, "12h", null);
    expect(withFallback).toContain("of history");
  });

  it("omits the time-span clause entirely for an unrecognized timeframe with no fallback", () => {
    expect(buildDataWindowSentence(50, "snapshot", null)).toBe("Showing 50 candles.");
  });
});

describe("buildMarkerLegendLine", () => {
  it("returns null when there are zero resolved trades", () => {
    expect(buildMarkerLegendLine(0)).toBeNull();
  });

  it("returns the legend line, using teal (not green) for entry -- matches the real chart marker color", () => {
    const line = buildMarkerLegendLine(5);
    expect(line).toContain("Teal = Vatican entry signal");
    expect(line).toContain("Teal = profitable exit");
    expect(line).toContain("Red = stop-loss exit");
    expect(line).not.toContain("Green");
  });
});

describe("deriveWinLossCounts", () => {
  it("returns 0/0 for zero resolved trades", () => {
    expect(deriveWinLossCounts(0, null)).toEqual({ wins: 0, losses: 0 });
  });

  it("returns 0/0 when win_rate is null even with resolved trades (never fabricated)", () => {
    expect(deriveWinLossCounts(10, null)).toEqual({ wins: 0, losses: 0 });
  });

  it("reconstructs exact win/loss counts from resolved_trades and win_rate", () => {
    expect(deriveWinLossCounts(20, 0.6)).toEqual({ wins: 12, losses: 8 });
  });

  it("rounds to the nearest whole win count for a non-exact fraction", () => {
    expect(deriveWinLossCounts(3, 0.667)).toEqual({ wins: 2, losses: 1 });
  });
});

describe("buildChartDescription", () => {
  it("shows the 'no completed trades yet' status line and no marker legend when resolved_trades is 0", () => {
    const data = buildChartDescription({
      asset: "GOLD",
      timeframe: "1week",
      candleCount: 199,
      periodsPerYear: 52,
      statsRow: stats({ resolved_trades: 0 }),
    });
    expect(data.statusLine).toBe("No completed trades yet — strategy is live and monitoring for setups.");
    expect(data.markerLegendLine).toBeNull();
    expect(data.openPositionEntryTimestamp).toBeNull();
  });

  it("shows the trade-count status line and marker legend when resolved_trades > 0", () => {
    const data = buildChartDescription({
      asset: "GOLD",
      timeframe: "1week",
      candleCount: 199,
      periodsPerYear: 52,
      statsRow: stats({ resolved_trades: 20, win_rate: 0.6 }),
    });
    expect(data.statusLine).toBe("20 trades completed: 12 wins (60%), 8 losses.");
    expect(data.markerLegendLine).not.toBeNull();
  });

  it("surfaces the raw open_position entry_timestamp for the component to format", () => {
    const data = buildChartDescription({
      asset: "GOLD",
      timeframe: "1week",
      candleCount: 199,
      periodsPerYear: 52,
      statsRow: stats({
        resolved_trades: 5,
        win_rate: 0.4,
        open_position: { entry_price: 3200, entry_timestamp: "2026-07-20T00:00:00Z", candle_timestamp: "2026-07-20T00:00:00Z" },
      }),
    });
    expect(data.openPositionEntryTimestamp).toBe("2026-07-20T00:00:00Z");
  });

  it("handles a null statsRow as zero resolved trades, never throwing", () => {
    const data = buildChartDescription({
      asset: "GOLD",
      timeframe: "1week",
      candleCount: 199,
      periodsPerYear: 52,
      statsRow: null,
    });
    expect(data.statusLine).toContain("No completed trades yet");
  });
});
