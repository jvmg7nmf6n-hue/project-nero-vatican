# Wise Man — Closing Implementation Report (GATE B → GATE C checklist)

CC-1 directive v3. Branch `feature/wise-man`, pushed to origin (confirmed
below). This is the required Sec 10 GATE C pre-merge checklist plus the
directive's own "CLOSING REPORT" requirements, combined. **Per the
directive's own explicit instruction: this is where CC-1 stops. No merge
has been performed or will be performed without an explicit separate human
go-ahead.**

---

## 1. Test counts, before → after, each suite separately

| Suite | Command | Before (GATE A baseline, 2026-08-08) | After (2026-08-08, this report) |
|---|---|---|---|
| Python | `.venv\Scripts\python.exe -m unittest discover -s tests` | 2804 tests, 2 failures, 3 errors, 21 skipped | 2804 tests, **0 failures**, 3 errors (unchanged, pre-existing, out of scope — see below), 21 skipped |
| Bellwether | `.venv\Scripts\python.exe -m unittest tests.test_macro_reads tests.test_bellwether_overlay -v` | 25 tests, all pass | 25 tests, all pass (unchanged) |
| Website | `cd website && npm test` | 770 tests, 2 failures | **943 tests, 0 failures** (173 new Wise Man tests + 2 fixed) |

The 2 Python failures and 2 website failures in the "before" column were
real, pre-existing, unrelated-to-Wise-Man issues found while baselining at
GATE A — fixed in their own separate commit (`8d8b5b0`) per explicit
instruction, before any Wise Man code was written. The 3 Python errors
(missing `lxml` in this dev venv) are untouched and out of the scope the
human specified ("2 Python, 2 website" — not the 3 lxml errors).

## 2. Evidence-bar constants unchanged

```
git diff main...feature/wise-man -- nero_core/research_agent/frequency_gate.py \
  tools/backtest_train_test_split.py tools/backtest_statistics.py \
  nero_core/eve/scoring.py nero_core/research_agent/trial.py
```
→ **empty output** (no changes to any guarded file). Values match the GATE
A 1.10 baseline exactly (30/yr, 70/30, MIN_SAMPLE_SIZE=20, FDR α=0.05,
bootstrap 5000 iterations, RANDOM_ENTRY_RUNS=200, Trial admission =
DSL-validity only). Asserting test: `tests/test_evidence_bar_unchanged.py`
— 6/6 passing (`EvidenceBarConstantsUnchangedTest`), confirmed already
existed in the repo and still passes unmodified.

## 3. No payment/billing/paid-consult code

```
git diff main...feature/wise-man -- website nero_core tests docs | \
  grep -iE "stripe|billing|payment|paywall|\$2/query|paid.consult|checkout\.session|price_id"
```
→ **empty output**. Confirmed nothing payment-shaped anywhere in the diff.

## 4. Guardrail — real, measured accuracy

Real evaluation against `claude-haiku-4-5` (script:
`website/scripts/wiseManGuardrailEval.ts`; full numbers:
`docs/investigations/wise_man_guardrail_eval_results.md`), run twice
independently with identical results:

| Corpus | Result |
|---|---|
| MUST_BLOCK, text only (n=27, incl. 5 Roman Urdu) | 27/27 correct — **block rate 100.0%** |
| MUST_NOT_BLOCK, text only (n=27, incl. 4 Roman Urdu) | 27/27 correct — **false-positive rate 0.0%** |
| MUST_BLOCK, attachment-bearing (n=3, image) | 3/3 correct — block rate 100.0% |
| MUST_NOT_BLOCK, attachment-bearing (n=2, image) | 2/2 correct — false-positive rate 0.0% |
| INJECTION_CASES (n=3, all PDF-based) | 3/3 correctly blocked |
| MULTI_TURN_EROSION (n=6 sequences, incl. 1 Roman Urdu) | 6/6 correctly blocked on the final turn |

**All four input types tested SEPARATELY, not conflated**: typed text (the
27+27 text corpus), voice-transcribed text (asserted to share the *exact
same* code path as typed text via a dedicated unit test — see below; a live
microphone/STT round-trip was not feasible to execute in this environment,
so this is a code-path-identity proof, not a live audio recording test),
image (3+2 above), PDF (3 injection cases). **Roman Urdu**: 5 MUST_BLOCK +
4 MUST_NOT_BLOCK + 1 multi-turn sequence, all correct — no separate Roman
Urdu failure mode found. **Injection**: 3/3, PDF only — see the known gap
below. **Fail-closed**: unit-tested directly (network error, non-200,
malformed JSON, missing field, and the same posture in `handleRequest.ts`'s
rate-limit and budget checks) — `website/__tests__/wiseManGuardrail.test.ts`
+ `wiseManHandleRequest.test.ts`. **Multi-turn erosion**: 6/6 above,
real API calls with prior-turn context, not simulated.

