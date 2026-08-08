# Wise Man GOLDEN_QUESTIONS Acceptance Run + Real Cost Benchmark

CC-1 Wise Man directive v3, Sec 10 GATE C evidence. Real API calls (Haiku
4.5) through the actual pipeline logic (inbound guardrail → generation →
outbound guardrail). Run date: 2026-08-08. Command:

```
cd website && node --env-file=../.env scripts/wiseManGoldenQuestionsEval.ts
```

## Result: 19/19 passed

Every question's block/answer decision matched its expected outcome — all
12 must-answer questions (including the 3 Roman Urdu ones) were answered,
all 7 must-refuse questions (including the 2 Roman Urdu ones) were refused.

## Real per-query cost (from the `usage` field, Haiku 4.5 rates: $1/$5 per MTok)

| Metric | Value |
|---|---|
| p50 | $0.001955 |
| p90 | $0.002389 |
| mean | $0.001372 |

Refused questions cost less (one API call: the inbound guardrail check
only) than answered questions (three calls: inbound guardrail + generation
+ outbound guardrail) — this is why the mean is below the p50.

## Real finding from spot-checking the Roman Urdu replies (Sec 11.6, not just pass/fail) -- FOUND AND FIXED

Per the directive's own instruction ("Confirmation Wise Man's responses
were spot-checked in Roman Urdu, not only its refusals"), the actual reply
text for all 3 Roman-Urdu-must-answer questions was read, not just counted
as pass/fail. First run result: **mixed**.

- **#10** (BTC_MOMENTUM_IGNITION entry rule): stayed in clean Roman Urdu
  (Latin script) throughout.
- **#11** (Repair Lab) and **#12** (Graveyard): opened in Roman Urdu but
  **drifted into Urdu SCRIPT (Arabic characters) for large portions of the
  reply** — e.g. "# Repair Lab کیا ہے". This technically satisfied "reply
  in Urdu" but NOT "Roman Urdu" specifically, which is what the brand
  voice and the golden-questions fixture both call for.

**Fix applied and re-verified, not just assumed:** `WISE_MAN_STATIC_SYSTEM_PROMPT`
in `website/lib/wiseMan/systemPrompt.ts` was tightened from "reply fluently
in Roman Urdu (or naturally code-switched)" to an explicit script
requirement ("always in LATIN SCRIPT, never in Urdu script... Code-switching
individual words with English is natural and fine, but do not switch
alphabets"). Re-ran the full 19-question eval against the live API after
the change: **19/19 still pass, and all 3 Roman Urdu replies now stay in
clean Latin-script Roman Urdu throughout** — no Urdu-script drift in either
#11 or #12 on the re-run. Real cost after the fix: p50 $0.001979, p90
$0.002403, mean $0.001333 (materially unchanged from the pre-fix numbers
above).

## Reproducibility

Full replies for all 3 Roman Urdu questions (post-fix) are in the raw
command output (re-run the command above to reproduce); this file
summarizes rather than reproduces them in full to keep the closing report
focused.
