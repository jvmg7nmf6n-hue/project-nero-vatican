import { daysLive, formatDaysLive, SURVIVORS, SURVIVORS_FRAMING_LINE } from "@/lib/survivors";

describe("daysLive", () => {
  it("computes real elapsed whole days between go-live and now", () => {
    const now = new Date("2026-08-08T12:00:00Z");
    expect(daysLive("2026-07-31", now)).toBe(8);
    expect(daysLive("2026-08-08", now)).toBe(0);
  });

  it("never returns negative even if now is somehow before go-live", () => {
    const now = new Date("2026-07-01T00:00:00Z");
    expect(daysLive("2026-07-31", now)).toBe(0);
  });
});

describe("formatDaysLive", () => {
  it("uses real singular/plural/sub-day phrasing, never a fabricated precision", () => {
    expect(formatDaysLive(0)).toBe("less than a day live");
    expect(formatDaysLive(1)).toBe("1 day live");
    expect(formatDaysLive(8)).toBe("8 days live");
  });
});

describe("SURVIVORS real data", () => {
  it("lists exactly the 3 real verified survivors with zero live entries recorded", () => {
    expect(SURVIVORS.map((s) => s.name)).toEqual(["BREAKOUT_MOMENTUM", "TREND_PULLBACK", "COINTEGRATION_PAIRS"]);
  });

  it("every survivor cites a real docs/*.md source report", () => {
    for (const s of SURVIVORS) {
      expect(s.sourceReport).toMatch(/^docs\/.+\.md$/);
    }
  });
});

describe("SURVIVORS_FRAMING_LINE", () => {
  it("states both the real verification AND the real lack of a live track record in one honest line", () => {
    expect(SURVIVORS_FRAMING_LINE.toLowerCase()).toContain("backtest");
    expect(SURVIVORS_FRAMING_LINE.toLowerCase()).toMatch(/no.*trade|not taken|hasn't fired|haven't fired/);
  });
});