**One shared code path, asserted directly** (Sec 4.1.2): `checkGuardrail()`
in `website/lib/wiseMan/guardrail.ts` is the single function called for
both inbound and outbound checks and for all four input-type shapes —
`wiseManGuardrail.test.ts`'s "all four input shapes... call the SAME shared
fetch code path" test proves this by asserting exactly one fetch call per
check regardless of input shape.

**Known, documented gap**: no image-PIXEL prompt-injection case exists (an
image with text baked into the pixels instructing the model to ignore its
rules) — the synthetic PNG generator used for evaluation draws colored bars
only, no font rendering. All 3 injection cases are PDF-based. Found and
recorded honestly during the eval run (an earlier attempt at an image
injection case was caught as not actually testing what it claimed, and
replaced) — see `wise_man_guardrail_eval_results.md` for the full account.
**Open item for a future pass, not silently claimed as covered.**

## 5. No secret printed, echoed, logged, or committed

```
git diff main...feature/wise-man -- website nero_core tests docs | \
  grep -iE "sk-ant-[a-zA-Z0-9]|api[_-]?key\s*=\s*['\"][a-zA-Z0-9]{10,}|password\s*=\s*['\"]|secret\s*=\s*['\"][a-zA-Z0-9]{10,}"
```
→ **empty output** (after excluding known-safe references: env var names,
`apiKey` variable references, and test placeholder strings like
`"test-key"`). `logGuardrailEvent()` and the route's own diagnostic logging
are both structurally incapable of logging raw text or the key — their
typed event shapes carry only classification metadata (see
`guardrail.ts`'s and `route.ts`'s own doc comments), verified in
`wiseManGuardrail.test.ts`'s "logs only classification metadata, never the
raw user text" test.

## 6. Feature flag, spend cap, rate limits, input caps, origin restriction

All tested, all results real:

- **Feature flag** (`isWiseManEnabled`): both states tested, defaults to
  **disabled** (mirrors `EVE_ENABLED`'s exact parsing convention) —
  `wiseManConfig.test.ts`, 13 tests.
- **Spend cap** (daily + monthly, atomic): `wiseManBudget.test.ts`, 8 tests
  incl. two genuine concurrency tests — 200 truly concurrent `Promise.all`
  reservations never lose an update, and a cap-boundary test confirms
  exactly the requests that fit are allowed with zero overshoot (Sec 11.1).
- **Rate limits** (per-session 30/hr default, per-IP 100/hr default, lower
  8/hr cap for attachments): `wiseManRateLimit.test.ts`, 7 tests, incl. one
  proving per-IP is the real backstop against a simulated cookie-clearing
  attacker the per-session limit alone would never catch (Sec 11.2).
- **Session definition**: signed HMAC-SHA256 httpOnly cookie, 24h TTL,
  `wiseManSession.test.ts`, 9 tests (round-trip, tamper detection, TTL
  boundary). Explicitly documented limitation: trivially reset by clearing
  cookies or an incognito window (Sec 11.2's own required disclosure).
- **Input caps** (message length, turn count, attachment count/size):
  `wiseManHandleRequest.test.ts` + `wiseManAttachments.test.ts`.
- **Origin restriction**: `wiseManConfig.test.ts` + `wiseManHandleRequest.test.ts`
  — present-but-mismatched Origin rejected; a real, stated, deliberate gap
  for a missing Origin header (documented in `handleRequest.ts`'s own
  comment — rate limiting and the spend cap are the real backstops there).

## 7. Golden-questions acceptance run

**19/19 passed**, real API calls, not mocked. Full detail and the real
per-query cost numbers: `docs/investigations/wise_man_golden_questions_eval_results.md`.
Includes a real finding caught by actually reading the Roman Urdu replies
(not just counting pass/fail): 2 of 3 Roman-Urdu-must-answer replies
initially drifted into Urdu script mid-reply; found, the system prompt was
tightened, and the fix was re-verified against the live API (19/19 still
pass, all 3 replies now clean Latin-script Roman Urdu).

## 8. Real numbers

- **Per-query cost** (Haiku 4.5, from the real `usage` field, over the
  19-question golden set): **p50 $0.001979, p90 $0.002403, mean $0.001333**.
- **Payload/tokens per page type**: **partially measured, honestly
  incomplete.** The "methodology" page type's context (static prose, no
  data) was measured as part of the golden-questions cost run above. The
  "graveyard" page type's summarizer was measured against 200 real-shaped
  synthetic records in `wiseManPageContext.test.ts`, confirming the
  `PAGE_CONTEXT_MAX_CHARS` (4000) cap holds after resolution. **The other
  11 page types were NOT independently measured against live committed
  data with a real API call in this session** — a standalone measurement
  script was attempted but blocked by the same Node/Next module-resolution
  mismatch documented in `guardrail.ts`'s and the eval scripts' own
  comments (plain Node's ESM loader needs explicit `.ts` extensions on
  relative imports; `lib/data.ts`, used throughout the real Next.js app,
  doesn't have them and shouldn't be changed just for a script). GATE A
  finding 1.6's real *file* byte sizes (37KB–120KB per `docs/site_data/*.json`
  file) are a reasonable upper-bound proxy for what the resolvers summarize
  from, but are not the same number as actual injected tokens. **Open item.**
