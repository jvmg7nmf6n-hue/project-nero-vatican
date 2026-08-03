import { render, screen } from "@testing-library/react";
import BacktestEvaluationPanel from "@/components/BacktestEvaluationPanel";
import type { BacktestEvaluation } from "@/lib/types";

function makeEvaluation(overrides: Partial<BacktestEvaluation> = {}): BacktestEvaluation {
  return {
    verdict_is: null,
    verdict_oos: null,
    is_trades: null,
    oos_trades: null,
    is_expectancy_r: null,
    oos_expectancy_r: null,
    evaluated_at: null,
    data_source: null,
    method: null,
    untestable_reason: null,
    note: "Not yet evaluated with this structured format.",
    ...overrides,
  };
}

describe("BacktestEvaluationPanel", () => {
  it("shows the not-yet-evaluated note and nothing else when there is no evidence at all", () => {
    render(<BacktestEvaluationPanel evaluation={makeEvaluation()} />);

    expect(screen.getByTestId("backtest-evaluation-not-yet")).toHaveTextContent(
      "Not yet evaluated with this structured format."
    );
    expect(screen.queryByTestId("backtest-evaluation-stats")).not.toBeInTheDocument();
    expect(screen.queryByTestId("backtest-evaluation-untestable")).not.toBeInTheDocument();
  });

  it("renders verdict_is/verdict_oos, trade counts, and expectancy for a real evaluation", () => {
    render(
      <BacktestEvaluationPanel
        evaluation={makeEvaluation({
          verdict_is: "DIED",
          verdict_oos: "INSUFFICIENT_SAMPLE",
          is_trades: 10,
          oos_trades: 5,
          is_expectancy_r: -0.28,
          oos_expectancy_r: 0.744,
          note: null,
        })}
      />
    );

    expect(screen.getByTestId("verdict-is")).toHaveTextContent("DIED");
    expect(screen.getByTestId("verdict-oos")).toHaveTextContent("INSUFFICIENT_SAMPLE");
    expect(screen.getByTestId("trade-counts")).toHaveTextContent("10 / 5");
    expect(screen.getByTestId("expectancy")).toHaveTextContent("-0.280 / 0.744");
  });

  it("renders the untestable-by-standard-harness note alongside its own real evidence, never blank", () => {
    render(
      <BacktestEvaluationPanel
        evaluation={makeEvaluation({
          is_trades: 61,
          oos_trades: 22,
          is_expectancy_r: 0.047,
          oos_expectancy_r: 0.003,
          untestable_reason: "Not compatible with the single-asset rule_dsl/auto_tester harness.",
          note: null,
        })}
      />
    );

    expect(screen.getByTestId("backtest-evaluation-untestable")).toHaveTextContent(
      "Not compatible with the single-asset rule_dsl/auto_tester harness."
    );
    // "Untestable" must never mean "no evidence shown" -- the real trade
    // counts/expectancy from the strategy's own dedicated backtest engine
    // still render alongside the untestable note.
    expect(screen.getByTestId("backtest-evaluation-stats")).toBeInTheDocument();
    expect(screen.getByTestId("trade-counts")).toHaveTextContent("61 / 22");
  });

  it("shows evaluated_at, data_source, and method in the meta line when present", () => {
    render(
      <BacktestEvaluationPanel
        evaluation={makeEvaluation({
          verdict_is: "DIED",
          evaluated_at: "2026-08-02",
          data_source: "docs/research_data/evaluation_candles/BTC_24h.json",
          method: "split_chronological + bootstrap_mean_r_ci + classify_verdict",
          note: null,
        })}
      />
    );

    const meta = screen.getByTestId("backtest-evaluation-meta");
    expect(meta).toHaveTextContent("2026-08-02");
    expect(meta).toHaveTextContent("BTC_24h.json");
    expect(meta).toHaveTextContent("classify_verdict");
  });
});
