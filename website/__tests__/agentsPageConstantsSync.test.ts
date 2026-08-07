import fs from "fs";
import path from "path";

// CC-1 follow-up directive, "make every Agents-page number live, not
// hardcoded": the process-count/dollar-cap numbers in HowItWorksSection
// (app/agents/page.tsx) describe Python source CONSTANTS -- 10
// scanner calls, 3 web-search requests, 5 searches/request, 40 turns,
// $1.50/session, $20/month, a 20-trade minimum sample -- not committed
// JSON data. There is no docs/site_data export for a Python constant, and
// building one would be a new export pipeline for numbers that essentially
// never change at runtime, which the directive's own Item 2a rules out
// ("no new backend"). The honest fix instead of a fake live fetch: this
// test reads the REAL Python source directly and fails if page.tsx's own
// prose drifts from it -- the same role PRE_REGISTERED_SESSION_COUNT's own
// sync test (agentsPage.test.ts) already plays for a different constant.
const REPO_ROOT = path.join(process.cwd(), "..");
// Collapsed to single spaces -- JSX text wraps across source lines exactly
// like HTML does, so a literal multi-line substring would fail this check
// for a reason that has nothing to do with whether the real number matches.
const PAGE_SOURCE = fs
  .readFileSync(path.join(process.cwd(), "app", "agents", "page.tsx"), "utf-8")
  .replace(/\s+/g, " ");

function readReal(relPath: string): string {
  return fs.readFileSync(path.join(REPO_ROOT, relPath), "utf-8");
}

describe("Agents page prose stays in sync with the real Python constants it describes", () => {
  it("Adam's scanner-channel call cap (hypothesis_gen.DEFAULT_MAX_CALLS_PER_RUN)", () => {
    const real = readReal("nero_core/research_agent/hypothesis_gen.py");
    const match = real.match(/^DEFAULT_MAX_CALLS_PER_RUN = (\d+)$/m);
    expect(match).not.toBeNull();
    expect(PAGE_SOURCE).toContain(`up to ${match![1]} calls per run`);
  });

  it("Adam's web-search channel caps (DEFAULT_WEB_MAX_CALLS_PER_RUN, WEB_SEARCH_TOOL.max_uses)", () => {
    const real = readReal("nero_core/research_agent/hypothesis_gen.py");
    const callsMatch = real.match(/^DEFAULT_WEB_MAX_CALLS_PER_RUN = (\d+)$/m);
    const usesMatch = real.match(/"max_uses":\s*(\d+)/);
    expect(callsMatch).not.toBeNull();
    expect(usesMatch).not.toBeNull();
    expect(PAGE_SOURCE).toContain(`up to ${callsMatch![1]} times per run`);
    expect(PAGE_SOURCE).toContain(`up to ${usesMatch![1]} searches per call`);
  });

  it("Eve's turn cap (eve.session.MAX_TURNS)", () => {
    const real = readReal("nero_core/eve/session.py");
    const match = real.match(/^MAX_TURNS = (\d+)$/m);
    expect(match).not.toBeNull();
    expect(PAGE_SOURCE).toContain(`up to ${match![1]} turns`);
  });

  it("Eve's hard dollar caps (budget_ledger.DEFAULT_SESSION_BUDGET_USD, MONTH_CEILING_USD)", () => {
    const real = readReal("nero_core/eve/budget_ledger.py");
    const sessionMatch = real.match(/^DEFAULT_SESSION_BUDGET_USD = ([\d.]+)$/m);
    const monthMatch = real.match(/^MONTH_CEILING_USD = ([\d.]+)$/m);
    expect(sessionMatch).not.toBeNull();
    expect(monthMatch).not.toBeNull();
    const sessionUsd = Number(sessionMatch![1]).toFixed(2);
    const monthUsd = Number(monthMatch![1]).toFixed(0);
    expect(PAGE_SOURCE).toContain(`$${sessionUsd} per-session cap`);
    expect(PAGE_SOURCE).toContain(`$${monthUsd}/month ceiling`);
  });

  it("the shared harness's minimum sample size (backtest_statistics.MIN_SAMPLE_SIZE)", () => {
    const real = readReal("tools/backtest_statistics.py");
    const match = real.match(/^MIN_SAMPLE_SIZE = (\d+)$/m);
    expect(match).not.toBeNull();
    expect(PAGE_SOURCE).toContain(`at least ${match![1]} trades`);
  });
});