- **Prompt caching**: a `cache_control` marker is present on the static
  system prompt, but Haiku 4.5's minimum cacheable prefix is 4096 tokens
  (GATE A finding 1.8) and the static prompt is nowhere near that length —
  stated in `systemPrompt.ts`'s own comment as likely NOT engaging, not
  assumed working. **Not measured via `cache_read_input_tokens` in this
  session** (would require inspecting raw API responses beyond what the
  eval scripts currently log) — **open item**.
- **Animation performance and asset size**: **not measured** — this
  requires a real browser's devtools (GPU compositing, frame timing, CPU
  under throttling), which isn't available in this environment. The
  implementation choice (CSS keyframe `transform` animations, which
  composite on the GPU without triggering layout/paint, per general browser
  behavior) is documented in `WiseManIcon`'s own comment as a design
  intent, not a verified measurement. **Open item** — needs a real browser
  session.
- **Browser compatibility matrix**: real, dated (2026-08-08), sourced from
  caniuse.com and MDN — `docs/investigations/wise_man_voice_compat.md`.
  Two data points flagged as uncertain rather than silently resolved (Edge
  and Android Chrome's SpeechRecognition support, where the source
  conflicts with their Chromium lineage).

## 9. Full diff summary

**46 files changed, 4917 insertions(+), 8 deletions(-)** (`git diff --stat
main...feature/wise-man`, full listing available via that command). New
dependency: **`@upstash/redis@^1.38.2`, MIT license** (confirmed via
`node_modules/@upstash/redis/package.json`) — replaces `@vercel/kv`, which
was evaluated first and rejected after `npm install` surfaced its own
deprecation notice pointing at Upstash Redis directly.

