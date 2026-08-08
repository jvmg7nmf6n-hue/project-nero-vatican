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

## ADDENDUM (2026-08-08) — GATE B Follow-Up Directive: Bellwether count + Redis fail-closed

CC-1 directive "Wise Man: GATE B Follow-Up (Pre-Merge Clarifications)".
Resolves exactly the two items that directive raised. Does not open GATE C.

### 1. Bellwether test-count discrepancy — GATE A/B report was wrong, corrected

**FINDING:** The GATE B closing report's "Bellwether: 25/25 pass" identified
the **wrong suite entirely**. `tests/test_macro_reads.py` +
`tests/test_bellwether_overlay.py` (root `tests/` dir, run via `unittest`)
are Vatican-side tests of a Bellwether-*overlay-consuming* feature
(`nero_core/execution/bellwether_overlay.py`) — a real but different thing
from the actual **Bellwether engine**, a separate, independently-versioned
Python project living at `vatican/bellwether/` with its own
`pyproject.toml`/`pytest.ini` (`asyncio_mode = "auto"`, `testpaths =
["tests"]`), its own `requirements-lock.txt`, and its own 10-file `tests/`
directory (75 test functions). This second suite was never discovered or
run during GATE A's Sec 1.9 baseline research — a real gap in that research
agent's search, not a Wise Man regression.

Real, verified numbers, run exactly as the subproject specifies:

```
cd vatican/bellwether
pip install -r requirements-lock.txt   # installed into the repo's shared .venv;
                                        # confirmed no conflicts (5 packages added:
                                        # fastapi, starlette, uvicorn, click, annotated-doc --
                                        # pydantic/httpx/pytest/pytest-asyncio already
                                        # satisfied the pin)
python -m pytest -q
```
```
........................................................................ [ 96%]
...                                                                      [100%]
75 passed in 29.02s
```

**75 passed, 0 failed, 0 skipped** — matching the directive's stated
baseline exactly (75/0), not the GATE B report's "25/25" (wrong suite) and
not `vatican/bellwether/README_VATICAN.md:153`'s own documented figure
("30 passed, 1-2 skipped") either — that README line is itself now stale
(the suite has grown to 75 since it was written, the same kind of
count-drift found and corrected in the root Python suite's
`test_eve_citation_freshness.py` during GATE A). Not fixed here — out of
this directive's scope (only the closing report's own count needed
correcting) and it's a pre-existing doc, not something this branch touched.

**`git diff --stat main...feature/wise-man -- vatican/`** → **empty
output**. `feature/wise-man` touches nothing under `vatican/` at all.
`vatican/bellwether/pytest.ini` already exists on `main`
(`git show main:vatican/bellwether/pytest.ini` confirms it). So the real
75/0 result is unaffected by this branch either way — the "25/25" number in
the prior report was a pure identification error in GATE A's own research,
corrected here, not a masked regression.

**On the "asyncio_mode collision" issue** named in the directive: verified
directly, not assumed. Running plain `pytest --collect-only -q` from the
**repo root** (no scoping) collects **2880 tests** — both the root
`unittest`-style `tests/` directory AND `vatican/bellwether/tests/` in one
pytest session, because there is no root-level `pytest.ini` to scope
collection and pytest's default rootdir search reaches both trees. This
confirms the two suites are not just conceptually separate but must be
**invoked separately, from their own directories, with their own runners**
(`unittest discover -s tests` from repo root; `pytest -q` from
`vatican/bellwether/`) — mixing them in one bare `pytest` invocation is a
real, reproducible collision risk, not a hypothetical one. CONFIDENCE:
confirmed-from-data (both counts and the collision are real command output,
not inferred).

**Safety-relevant coverage check**: none of the 75 Bellwether tests were
skipped, deselected, or removed to reach this number — all 75 ran and
passed. No evidence-bar or correlation-discount logic lives in
`vatican/bellwether/` (that logic is in `nero_core/eve/scoring.py` and
`tools/backtest_statistics.py`, covered by the root Python suite and
`tests/test_evidence_bar_unchanged.py`, both separately confirmed unchanged
in the main GATE C checklist above).

**RECOMMENDATION:** correct the GATE B report's "Section 1: Test counts"
table (item 1 in this same file, above) — done: the "Before/After" Bellwether
row should read **75 tests, all pass** for both columns (this branch never
touched Bellwether), not 25/25. Left the original text as-is above (per
this directive's own instruction: this addendum corrects it "in place" by
being the authoritative dated correction) rather than silently editing the
historical entry, so the error and its correction are both on record.

### 2. Production Redis dependency — fail-closed shipped

**FINDING (exact mechanism, file+line, corrected from the GATE B report's
vaguer "silently ineffective" phrasing):** Before this fix,
`website/app/api/wise-man/route.ts:78` called `loadStore()` fresh on
**every POST request**, with no module-level caching. When
`UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` were unset,
`loadStore()` returned `createInMemoryCounterStore()`
(`website/lib/wiseMan/budget.ts:43-51`), which constructs a **brand-new,
empty `Map<string, number>()` on that call**. Because this happened inside
the request handler itself rather than at module scope, every single
request got its own fresh counter starting at zero — the rate limiter and
spend cap could **never** reach any cap, regardless of request volume. This
is a complete no-op, not a degraded-but-functional mechanism (the GATE B
report's phrasing undersold the severity). CONFIDENCE: confirmed-from-code.

**Options considered (per the directive's instruction not to silently
pick):**

| Option | Behavior | Trade-off |
|---|---|---|
| (a) Fail closed | Refuse to serve any Wise Man request while the flag is on and no real store is configured; loud server log | Safe by default — an unconfigured deploy simply can't spend money without a cap. Costs availability: Wise Man silently (from the visitor's perspective) doesn't work until Redis is linked. |
| (b) Loud warning, still serve | Log loudly but proceed using the no-op in-memory store | Availability-first — Wise Man "works" the moment the flag flips. Requires a human to actually notice a log line before the spend/rate protection is real; the exact silent-failure shape this directive was raised to close. |

