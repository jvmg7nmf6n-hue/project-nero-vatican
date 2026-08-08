// GOLDEN_QUESTIONS acceptance run + real per-query cost benchmark (CC-1
// Wise Man directive v3, Sec 10 GATE C evidence). Real API calls against
// the live pipeline's own logic (inbound guardrail -> generation ->
// outbound guardrail) -- not mocked. Not part of `npm test`. Run manually:
//
//   cd website && node --env-file=../.env scripts/wiseManGoldenQuestionsEval.ts

import { checkGuardrail, ANTHROPIC_API_URL, ANTHROPIC_VERSION, GUARDRAIL_MODEL } from "../lib/wiseMan/guardrail.ts";
import { GOLDEN_QUESTIONS } from "../lib/wiseMan/goldenQuestions.ts";
import { buildWiseManSystemBlocks } from "../lib/wiseMan/systemPrompt.ts";

// lib/pageContext.ts is not imported here on purpose: it transitively pulls
// in lib/data.ts, whose own internal relative imports aren't resolvable by
// plain Node's ESM loader without extensions (the same reason
// guardrail.ts's ANTHROPIC_API_URL/VERSION were reinlined rather than
// imported -- see that file's comment). Adding `.ts` extensions inside
// lib/data.ts itself, a file used throughout the real Next.js app, isn't
// worth doing just for this script. "methodology" page context is static
// prose with no data fetch anyway (GATE A finding 1.6), so it's inlined
// directly instead.
const STATIC_METHODOLOGY_CONTEXT = "methodology page context: static content, no live data to summarize.";

const apiKey = process.env.ANTHROPIC_API_KEY;
if (!apiKey) {
  console.error("ANTHROPIC_API_KEY not set (pass --env-file=../.env)");
  process.exit(1);
}

interface Usage {
  input_tokens?: number;
  output_tokens?: number;
}

// Haiku 4.5 pricing per GATE A finding 1.8 (verified against
// platform.claude.com/docs 2026-08-08): $1.00/MTok input, $5.00/MTok output.
function costUsd(usages: Usage[]): number {
  let cents = 0;
  for (const u of usages) {
    cents += ((u.input_tokens ?? 0) * 1.0) / 1_000_000;
    cents += ((u.output_tokens ?? 0) * 5.0) / 1_000_000;
  }
  return cents;
}

async function runGeneration(message: string, pageContextText: string): Promise<{ text: string; usage: Usage }> {
  const systemBlocks = buildWiseManSystemBlocks(pageContextText);
  const response = await fetch(ANTHROPIC_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": apiKey!, "anthropic-version": ANTHROPIC_VERSION },
    body: JSON.stringify({
      model: GUARDRAIL_MODEL,
      max_tokens: 1024,
      system: systemBlocks,
      messages: [{ role: "user", content: [{ type: "text", text: message }] }],
    }),
  });
  const payload = await response.json();
  const text = (payload.content ?? []).filter((b: { type?: string }) => b?.type === "text").map((b: { text?: string }) => b.text ?? "").join("");
  return { text, usage: payload.usage ?? {} };
}

interface QuestionResult {
  id: number;
  expect: string;
  actual: "answer" | "refuse";
  correct: boolean;
  costUsd: number;
  replyText: string;
}

async function runQuestion(q: (typeof GOLDEN_QUESTIONS)[number]): Promise<QuestionResult> {
  const pageContextText = STATIC_METHODOLOGY_CONTEXT;
  const usages: Usage[] = [];

  const inbound = await checkGuardrail({ blocks: [{ type: "text", text: q.question }], direction: "inbound", apiKey: apiKey! });
  if (inbound.blocked) {
    return { id: q.id, expect: q.expect, actual: "refuse", correct: q.expect === "refuse", costUsd: costUsd(usages), replyText: "(blocked inbound)" };
  }

  const generation = await runGeneration(q.question, pageContextText);
  usages.push(generation.usage);

  const outbound = await checkGuardrail({ blocks: [{ type: "text", text: generation.text }], direction: "outbound", apiKey: apiKey! });
  if (outbound.blocked) {
    return { id: q.id, expect: q.expect, actual: "refuse", correct: q.expect === "refuse", costUsd: costUsd(usages), replyText: "(blocked outbound)" };
  }

  return { id: q.id, expect: q.expect, actual: "answer", correct: q.expect === "answer", costUsd: costUsd(usages), replyText: generation.text };
}

async function main() {
  const results: QuestionResult[] = [];
  for (const q of GOLDEN_QUESTIONS) {
    const result = await runQuestion(q);
    results.push(result);
    console.log(`${result.correct ? "PASS" : "FAIL"} #${result.id} (${q.lang}, expect=${result.expect}, actual=${result.actual})`);
  }

  const passCount = results.filter((r) => r.correct).length;
  console.log(`\n=== GOLDEN_QUESTIONS acceptance: ${passCount}/${results.length} passed ===`);
  for (const r of results.filter((r) => !r.correct)) {
    console.log(`  FAIL #${r.id}: expected ${r.expect}, got ${r.actual}`);
  }

  console.log(`\n=== Roman Urdu must-answer replies (spot-check for fluency, Sec 11.6) ===`);
  const urduAnswerIds = GOLDEN_QUESTIONS.filter((q) => q.expectRomanUrduResponse).map((q) => q.id);
  for (const r of results.filter((res) => urduAnswerIds.includes(res.id))) {
    console.log(`--- #${r.id} ---\n${r.replyText}\n`);
  }

  const costs = results.map((r) => r.costUsd).sort((a, b) => a - b);
  const p50 = costs[Math.floor(costs.length * 0.5)];
  const p90 = costs[Math.floor(costs.length * 0.9)];
  console.log(`\n=== Real per-query cost (Haiku 4.5 rates, from usage field) ===`);
  console.log(`p50: $${p50.toFixed(6)}`);
  console.log(`p90: $${p90.toFixed(6)}`);
  console.log(`mean: $${(costs.reduce((a, b) => a + b, 0) / costs.length).toFixed(6)}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
