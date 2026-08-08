import { GOLDEN_QUESTIONS } from "@/lib/wiseMan/goldenQuestions";

describe("wiseMan GOLDEN_QUESTIONS fixture (CC-1 Wise Man directive Sec 3)", () => {
  it("has between 15 and 20 questions", () => {
    expect(GOLDEN_QUESTIONS.length).toBeGreaterThanOrEqual(15);
    expect(GOLDEN_QUESTIONS.length).toBeLessThanOrEqual(20);
  });

  it("has unique ids covering 1..N with no gaps", () => {
    const ids = GOLDEN_QUESTIONS.map((q) => q.id).sort((a, b) => a - b);
    expect(ids).toEqual(Array.from({ length: GOLDEN_QUESTIONS.length }, (_, i) => i + 1));
  });

  it("has at least 5 questions that must be refused", () => {
    const refuseCount = GOLDEN_QUESTIONS.filter((q) => q.expect === "refuse").length;
    expect(refuseCount).toBeGreaterThanOrEqual(5);
  });

  it("has at least 5 in-scope questions using buy/sell/entry/invest descriptively that must NOT be blocked", () => {
    const descriptive = GOLDEN_QUESTIONS.filter((q) => q.usesAdviceWordDescriptively);
    expect(descriptive.length).toBeGreaterThanOrEqual(5);
    for (const q of descriptive) {
      expect(q.expect).toBe("answer");
    }
  });

  it("has at least 3 Roman Urdu questions expecting a Roman Urdu response (Sec 11.6)", () => {
    const romanUrduAnswers = GOLDEN_QUESTIONS.filter((q) => q.expectRomanUrduResponse);
    expect(romanUrduAnswers.length).toBeGreaterThanOrEqual(3);
    for (const q of romanUrduAnswers) {
      expect(q.lang).toBe("ur");
      expect(q.expect).toBe("answer");
    }
  });

  it("tests the must-block set in Roman Urdu too (Sec 4.1.4)", () => {
    const romanUrduRefusals = GOLDEN_QUESTIONS.filter((q) => q.lang === "ur" && q.expect === "refuse");
    expect(romanUrduRefusals.length).toBeGreaterThanOrEqual(1);
  });

  it("every question has a non-empty question and expectShape", () => {
    for (const q of GOLDEN_QUESTIONS) {
      expect(q.question.length).toBeGreaterThan(0);
      expect(q.expectShape.length).toBeGreaterThan(0);
    }
  });
});
