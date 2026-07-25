import { classifyTier } from "@/lib/tier";

describe("classifyTier", () => {
  it.each([
    "triple-verified",
    "verified — sample-limited",
    "verified — weakest, live-proving",
  ])('classifies "%s" as verified', (status) => {
    expect(classifyTier(status)).toBe("verified");
  });

  it.each([
    "watchlist — forward-testing, not verified (band-timing beat random both halves; N below 20-trade bar)",
    "promising-watchlist — forward-testing, not verified",
    "watchlist — CI clears zero both halves, adequate sample, breakout-timing edge confirmed vs random baseline; grid-shift structurally unavailable at 1week (settlement gaps) — this is the ceiling, not a data shortfall",
  ])('classifies "%s" as watchlist', (status) => {
    expect(classifyTier(status)).toBe("watchlist");
  });

  it.each([
    "experimental — snapshot-based, forward-testing only, no backtest exists",
    "forward-test-only, no historical backtest",
  ])('classifies "%s" as experimental', (status) => {
    expect(classifyTier(status)).toBe("experimental");
  });

  it("defaults an unrecognized status to experimental rather than assuming verified", () => {
    expect(classifyTier("some new status nobody has seen before")).toBe("experimental");
  });

  it("is case-insensitive", () => {
    expect(classifyTier("VERIFIED — sample-limited")).toBe("verified");
  });
});
