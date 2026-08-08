import {
  MUST_BLOCK,
  MUST_NOT_BLOCK,
  INJECTION_CASES,
  MULTI_TURN_EROSION,
} from "@/lib/wiseMan/guardrailCorpus";

describe("wiseMan guardrail corpora (CC-1 Wise Man directive Sec 4.1.3/4.1.4/4.1.5/11.3)", () => {
  it("MUST_BLOCK has at least 25 cases", () => {
    expect(MUST_BLOCK.length).toBeGreaterThanOrEqual(25);
  });

  it("MUST_NOT_BLOCK has at least 25 cases", () => {
    expect(MUST_NOT_BLOCK.length).toBeGreaterThanOrEqual(25);
  });

  it("MUST_BLOCK covers direct, hypothetical, roleplay, third_person, and chart_image_caption framings", () => {
    const framings = new Set(MUST_BLOCK.map((c) => c.framing));
    for (const required of ["direct", "hypothetical", "roleplay", "third_person", "chart_image_caption"]) {
      expect(framings.has(required as never)).toBe(true);
    }
  });

  it("MUST_BLOCK includes the must-block set tested in Roman Urdu (Sec 4.1.4)", () => {
    const urduBlocks = MUST_BLOCK.filter((c) => c.lang === "ur");
    expect(urduBlocks.length).toBeGreaterThanOrEqual(1);
  });

  it("MUST_NOT_BLOCK cases cite a real site-copy source where framed as site_copy", () => {
    for (const c of MUST_NOT_BLOCK.filter((c) => c.framing === "site_copy")) {
      expect(c.sourceNote).toBeTruthy();
    }
  });

  it("has no duplicate ids across MUST_BLOCK and MUST_NOT_BLOCK", () => {
    const ids = [...MUST_BLOCK, ...MUST_NOT_BLOCK].map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("INJECTION_CASES all pair with an attachment and describe untrusted content (Sec 4.1.5)", () => {
    expect(INJECTION_CASES.length).toBeGreaterThanOrEqual(1);
    for (const c of INJECTION_CASES) {
      expect(c.pairWithPdf || c.pairWithImage).toBe(true);
      expect(c.sourceNote).toBeTruthy();
    }
  });

  it("MULTI_TURN_EROSION has at least 5 sequences, each with >= 2 turns (Sec 11.3)", () => {
    expect(MULTI_TURN_EROSION.length).toBeGreaterThanOrEqual(5);
    for (const seq of MULTI_TURN_EROSION) {
      expect(seq.turns.length).toBeGreaterThanOrEqual(2);
    }
  });

  it("MULTI_TURN_EROSION includes at least one Roman Urdu sequence", () => {
    expect(MULTI_TURN_EROSION.some((seq) => seq.lang === "ur")).toBe(true);
  });
});
