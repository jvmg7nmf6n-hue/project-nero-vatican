// Real guardrail accuracy evaluation (CC-1 Wise Man directive v3, Sec 4.1.3 /
// 4.1.4 / 4.1.5 / 11.3 / 11.5). Runs REAL API calls against claude-haiku-4-5
// -- not mocked, not part of `npm test` (this would make CI slow, costly,
// and dependent on network + a real key). Run manually or in the Sec 10
// GATE C evidence-gathering pass:
//
//   node --env-file=../.env scripts/wiseManGuardrailEval.ts
//
// (from website/; --env-file loads the repo-root .env's ANTHROPIC_API_KEY --
// same shared key Adam/Eve/the website all read, per GATE A finding 1.3).
// Node 24's native TypeScript support runs this file directly, no build step.

import { checkGuardrail, type WiseManContentBlock } from "../lib/wiseMan/guardrail.ts";
import {
  MUST_BLOCK,
  MUST_NOT_BLOCK,
  INJECTION_CASES,
  MULTI_TURN_EROSION,
  type CorpusCase,
} from "../lib/wiseMan/guardrailCorpus.ts";
import { deflateSync } from "node:zlib";

const apiKey = process.env.ANTHROPIC_API_KEY;
if (!apiKey) {
  console.error("ANTHROPIC_API_KEY not set (pass --env-file=../.env)");
  process.exit(1);
}

// --- synthetic attachments (no image/pdf library dependency, same approach
// as scripts/probes/wise_man_haiku_attachment_probe.py) ---------------------

function crc32(buf: Buffer): number {
  let c: number;
  const table: number[] = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(tag: string, data: Buffer): Buffer {
  const tagBuf = Buffer.from(tag, "ascii");
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([tagBuf, data])), 0);
  return Buffer.concat([len, tagBuf, data, crcBuf]);
}

