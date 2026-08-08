import { render, screen } from "@testing-library/react";
import FactoryLoopScoreboard from "@/components/FactoryLoopScoreboard";
import type { FactoryLoopScoreboard as ScoreboardData } from "@/lib/types";

const NOW = new Date("2026-08-08T07:00:00Z");

const SCOREBOARD: ScoreboardData = {
  schema_version: 1,
  last_updated: "2026-08-08T06:55:00+00:00",
  live_scheduler: {
    tracked_count: 37,
    active_count: 2,
    active: [{ strategy: "PEAD", strategy_version: "v1", asset: "AMZN", entry_price: 233.4, entered_at: "2026-08-01T00:08:17+00:00" }],
  },
  forward_trial: {
    tracked_count: 20,
    active_count: 4,
    active: [{ trial_id: "t1", hypothesis_name: "INTRADAY_TSMOM_BTC_4H", asset: "BTC", entry_price: 65046.0, entered_at: "2026-08-08T06:44:55+00:00" }],
    by_origin: { adam: 6, eve: 14 },
  },
  repair_lab: {
    manual_candidates: { count: 3, launchable_count: 0, note: "hand-curated" },
    automated_chains: {
      count: 1,
      open_chains: 1,
      resolved_chains: 0,
      healthy_count: 0,
      chains: [
        {
          repair_chain_id: "RC-CHANNEL_LOW_PULLBACK_UPTREND_SOL_4H",
          original_hypothesis_name: "CHANNEL_LOW_PULLBACK_UPTREND_SOL_4H",
          chain_status: "OPEN",
          attempts: [{ attempt_id: "A1", status: "PENDING_FORWARD_DATA", modification_type: "exit_structure" }],
        },
      ],
      note: "real chains",
    },
  },
  graveyard: { count: 25 },
  recent_activity: [
    { source: "eve", at: "2026-08-07T23:37:23+00:00", summary: "session_3_of_8 -- real spend $0.4538" },
    { source: "adam", at: "2026-08-06T04:37:28+00:00", summary: "3 hypotheses generated, $1.5708 spent" },
  ],
};

describe("FactoryLoopScoreboard", () => {
  it("shows an honest unavailable message, never a fabricated zero, when data is null", () => {
    render(<FactoryLoopScoreboard scoreboard={null} now={NOW} />);
    expect(screen.getByTestId("factory-loop-scoreboard-unavailable")).toBeInTheDocument();
  });

  it("shows the real combined active-vs-live total", () => {
    render(<FactoryLoopScoreboard scoreboard={SCOREBOARD} now={NOW} />);
    // 2 (live-scheduler) + 4 (forward trial) = 6 active, of 57 tracked (37+20).
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText(/of 57 tracked/)).toBeInTheDocument();
  });

  it("shows Forward Trial active vs tracked separately from live-scheduler", () => {
    render(<FactoryLoopScoreboard scoreboard={SCOREBOARD} now={NOW} />);
    expect(screen.getByText("4 active / 20 tracked")).toBeInTheDocument();
    expect(screen.getByText("2 active / 37 tracked")).toBeInTheDocument();
  });

  it("reports manual repair candidates and automated chains as two separate tiles, never merged", () => {
    render(<FactoryLoopScoreboard scoreboard={SCOREBOARD} now={NOW} />);
    const manual = screen.getByTestId("repair-lab-manual");
    const automated = screen.getByTestId("repair-lab-automated");
    expect(manual.textContent).toContain("3 on file, 0 launchable right now");
    expect(automated.textContent).toContain("1 launched, 0 healthy");
    expect(automated.textContent).toContain("CHANNEL_LOW_PULLBACK_UPTREND_SOL_4H");
  });

  it("renders the real recent activity feed, most recent first, with real summaries", () => {
    render(<FactoryLoopScoreboard scoreboard={SCOREBOARD} now={NOW} />);
    const feed = screen.getByTestId("factory-loop-recent-activity");
    expect(feed.textContent).toContain("session_3_of_8");
    expect(feed.textContent).toContain("3 hypotheses generated");
  });

  it("never fabricates a Forward Trial active_count when the export reports it as unavailable (null)", () => {
    const withError: ScoreboardData = {
      ...SCOREBOARD,
      forward_trial: { ...SCOREBOARD.forward_trial, active_count: null, error: "sqlite3.OperationalError: db locked" },
    };
    render(<FactoryLoopScoreboard scoreboard={withError} now={NOW} />);
    expect(screen.getByText("— active / 20 tracked")).toBeInTheDocument();
  });
});