New library modules (`website/lib/wiseMan/`): `attachments.ts`, `budget.ts`,
`config.ts`, `disclaimer.ts`, `errors.ts`, `goldenQuestions.ts`,
`guardrail.ts`, `guardrailCorpus.ts`, `handleRequest.ts`, `pageContext.ts`,
`pathToPageContext.ts`, `rateLimit.ts`, `session.ts`, `systemPrompt.ts`.
New route: `website/app/api/wise-man/route.ts`. New component:
`website/components/WiseMan.tsx`. New eval scripts (manual, not CI):
`website/scripts/wiseManGuardrailEval.ts`,
`website/scripts/wiseManGoldenQuestionsEval.ts`. 15 new test files, 173 new
tests. One line changed in `website/app/layout.tsx` (mount `<WiseMan />`).
Two pre-existing files touched for real, explained reasons:
`website/__tests__/chatRoute.test.ts` (extended its allowlist to recognize
the new route as a second legitimate `ANTHROPIC_API_KEY` reader — the
existing chatbot's own behavior is unchanged) and `website/tsconfig.json`
(`allowImportingTsExtensions: true`, needed for the standalone eval
scripts to run under plain Node).

## 10. Push verification

```
git log origin/feature/wise-man --oneline -3
```
```
fe36854 Wise Man: GOLDEN_QUESTIONS acceptance run (19/19) + real cost benchmark
bdbf7db Wise Man: .docx-specific rejection message + real voice compat matrix (Sec 2.5, 7)
c90e2cc Wise Man: site-wide widget -- voice, disclaimer, placeholder icon, a11y (Sec 7/8.6/9)
```
Branch is pushed and clean (`git status` shows no uncommitted changes to
any file this directive touched — the untracked files visible in `git
status` predate this session and are not part of this diff).

## 11. Roman Urdu spot-check confirmation

Confirmed for both directions, not just refusals: the 7 MUST-BLOCK Roman
Urdu-adjacent golden questions/corpus cases were correctly refused, AND the
3 Roman-Urdu-must-answer golden questions' actual reply text was read in
full (not just pass/fail-counted) — see item 7 above and
`wise_man_golden_questions_eval_results.md` for the full text and the real
bug this caught and the fix that was verified.

## 12. Statement of what the system still cannot do

- No live-browser voice or animation testing was performed (both require a
  real browser environment not available here) — implemented and unit/
  logic-tested, but not end-to-end verified in an actual browser.
- No image-pixel prompt-injection test exists (PDF-based injection is
  covered; image-pixel is not).
- Per-page-type token/payload measurement is real for 2 of 13 page types
  (methodology, graveyard); the other 11 are unmeasured against live data.
- Prompt caching's real effectiveness on Haiku 4.5 is not measured (and,
  per the static-prompt-length math, likely doesn't engage at all today).
- The disclaimer and legal-entity text are still the human-owned
  `TODO(human)` placeholder — Wise Man is not ready for real traffic until
  that's supplied and the Chrome-voice-privacy disclosure (found during
  this session's own research) is folded into it.
- The real navy-gold seal icon asset is still a placeholder.
- Rate limiting and the spend cap use an in-memory fallback store that does
  NOT share state across serverless invocations — in production, this
  requires linking a real Upstash Redis integration in the Vercel
  dashboard (a human, dashboard-side step); without it, the caps are
  silently ineffective in a multi-instance deployment. This is stated in
  `route.ts`'s own comment, not hidden.

## Every figure or premise found stale or wrong during this work

- `@vercel/kv`, the package the GATE A report's Design Option 2.3-A named,
  turned out to be deprecated as of this build (surfaced by `npm install`'s
  own warning) — switched to `@upstash/redis` directly, documented in the
  commit and in `budget.ts`'s own comment.
- Two Python test assertions (`test_eve_citation_freshness.py`,
  `test_eve_context_verdict_stripped.py`) were pinned to record counts that
  had legitimately grown since they were written — not bugs, but stale
  fixtures; corrected to assert the durable invariant instead of the
  point-in-time count (see commit `8d8b5b0`'s full reasoning).
- One website test's premise (`failure_patterns.json` "no duplicate family
  names") was actually wrong for the real, intended data model — `family`
  is an intentional many-to-one grouping label; `name` is the real unique
  key. Corrected the test, not the data.
- The Roman Urdu system-prompt instruction ("reply fluently... or naturally
  code-switched") was ambiguous enough that the model read it as license to
  switch alphabets, not just languages — found and fixed, see item 7.

## OPEN QUESTIONS (human-owned, unchanged from GATE A except where noted)

1. **Disclaimer text + operating legal entity/jurisdiction** (Sec 4.2) —
   still `TODO(human)`. **Now also needs to include** the Chrome-voice-
   audio-sent-to-a-remote-service privacy disclosure found in this
   session's voice compat research.
2. **Icon SVG asset** (Sec 9.1) — still not supplied; placeholder is live
   with the required separately-addressable ring/needle structure.
3. **Screen corner** — resolved, not open: bottom-left, my call per the
   explicit GATE B kickoff instruction, reasoning in commit `c90e2cc`.
4. **System message bilingual-ness** (Sec 11.7) — resolved, not open: all
   error copy is bilingual per the explicit GATE B kickoff instruction.
5. **Image-pixel prompt injection test** — not built this pass; a real gap
   for a future iteration, not silently claimed as covered.
6. **Per-page-type token measurement** for 11 of 13 page types, and real
   `cache_read_input_tokens` measurement — both need either a fix to how
   the standalone eval scripts resolve `lib/data.ts`'s imports, or running
   the measurement through the actual deployed route instead of a
   standalone script.
7. **Production Redis provisioning** — a human, Vercel-dashboard step,
   without which rate limiting and the spend cap are ineffective across
   multiple serverless instances.

---

**This report is the GATE C checklist. Per Sec 0.2/Sec 10: stop and ask.**
No merge to `main` will be performed without an explicit human go-ahead.