**WHAT SHIPPED: (a), fail closed.** Consistent with the fail-closed posture
already used everywhere else in this build (the guardrail's own
`checkGuardrail()`, the rate limiter, and the budget check in
`handleRequest.ts` all fail closed on their own errors already — see the
main checklist above) — extending the same posture to a *misconfiguration*
rather than only a *runtime error* was a natural, justified default, not an
arbitrary pick. (b) was rejected specifically because a log line nobody is
guaranteed to read is not a real substitute for the cap actually existing
when real money is on the line.

**Real code change:** `website/app/api/wise-man/route.ts` — a new
`hasRealCounterStoreConfigured()` check (also matching `@upstash/redis`'s
own `Redis.fromEnv()` fallback to the legacy `KV_REST_API_URL`/`_TOKEN`
names, verified directly against `node_modules/@upstash/redis/nodejs.js:
5708-5729` — the initial version of this check would have been a false
negative on a deployment still using those legacy names) gates the top of
`POST()`: if `isWiseManEnabled()` is true and no real store is configured,
log one CRITICAL-tagged line naming the missing env vars and return 503
with the new `storage_not_configured` bilingual error code
(`website/lib/wiseMan/errors.ts`) — before parsing the request body, before
any network call. 4 new tests in `website/__tests__/wiseManRoute.test.ts`
(`@jest-environment node`, calling the real `POST` handler directly, same
pattern as `chatRoute.test.ts`): fails closed with the CRITICAL log and
zero model calls when flag-on/no-Redis; does not fire when the flag is off;
does not fire when Redis is configured via either naming convention. Full
website suite after this change: **85/85 suites, 947/947 tests**; `next
build`/`next lint` clean. Commit: `3b8a3ad`.

**Concrete Upstash Redis linking steps for this repo's own deploy setup**
(not a generic tutorial — scoped to what's actually true here): this repo
has no root-level `vercel.json`; only `website/vercel.json` exists
(`{"framework": "nextjs"}`), consistent with the Vercel project's **Root
Directory** being set to `website` in this monorepo (GATE A finding 1.5's
own confirmation that the live deploy is `https://project-nero-vatican.vercel.app`,
serving from this subfolder). Steps:

1. In the Vercel dashboard, open the `project-nero-vatican` project (the
   one whose Root Directory is `website`).
2. Go to the **Storage** tab (or **Integrations** → **Browse Marketplace**
   → search "Upstash") and add an **Upstash** Redis database/integration.
3. Sign in to (or create) the Upstash account when prompted, then choose
   **Create Database** (or link an existing Redis instance if one already
   exists for this project) when the integration asks which database to
   use.
4. **Select `project-nero-vatican` as the project to connect it to** — this
   is the step that actually writes the environment variables into this
   Vercel project's env var settings; skipping it (e.g. creating the
   database in the Upstash console directly, outside the Vercel
   integration flow) will NOT populate them automatically and requires
   copying `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` in by hand
   instead from the Upstash console's own database details page.
5. Confirm the two variables landed in **Project Settings → Environment
   Variables** for this project: `UPSTASH_REDIS_REST_URL` and
   `UPSTASH_REDIS_REST_TOKEN` (these exact names — verified directly
   against the installed `@upstash/redis` package's own `Redis.fromEnv()`
   source, not assumed from generic docs). Apply them to the Production
   environment at minimum (Preview/Development too, if Wise Man should be
   testable pre-merge on preview deploys).
6. Redeploy (or trigger a new deployment) so the running instance picks up
   the new environment variables — Vercel does not hot-reload env vars into
   already-running serverless functions.
7. Verify: with `WISE_MAN_ENABLED=1` also set, a request to `/api/wise-man`
   should no longer produce the `[wise-man] CRITICAL:` log line added in
   this directive's fix. If it still does, re-check step 5 — the most
   common failure mode is the variables landing in a different Vercel
   *environment* (e.g. only Preview, not Production) than the one actually
   serving traffic.

Source for the general integration flow: Vercel Marketplace's own Upstash
integration page (accessed 2026-08-08); the exact env var names and their
legacy fallback were verified directly against this repo's own installed
`@upstash/redis` package source, not the marketplace page (which does not
state the variable names explicitly).

### Push verification

```
git log origin/feature/wise-man --oneline -3
```
```
3b8a3ad Wise Man: fail closed when enabled with no real counter store configured
484fdb6 Wise Man: closing implementation report / Sec 10 GATE C checklist
fe36854 Wise Man: GOLDEN_QUESTIONS acceptance run (19/19) + real cost benchmark
```

### This remains a hard stop

Per this directive's own explicit scope: **no GATE C activity was
performed and none is implied by this addendum.** Both items raised are now
resolved with real, verified evidence. No merge to `main` without an
explicit, separate human go-ahead.

---

**This report is the GATE C checklist. Per Sec 0.2/Sec 10: stop and ask.**
No merge to `main` will be performed without an explicit human go-ahead.
