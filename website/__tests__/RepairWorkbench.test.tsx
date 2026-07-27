import { render, screen } from "@testing-library/react";
import RepairWorkbench from "@/components/RepairWorkbench";
import type { RepairCandidate } from "@/lib/types";

function candidate(overrides: Partial<RepairCandidate> = {}): RepairCandidate {
  return {
    parent_strategy: "BOS_CONTINUATION",
    failure_pattern: "regime-filter-only",
    diagnosis: "The capped ATR stop dominates over the structural stop.",
    proposed_fix: "Reject cap-dominated setups instead of capping them.",
    hypothesis_name: "BOS_STRUCTURAL_STOP_ONLY",
    status: "candidate",
    ...overrides,
  };
}

describe("RepairWorkbench", () => {
  it("always renders the hardcoded RMR lineage worked example", () => {
    render(<RepairWorkbench candidates={[]} />);
    const steps = screen.getAllByTestId("rmr-lineage-step");
    expect(steps.length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText(/RANGE_MEAN_REVERSION v1\.0\.0/)).toBeInTheDocument();
    expect(screen.getByText(/R1 — REGIME_TRANSITION/)).toBeInTheDocument();
    expect(screen.getByText(/R2 — RANGE_MATURITY gate/)).toBeInTheDocument();
    expect(screen.getByText(/R3 — REGIME_ALLOCATOR/)).toBeInTheDocument();
  });

  it("shows an empty-state message when there are no repair candidates", () => {
    render(<RepairWorkbench candidates={[]} />);
    expect(screen.getByTestId("repair-candidates-empty")).toBeInTheDocument();
  });

  it("renders one card per candidate with parent, diagnosis, fix, and status", () => {
    render(<RepairWorkbench candidates={[candidate()]} />);
    const card = screen.getByTestId("repair-candidate-card");
    expect(card).toHaveAttribute("data-status", "candidate");
    expect(screen.getByText("BOS_STRUCTURAL_STOP_ONLY")).toBeInTheDocument();
    expect(screen.getByText(/Parent: BOS_CONTINUATION/)).toBeInTheDocument();
    expect(screen.getByText(/capped ATR stop dominates/)).toBeInTheDocument();
    expect(screen.getByText(/Reject cap-dominated setups/)).toBeInTheDocument();
    expect(screen.getByText("Candidate")).toBeInTheDocument();
  });

  it("renders multiple candidate cards independently", () => {
    render(
      <RepairWorkbench
        candidates={[
          candidate({ hypothesis_name: "BOS_STRUCTURAL_STOP_ONLY" }),
          candidate({ hypothesis_name: "LEADLAG_TIME_INVARIANT", parent_strategy: "LEADLAG_FOLLOW", status: "watchlist" }),
        ]}
      />
    );
    expect(screen.getAllByTestId("repair-candidate-card")).toHaveLength(2);
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
  });
});
