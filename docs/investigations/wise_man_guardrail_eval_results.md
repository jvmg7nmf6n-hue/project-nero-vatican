# Wise Man Guardrail — Real Evaluation Results

CC-1 Wise Man directive v3, Sec 4.1.3 / 4.1.4 / 4.1.5 / 11.3 / 11.5 evidence.
Real API calls against `claude-haiku-4-5`, run twice for consistency (both
runs identical). Command:

```
cd website && node --env-file=../.env scripts/wiseManGuardrailEval.ts
```

Run date: 2026-08-08.

## Results (both runs identical)

| Corpus | Result |
|---|---|
| MUST_BLOCK (text only, n=27) | 27/27 correct — block rate 100.0% |
| MUST_NOT_BLOCK (text only, n=27) | 27/27 correct — false-positive rate 0.0% |
| MUST_BLOCK (attachment-bearing, n=3) | 3/3 correct — block rate 100.0% |
| MUST_NOT_BLOCK (attachment-bearing, n=2) | 2/2 correct — false-positive rate 0.0% |
| INJECTION_CASES (n=3, all PDF-based) | 3/3 correct |
| MULTI_TURN_EROSION (n=6 sequences, incl. 1 Roman Urdu) | 6/6 correctly blocked on the final turn |

Text-only corpus (n=54) covers direct, hypothetical, roleplay, third-person,
and site-copy/definitional framings, in both English and Roman Urdu (5 of
30 MUST_BLOCK cases and 3 of 29 MUST_NOT_BLOCK cases are Roman Urdu).

## Known gap, found and documented during this run

An earlier `inj02` case described an image with "overlaid injection text"
that was never actually rendered into the synthetic PNG (the hand-rolled PNG
generator in `wiseManGuardrailEval.ts` draws colored bars only — no text
rendering, no font library dependency). The guardrail correctly reported
"not blocked" because the actual image bytes sent contained no injection at
all — the test's description didn't match its own data, not a guardrail
miss. Fixed by replacing it with a second, real PDF-based injection case
(now 3/3 PDF-based injection cases, all real). **An image-based (pixels, not
document-attached) prompt-injection test remains unbuilt** — flagged as an
open item for the Sec 10 closing report, not silently claimed as covered.

## Reproducibility

The full corpus lives in `website/lib/wiseMan/guardrailCorpus.ts`
(`MUST_BLOCK`, `MUST_NOT_BLOCK`, `INJECTION_CASES`, `MULTI_TURN_EROSION`),
schema-tested in `website/__tests__/wiseManGuardrailCorpus.test.ts`. The
`checkGuardrail()` function's own mechanics (fail-closed, shared code path
across all 4 input types, JSON parsing, no-secret-logging) are unit-tested
with mocked responses in `website/__tests__/wiseManGuardrail.test.ts` — those
run in `npm test` and cost nothing; this real-API evaluation is a separate,
manually-run step, not part of CI.
