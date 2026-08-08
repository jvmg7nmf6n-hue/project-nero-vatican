import { resolvePageContext, truncateAtLineBoundary, PAGE_CONTEXT_MAX_CHARS } from "@/lib/wiseMan/pageContext";
import * as data from "@/lib/data";

jest.mock("@/lib/data");

const mockFetchSiteSummary = jest.mocked(data.fetchSiteSummary);
const mockFetchStrategies = jest.mocked(data.fetchStrategies);
const mockFetchStats = jest.mocked(data.fetchStats);
const mockFetchGraveyard = jest.mocked(data.fetchGraveyard);
const mockFetchStrategyDescriptions = jest.mocked(data.fetchStrategyDescriptions);

beforeEach(() => {
  jest.resetAllMocks();
  mockFetchSiteSummary.mockResolvedValue(null);
  mockFetchStrategies.mockResolvedValue(null);
  mockFetchStats.mockResolvedValue(null);
  mockFetchGraveyard.mockResolvedValue(null);
  mockFetchStrategyDescriptions.mockResolvedValue(null);
});

describe("truncateAtLineBoundary (Sec 5 deterministic cap, never mid-JSON/mid-sentence)", () => {
  it("returns short text unchanged", () => {
    expect(truncateAtLineBoundary("short", 100)).toBe("short");
  });

  it("cuts at the last full line under the cap, never mid-line", () => {
    const text = "line one\nline two\nline three that is quite long and pushes past the cap";
    const result = truncateAtLineBoundary(text, 20);
    expect(result.startsWith("line one")).toBe(true);
    expect(result).not.toContain("line three that is q"); // never a partial line
    expect(result).toContain("[...page context truncated at 20 characters...]");
  });

  it("real page contexts stay under PAGE_CONTEXT_MAX_CHARS after resolution", async () => {
    mockFetchGraveyard.mockResolvedValue(
      Array.from({ length: 200 }, (_, i) => ({
        name: `HYP_${i}`,
        family: "Test Family",
        what_was_tested: "x".repeat(50),
        why_it_died: "y".repeat(50),
        source_doc: "docs/test.md",
      })),
    );
    const result = await resolvePageContext({ page: "graveyard" });
    expect(result.length).toBeLessThanOrEqual(PAGE_CONTEXT_MAX_CHARS + 60); // + truncation marker
  });
});

describe("resolvePageContext (Sec 5 server-side resolution, no client-supplied facts)", () => {
  it("home: pulls from fetchSiteSummary + fetchStrategies only, never trusts client input", async () => {
    mockFetchSiteSummary.mockResolvedValue({
      configs_tested: 42,
      strategies_survived: 5,
      strategy_families_verified: 3,
      tracking_since: "2026-01-01",
      last_curated: "2026-08-01",
    });
    const result = await resolvePageContext({ page: "home" });
    expect(result).toContain("42 configs tested");
    expect(result).toContain("5 survived");
  });

  it("strategy: resolves by id via the SAME fetchers the real page uses", async () => {
    mockFetchStrategies.mockResolvedValue({
      schema_version: 1,
      last_updated: "2026-08-01",
      strategies: [
        { name: "TEST_STRAT", version: "1.0.0", asset: "BTC", timeframe: "4h", verification_status: "TESTED", source_report: null },
      ],
    });
    mockFetchStats.mockResolvedValue({
      schema_version: 1,
      last_updated: "2026-08-01",
      strategies: [
        { strategy: "TEST_STRAT", strategy_version: "1.0.0", asset: "BTC", resolved_trades: 87, win_rate: 0.55, expectancy_r: 0.2, avg_return_pct: 1.1, signal_counts: {}, open_position: null },
      ],
    });
    mockFetchStrategyDescriptions.mockResolvedValue({
      TEST_STRAT: { mechanism: "Buys when RSI < 30." } as never,
    });
    const result = await resolvePageContext({ page: "strategy", id: "TEST_STRAT" });
    expect(result).toContain("TEST_STRAT");
    expect(result).toContain("87 resolved trades");
    expect(result).toContain("Buys when RSI < 30.");
  });

  it("strategy: an unknown id resolves honestly to 'no data found', never fabricated", async () => {
    mockFetchStrategies.mockResolvedValue({ schema_version: 1, last_updated: "x", strategies: [] });
    mockFetchStats.mockResolvedValue({ schema_version: 1, last_updated: "x", strategies: [] });
    const result = await resolvePageContext({ page: "strategy", id: "DOES_NOT_EXIST" });
    expect(result).toContain("No data found for this strategy id.");
  });

  it("methodology and pricing are static pages with an honest 'no live data' context", async () => {
    const methodology = await resolvePageContext({ page: "methodology" });
    const pricing = await resolvePageContext({ page: "pricing" });
    expect(methodology).toContain("static content");
    expect(pricing).toContain("static content");
  });

  it("gracefully handles missing data (nulls) without throwing", async () => {
    await expect(resolvePageContext({ page: "home" })).resolves.toEqual(expect.any(String));
    await expect(resolvePageContext({ page: "graveyard" })).resolves.toEqual(expect.any(String));
  });
});
