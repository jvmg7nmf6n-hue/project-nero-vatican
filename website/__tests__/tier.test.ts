import fs from "fs";
import path from "path";
import { classifyTier, isRecognizedVerificationStatus } from "@/lib/tier";

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

// CC-1 overnight directive, Part 3: closed-vocabulary enforcement, in the
// spirit of the graveyard's own enforced taxonomy. classifyTier's silent
// "experimental" default (tested above) stays as a safe RUNTIME fallback --
// this suite is the real enforcement, catching a typo'd or genuinely new
// verification_status wording as a loud CI failure instead of a silent
// misclassification a reader would never notice.
describe("isRecognizedVerificationStatus", () => {
  it("recognizes every real prefix this project actually uses", () => {
    expect(isRecognizedVerificationStatus("experimental — snapshot-based")).toBe(true);
    expect(isRecognizedVerificationStatus("forward-test-only, no historical backtest")).toBe(true);
    expect(isRecognizedVerificationStatus("promising-watchlist — forward-testing")).toBe(true);
    expect(isRecognizedVerificationStatus("watchlist — CI clears zero")).toBe(true);
    expect(isRecognizedVerificationStatus("triple-verified")).toBe(true);
    expect(isRecognizedVerificationStatus("verified — sample-limited")).toBe(true);
  });

  it("catches a typo'd verification_status value that classifyTier would otherwise silently absorb into experimental", () => {
    // Proves the detector actually detects: a plausible-looking typo of a
    // REAL status ("verifed" missing an 'i') must be flagged unrecognized,
    // even though classifyTier itself still safely (silently) returns
    // "experimental" for it at runtime.
    expect(isRecognizedVerificationStatus("verifed — sample-limited")).toBe(false);
    expect(classifyTier("verifed — sample-limited")).toBe("experimental");
  });

  it("catches a genuinely new, never-seen status wording", () => {
    expect(isRecognizedVerificationStatus("provisionally-accepted")).toBe(false);
  });
});

describe("real committed strategies.json closed-vocabulary check", () => {
  it("every real verification_status on the live roster is a recognized prefix -- fails loudly in CI if a future roster entry introduces unrecognized wording", () => {
    const realPath = path.join(process.cwd(), "..", "docs", "site_data", "strategies.json");
    const real = JSON.parse(fs.readFileSync(realPath, "utf-8"));
    const unrecognized = real.strategies
      .map((s: { verification_status: string }) => s.verification_status)
      .filter((status: string) => !isRecognizedVerificationStatus(status));
    expect(unrecognized).toEqual([]);
  });
});
