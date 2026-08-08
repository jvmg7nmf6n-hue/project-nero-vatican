import { render, screen } from "@testing-library/react";
import SurvivorsSection from "@/components/SurvivorsSection";
import type { SurvivorDistanceExport } from "@/lib/types";

const NOW = new Date("2026-08-08T12:00:00Z");

const DISTANCE_EXPORT: SurvivorDistanceExport = {
  schema_version: 1,
  last_updated: "2026-08-08T01:10:34.545132+00:00",
  distances: [
    {
      strategy_id: "BREAKOUT_MOMENTUM",
      asset: "GOLD",
      timeframe: "1week",
      candle_close_time_ms: 1785628800000,
      computed_at: "2026-08-08T01:10:34.545132+00:00",
      conditions: [
        { label: "close vs prior 20-week high (breakout level)", unit: "pct", distance: -15.796 },
        { label: "close vs 200-period moving average", unit: "pct", distance: 48.539 },
        { label: "RSI(14) vs momentum floor (50.0)", unit: "rsi_points", distance: -13.779 },
      ],
    },
    {
      strategy_id: "COINTEGRATION_PAIRS",
      asset: "BTC-ETH",
      timeframe: "12h",
      candle_close_time_ms: 1786147199999,
      computed_at: "2026-08-08T01:10:34.545132+00:00",
      conditions: [
        {
          label: "|z-score of spread| vs entry threshold (2.0)",
          unit: "z_units",
          distance: 1.3971,
          raw_zscore: 0.6029,
          note: "0 or below means the threshold is currently met",
        },
      ],
    },
  ],
  errors: [{ strategy: "TREND_PULLBACK/BNB", message: "FileNotFoundError: no candle file" }],
};

describe("SurvivorsSection", () => {
  it("renders all 3 real survivors with '0 live entries yet' stated plainly for each", () => {
    render(<SurvivorsSection survivorDistance={DISTANCE_EXPORT} now={NOW} />);
    expect(screen.getByText("BREAKOUT_MOMENTUM")).toBeInTheDocument();
    expect(screen.getByText("TREND_PULLBACK")).toBeInTheDocument();
    expect(screen.getByText("COINTEGRATION_PAIRS")).toBeInTheDocument();
    expect(screen.getAllByText("0 live entries yet")).toHaveLength(3);
  });

  it("shows real backtest metrics labeled as backtest, not a live performance claim", () => {
    render(<SurvivorsSection survivorDistance={DISTANCE_EXPORT} now={NOW} />);
    expect(screen.getAllByText(/Backtest \(historical, not live\)/).length).toBeGreaterThan(0);
    expect(screen.getByText(/N=63, 63.5% win/)).toBeInTheDocument();
  });

  it("renders real distance conditions when data is present", () => {
    render(<SurvivorsSection survivorDistance={DISTANCE_EXPORT} now={NOW} />);
    expect(screen.getByText("close vs prior 20-week high (breakout level)")).toBeInTheDocument();
    expect(screen.getByText("|z-score of spread| vs entry threshold (2.0)")).toBeInTheDocument();
  });

  it("shows an honest unavailable state for a survivor missing from the distance export (never a fabricated number)", () => {
    render(<SurvivorsSection survivorDistance={DISTANCE_EXPORT} now={NOW} />);
    expect(screen.getByText("Live distance data unavailable right now.")).toBeInTheDocument();
  });

  it("shows an honest unavailable state for every card when the whole export is null", () => {
    render(<SurvivorsSection survivorDistance={null} now={NOW} />);
    expect(screen.getAllByText("Live distance data unavailable right now.")).toHaveLength(3);
  });

  it("links to the real strategy detail page and the real verification report for each survivor", () => {
    render(<SurvivorsSection survivorDistance={DISTANCE_EXPORT} now={NOW} />);
    const strategyLinks = screen.getAllByText("Strategy detail");
    expect(strategyLinks).toHaveLength(3);
    expect(strategyLinks[0].closest("a")).toHaveAttribute(
      "href",
      "/strategy/breakout-momentum--gold--breakout-momentum-v1-2-0-gold-calibrated-1week"
    );
    const reportLinks = screen.getAllByText("Verification report");
    expect(reportLinks[0].closest("a")).toHaveAttribute(
      "href",
      "https://github.com/jvmg7nmf6n-hue/project-nero-vatican/blob/main/docs/statistical_harness_upgrade.md"
    );
  });

  it("cross-links to ORDERFLOW_IMBALANCE's own real live-activity page", () => {
    render(<SurvivorsSection survivorDistance={DISTANCE_EXPORT} now={NOW} />);
    const link = screen.getByText(/ORDERFLOW_IMBALANCE.*live activity/i);
    expect(link.closest("a")).toHaveAttribute("href", "/strategy/orderflow-imbalance--btc--orderflow-imbalance-v1-0-0");
  });

  it("never renders any time-to-trigger, ETA, or prediction language anywhere in the section", () => {
    const { container } = render(<SurvivorsSection survivorDistance={DISTANCE_EXPORT} now={NOW} />);
    const text = container.textContent?.toLowerCase() ?? "";
    // Word-boundary patterns -- a bare "eta" substring check would false-positive
    // on ordinary words like "detail"/"metadata" ("d-ETA-il"); \b anchors to a
    // real standalone word/phrase instead.
    const forbidden = [
      /\beta\b/, /expected within/, /estimated time/, /time until/, /time to trigger/,
      /candles until/, /minutes until/, /hours until/, /should trigger/, /likely to trigger/,
      /probability of firing/, /countdown/,
    ];
    const hits = forbidden.filter((re) => re.test(text));
    expect(hits).toEqual([]);
  });
});