function syntheticChartPng(width = 240, height = 160): string {
  const barHeights = [40, 70, 55, 90, 65, 100, 80];
  const barW = Math.floor(width / barHeights.length);
  const rows: Buffer[] = [];
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3);
    row[0] = 0;
    for (let x = 0; x < width; x++) {
      const barI = Math.min(Math.floor(x / barW), barHeights.length - 1);
      const barTop = height - barHeights[barI];
      const isBar = y >= barTop && x % barW !== 0;
      const [r, g, b] = isBar ? [30, 90, 160] : [245, 245, 240];
      row[1 + x * 3] = r;
      row[1 + x * 3 + 1] = g;
      row[1 + x * 3 + 2] = b;
    }
    rows.push(row);
  }
  const raw = Buffer.concat(rows);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type: RGB
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const png = Buffer.concat([
    sig,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
  return png.toString("base64");
}

function syntheticPdf(lines: string[]): string {
  const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
  const ops = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL", ...lines.map((l) => `(${esc(l)}) Tj T*`), "ET"];
  const contentStream = Buffer.from(ops.join("\n"), "latin1");
  const objects: Buffer[] = [
    Buffer.from("<< /Type /Catalog /Pages 2 0 R >>", "latin1"),
    Buffer.from("<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "latin1"),
    Buffer.from(
      "<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /MediaBox [0 0 612 792] /Contents 4 0 R >>",
      "latin1",
    ),
    Buffer.concat([
      Buffer.from(`<< /Length ${contentStream.length} >>\nstream\n`, "latin1"),
      contentStream,
      Buffer.from("\nendstream", "latin1"),
    ]),
    Buffer.from("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", "latin1"),
  ];
  let buf = Buffer.from("%PDF-1.4\n", "latin1");
  const offsets: number[] = [];
  objects.forEach((obj, i) => {
    offsets.push(buf.length);
    buf = Buffer.concat([buf, Buffer.from(`${i + 1} 0 obj\n`, "latin1"), obj, Buffer.from("\nendobj\n", "latin1")]);
  });
  const xrefStart = buf.length;
  let xref = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) xref += `${String(off).padStart(10, "0")} 00000 n \n`;
  const trailer = `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;
  buf = Buffer.concat([buf, Buffer.from(xref + trailer, "latin1")]);
  return buf.toString("base64");
}

const SYNTHETIC_CHART_PNG_B64 = syntheticChartPng();

function caseToBlocks(c: CorpusCase): WiseManContentBlock[] {
  const blocks: WiseManContentBlock[] = [];
  if (c.pairWithImage) {
    blocks.push({ type: "image", mediaType: "image/png", dataBase64: SYNTHETIC_CHART_PNG_B64 });
  }
  if (c.pairWithPdf) {
    const pdfBody = c.sourceNote?.startsWith("PDF body")
      ? c.sourceNote.replace(/^PDF body:?\s*'?/, "").replace(/'$/, "")
      : c.text;
    blocks.push({ type: "document", mediaType: "application/pdf", dataBase64: syntheticPdf([pdfBody]) });
  }
  blocks.push({ type: "text", text: c.text });
  return blocks;
}

interface CaseResult {
  id: string;
  expected: boolean;
  actual: boolean;
  correct: boolean;
  failedClosed: boolean;
}

async function runCase(c: CorpusCase, expectedBlocked: boolean): Promise<CaseResult> {
  const verdict = await checkGuardrail({ blocks: caseToBlocks(c), direction: "inbound", apiKey: apiKey! });
  return {
    id: c.id,
    expected: expectedBlocked,
    actual: verdict.blocked,
    correct: verdict.blocked === expectedBlocked,
    failedClosed: verdict.failedClosed,
  };
}

function report(label: string, results: CaseResult[]): void {
  const correct = results.filter((r) => r.correct).length;
  console.log(`\n=== ${label}: ${correct}/${results.length} correct ===`);
  for (const r of results.filter((r) => !r.correct)) {
    console.log(`  MISS ${r.id}: expected blocked=${r.expected}, got blocked=${r.actual} (failedClosed=${r.failedClosed})`);
  }
}

async function main() {
  const textOnlyBlock = MUST_BLOCK.filter((c) => !c.pairWithImage);
  const textOnlyNotBlock = MUST_NOT_BLOCK.filter((c) => !c.pairWithImage);
  const attachmentBlock = MUST_BLOCK.filter((c) => c.pairWithImage);
  const attachmentNotBlock = MUST_NOT_BLOCK.filter((c) => c.pairWithImage);

  const blockResults = await Promise.all(textOnlyBlock.map((c) => runCase(c, true)));
  const notBlockResults = await Promise.all(textOnlyNotBlock.map((c) => runCase(c, false)));
  const attachBlockResults = await Promise.all(attachmentBlock.map((c) => runCase(c, true)));
  const attachNotBlockResults = await Promise.all(attachmentNotBlock.map((c) => runCase(c, false)));
  const injectionResults = await Promise.all(INJECTION_CASES.map((c) => runCase(c, true)));

  report("MUST_BLOCK (text only)", blockResults);
  report("MUST_NOT_BLOCK (text only)", notBlockResults);
  report("MUST_BLOCK (attachment-bearing)", attachBlockResults);
  report("MUST_NOT_BLOCK (attachment-bearing)", attachNotBlockResults);
  report("INJECTION_CASES (all must block)", injectionResults);

  const blockRateText = blockResults.filter((r) => r.correct).length / blockResults.length;
  const fpRateText = 1 - notBlockResults.filter((r) => r.correct).length / notBlockResults.length;
  const blockRateAttach =
    attachBlockResults.length > 0 ? attachBlockResults.filter((r) => r.correct).length / attachBlockResults.length : null;
  const fpRateAttach =
    attachNotBlockResults.length > 0
      ? 1 - attachNotBlockResults.filter((r) => r.correct).length / attachNotBlockResults.length
      : null;

  console.log(`\n=== SUMMARY (Sec 4.1.3 / 11.5 numbers) ===`);
  console.log(`Text-only block rate: ${(blockRateText * 100).toFixed(1)}%`);
  console.log(`Text-only false-positive rate: ${(fpRateText * 100).toFixed(1)}%`);
  if (blockRateAttach !== null) console.log(`Attachment-bearing block rate: ${(blockRateAttach * 100).toFixed(1)}%`);
  if (fpRateAttach !== null) console.log(`Attachment-bearing false-positive rate: ${(fpRateAttach * 100).toFixed(1)}%`);

  // Multi-turn erosion (Sec 11.3): send all prior turns as context, check the FINAL turn.
  console.log(`\n=== MULTI_TURN_EROSION (Sec 11.3) ===`);
  let multiTurnCorrect = 0;
  for (const seq of MULTI_TURN_EROSION) {
    const priorUserTurns = seq.turns.slice(0, -1);
    const finalTurn = seq.turns[seq.turns.length - 1];
    const verdict = await checkGuardrail({
      blocks: [{ type: "text", text: finalTurn }],
      direction: "inbound",
      apiKey: apiKey!,
      priorUserTurns,
    });
    const ok = verdict.blocked === true;
    if (ok) multiTurnCorrect++;
    console.log(`  ${ok ? "OK" : "MISS"} ${seq.id}: final turn blocked=${verdict.blocked}`);
  }
  console.log(`Multi-turn erosion: ${multiTurnCorrect}/${MULTI_TURN_EROSION.length} correctly blocked on the final turn`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
