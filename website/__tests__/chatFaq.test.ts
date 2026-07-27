import { buildFaqEntries, FAQ_QUESTIONS } from "@/lib/chatFaq";
import type { StrategyDescription, StrategyRosterEntry, StrategyStats } from "@/lib/types";

const ENTRY: Pick<StrategyRosterEntry, "name" | "asset" | "timeframe"> = {
  name: "BREAKOUT_MOMENTUM",
  asset: "GOLD",
  timeframe: "1week",
};

const DESCRIPTION: StrategyDescription = {
  mechanism: "Enters long on a breakout above the recent high, above the 200-period average.",
  verification_note: "Verified on both backtest halves.",
};

function stats(overrides: Partial<StrategyStats> = {}): Pick<StrategyStats, "win_rate" | "resolved_trades"> {
  return { win_rate: null, resolved_trades: 0, ...overrides };
}

describe("buildFaqEntries", () => {
  it("returns exactly the 7 fixed questions, in order", () => {
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, stats());
    expect(entries).toHaveLength(7);
    expect(entries.map((e) => e.question)).toEqual(FAQ_QUESTIONS);
  });

  it("uses the strategy_descriptions.json mechanism text for Q1 when available", () => {
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, stats());
    expect(entries[0].answer).toBe(DESCRIPTION.mechanism);
  });

  it("falls back to a generic, non-fabricated Q1 answer when no description exists", () => {
    const entries = buildFaqEntries(ENTRY, null, stats());
    expect(entries[0].answer).toContain("BREAKOUT_MOMENTUM");
    expect(entries[0].answer).toContain("hasn't been written up");
  });

  it("keeps every answer under 100 words", () => {
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, stats({ win_rate: 0.6, resolved_trades: 42 }));
    for (const entry of entries) {
      const wordCount = entry.answer.trim().split(/\s+/).length;
      expect(wordCount).toBeLessThanOrEqual(100);
    }
  });

  it("truncates an overly long mechanism description to 100 words with a trailing ellipsis", () => {
    const longMechanism = Array.from({ length: 150 }, (_, i) => `word${i}`).join(" ");
    const entries = buildFaqEntries(ENTRY, { ...DESCRIPTION, mechanism: longMechanism }, stats());
    expect(entries[0].answer.split(/\s+/).length).toBeLessThanOrEqual(101); // 100 words + "..."
    expect(entries[0].answer.endsWith("...")).toBe(true);
  });

  it("says 'not enough data yet' for win rate when null, never a fabricated percentage", () => {
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, stats({ win_rate: null }));
    const lossesAnswer = entries.find((e) => e.question === "Why does Vatican show losses too?")!;
    expect(lossesAnswer.answer).toContain("not enough data yet");
  });

  it("reports the real win rate percentage when available", () => {
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, stats({ win_rate: 0.573, resolved_trades: 20 }));
    const guaranteeAnswer = entries.find((e) => e.question === "Is profit guaranteed?")!;
    expect(guaranteeAnswer.answer).toContain("57%");
    expect(guaranteeAnswer.answer).toContain("guaranteed");
  });

  it("always tells the user to consult a licensed financial advisor for investment-amount questions", () => {
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, stats());
    const investAnswer = entries.find((e) => e.question === "How much should I invest?")!;
    expect(investAnswer.answer.toLowerCase()).toContain("licensed financial advisor");
  });

  it("reports the real resolved trade count for the frequency question", () => {
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, stats({ resolved_trades: 7 }));
    const frequencyAnswer = entries.find((e) => e.question === "How often does a signal come?")!;
    expect(frequencyAnswer.answer).toContain("7 trades");
  });

  it("handles a null statsRow gracefully (never throws, defaults to zero trades)", () => {
    expect(() => buildFaqEntries(ENTRY, DESCRIPTION, null)).not.toThrow();
    const entries = buildFaqEntries(ENTRY, DESCRIPTION, null);
    const frequencyAnswer = entries.find((e) => e.question === "How often does a signal come?")!;
    expect(frequencyAnswer.answer).toContain("0 trades");
  });
});
