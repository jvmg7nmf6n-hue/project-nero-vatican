# LLM News Sentiment — Live Validation (non-mocked)

Validation run of `nero_core/strategies/news_sentiment_llm.py` (`news-sentiment-v2.0.0-llm-claude`)
against the real Anthropic Messages API, on `feature/news-sentiment`. This is a plumbing/honesty-gate
validation, not a demonstration and not a calibration study.

## Setup facts (from Step 0 code reading, recorded before any live call)

- Model: `claude-sonnet-5`, `max_tokens=400`, single-headline-per-call prompt (see `_call_claude`).
- **Temperature is not set in the production request body at all.** No override is applied for this
  test either (per instruction: do not touch the production call path). The Anthropic Messages API's
  default temperature therefore applies. This means non-determinism across the two runs below is
  expected, not a bug — it is itself the thing being measured by comparing run 1 vs run 2.
- Gates (from `_apply_honesty_gates` / `analyze_headline`):
  - (a) `confidence < 0.6` → forced `NO_SIGNAL`, both impact fields forced `NEUTRAL`.
  - (b) `surprise_score < 0.1` → both impact fields forced `NEUTRAL` (independent of (a); confidence
    field itself is untouched).
  - (c) `calibration_status` always `"uncalibrated"` (not a value gate, just an honest label).
  - (d) lookahead: `min_publication_age_hours=2.0`, reused from `news_sentiment.select_eligible_headlines`.
  - (e) no `historical_matches` field anywhere.
- Mocked tests patch `requests.post` at the same call site production uses — the code path (prompt,
  parsing, gate logic) is identical between mock and live. Any divergence found here is about whether
  real Claude output matches the *values* the mocks hardcoded, not a code-path mismatch.
- No production caller wires this module to anything yet (`live_scheduler`, `app.py` — zero references
  outside the module and its test file). Nothing to isolate from in that sense; noted for Step 6.

## Selected headlines (verbatim, as returned by the pipeline — no hand-picking)

Fetch timestamp (UTC): `2026-07-28T12:28:58.664345+00:00`
Source call: `NewsFeedClient().load("GOLD", limit=12)` → status `live (78 matched)`, top 5 taken in
pipeline-returned order. Headline #5 was dropped from the analysis set (see below) because it failed
the lookahead-eligibility parse, leaving 4 headlines actually sent to Claude.

| # | Headline | Source | Published (raw) | Age at fetch (h) | Eligible (>=2h)? |
|---|---|---|---|---|---|
| 1 | As the U.S.-Iran war heats up again, these parts of the stock market and economy could be affected | CNBC | Tue, 21 Jul 2026 14:37:08 GMT | 165.86 | Yes |
| 2 | Fed Chairman Kevin Warsh's testimony to Senate banking committee hits on economy, interest rates | CNBC | Wed, 15 Jul 2026 22:05:14 GMT | 302.40 | Yes |
| 3 | Odds of Federal Reserve rate hike surge as oil prices rip higher | CNBC | Thu, 23 Jul 2026 20:25:28 GMT | 112.06 | Yes |
| 4 | 'WarshGPT': How Wall Street is adapting to the Fed's new era of communication | CNBC | Sat, 18 Jul 2026 18:16:42 GMT | 234.20 | Yes |
| 5 (excluded) | Gold prices today, Tuesday, July 28, 2026: Gold remains below $4,100 ahead of Fed meeting | Yahoo Finance | `2026-07-28T11:40:31Z` (ISO8601, not RFC822) | n/a — unparseable | No (parse failure -> conservatively excluded) |

**Finding, recorded now (not after seeing results):** `parse_published` uses `email.utils.parsedate_to_datetime`,
which only accepts RFC822-style dates. Yahoo Finance's feed returns ISO8601 pubDates. Every Yahoo Finance
headline will silently fail the lookahead-eligibility check and be excluded, regardless of true age. This
is fail-safe (never creates a lookahead leak) but means the signal is effectively blind to one of its five
configured RSS sources. This is a pre-existing bug in `news_sentiment.py` (shared, not reimplemented by the
LLM variant) — out of scope to fix under this validation task, flagged for a follow-up.

## Predictions (written before any Claude API call)

1. **"As the U.S.-Iran war heats up again..."** — Predict confidence **below** 0.6 (gate a fires ->
   NO_SIGNAL). Reasoning: hedged/analytical framing ("could be affected") rather than a concrete
   directional claim, and "heats up **again**" signals continuation of already-known tension rather than
   a fresh discrete event, which should suppress both confidence and surprise in a careful model.
   Fallback expectation if gate (a) does NOT fire: BULLISH gold (safe-haven), ambiguous/NEUTRAL btc.

2. **"Fed Chairman Kevin Warsh's testimony... hits on economy, interest rates"** — Predict confidence
   **below** 0.6 (gate a fires -> NO_SIGNAL), highest-confidence prediction of the four. Reasoning: the
   headline reports only that testimony *occurred* and *touched on* topics — it contains zero directional
   content (no stated hawkish/dovish outcome). A model reasoning honestly should not be able to assign
   >0.6 confidence to a directional read of a title with no directional information.

3. **"Odds of Federal Reserve rate hike surge as oil prices rip higher"** — Predict confidence **at or
   above** 0.6 and surprise_score **at or above** 0.1 (both gates clear -> SIGNAL). Predict direction
   BEARISH for both gold and BTC. Reasoning: concrete, discrete, strongly-worded move ("surge", "rip
   higher") with a clear macro mechanism (higher rate-hike odds -> higher real yields -> bearish for
   non-yielding gold; tighter-liquidity expectation -> risk-off -> bearish BTC).

4. **"'WarshGPT': How Wall Street is adapting to the Fed's new era of communication"** — Predict
   confidence **below** 0.6 (gate a fires -> NO_SIGNAL). Reasoning: soft/feature-style story about
   communication style, not a market-moving data point or policy action; no directional economic content.

**Prior on overall run:** 3 of 4 predicted NO_SIGNAL via gate (a), 1 of 4 predicted a clean SIGNAL
(bearish/bearish). If the actual run instead fires the surprise gate (b) somewhere I did not predict it,
or clears gate (a) on headlines 1/2/4, that is a genuine miss of my prediction and will be reported as
such, not smoothed over.

## Live run execution notes

- Evaluation timestamp (`now`, used for both runs' `publication_age_hours`): `2026-07-28T12:33:34.347485+00:00`.
- 4 headlines x 2 passes = 8 real calls to `https://api.anthropic.com/v1/messages`, all HTTP 200. Zero
  network errors, zero timeouts, zero rate limits -> zero retries triggered (retry logic only engages on
  `requests.RequestException` subclasses, per the task's API-error-only retry rule; it was never invoked).
- Temperature: confirmed not present in the outgoing request body (checked the raw JSON sent, matches
  `_call_claude`'s literal `json={...}` dict — no `temperature` key). The Anthropic API default applied.
  This means the two runs are a genuine repeat-run stability check, not a redundant no-op.
- **API key confirmation**: the runner script asserted, after writing results to disk, that the literal key
  string does not appear anywhere in the output file. It also never appears in this document (nothing below
  is copied from request headers — only response bodies, which never echo the key, are quoted).

## THE key finding: a parsing bug the mocks cannot see

Headline #2 ("Fed Chairman Kevin Warsh's testimony...") produced `source: "error: KeyError"` in **both**
run 1 and run 2 — reasoning field: `"Claude API call failed: KeyError: 'text'"`.

Root cause (from the raw HTTP capture, preserved below): `claude-sonnet-5` returned a **thinking content
block first** in the `content` array for this headline in both runs (extended thinking activated
dynamically — the other 3 headlines never triggered it and returned plain text-only content arrays).
Production's `_call_claude` does:
```python
text = payload["content"][0]["text"].strip()
```
This unconditionally assumes `content[0]` is the text block. When a thinking block is emitted first,
`content[0]` has keys `{"type": "thinking", "thinking": ..., "signature": ...}` — no `"text"` key — so the
indexing raises `KeyError: 'text'` before the model's actual JSON answer (if any) is ever read, even in
run 2 where a genuine (truncated) text block *was* present at `content[1]`.

**This is exactly the mock/live divergence the task asked me to surface.** Every mocked test builds its
fake response as `{"content": [{"text": json.dumps(payload)}]}` (see `_mock_response` in
`test_news_sentiment_llm.py`) — a single content block, always type `text`, always at index 0. That
assumption is baked into every existing test and is **violated by the real API** whenever extended
thinking emits a leading thinking block. The mocks cannot catch this because they never model a
multi-block, thinking-first content array. All existing "malformed JSON" tests exercise
`json.JSONDecodeError`, not this `KeyError` path — so this specific failure mode has zero test coverage
today.

Consequence for this run: headline #2 got `NEUTRAL`/`NEUTRAL`, `confidence=0.0`, `surprise_score=0.0`,
`signal_type=NO_SIGNAL` in both passes — but **not because Claude judged the headline low-confidence**.
The model's real read was never obtained. The downstream NO_SIGNAL is coincidentally the same *label* my
prediction expected, but for a completely different and much worse reason (a crash, not an honest
low-confidence read) — see the Results vs Predictions table below, where this is marked DIVERGE on
mechanism despite matching on surface label.

This finding is independent of, and does not require, any temperature change — it is a structural
indexing assumption that any thinking-capable response can violate at any temperature.

## Full structured output — Run 1

| Headline | confidence | surprise_score | impact_gold (raw) | impact_btc (raw) | gate fired | signal_type | source |
|---|---|---|---|---|---|---|---|
| 1. US-Iran war | 0.45 | 0.3 | BULLISH | NEUTRAL | (a) confidence<0.6 | NO_SIGNAL | claude |
| 2. Warsh testimony | 0.0 | 0.0 | n/a — crashed | n/a — crashed | n/a (KeyError before gates ran) | NO_SIGNAL | error: KeyError |
| 3. Rate hike odds surge | 0.55 | 0.5 | BEARISH | BEARISH | (a) confidence<0.6 | NO_SIGNAL | claude |
| 4. WarshGPT feature | 0.2 | 0.1 | NEUTRAL | NEUTRAL | (a) confidence<0.6 | NO_SIGNAL | claude |

Note: "impact_gold/btc (raw)" is the model's pre-gate read, taken from the raw HTTP response body (not
the gated `HeadlineAnalysis.impact_on_gold/btc`, which gate (a) forces to NEUTRAL in rows 1/3/4 since all
three landed under the 0.6 confidence gate). Post-gate, **every single headline in run 1 published
NEUTRAL/NEUTRAL** — the gate suppressed all three real reads plus the one crash.

## Full structured output — Run 2

| Headline | confidence | surprise_score | impact_gold (raw) | impact_btc (raw) | gate fired | signal_type | source |
|---|---|---|---|---|---|---|---|
| 1. US-Iran war | 0.45 | 0.35 | BULLISH | NEUTRAL | (a) confidence<0.6 | NO_SIGNAL | claude |
| 2. Warsh testimony | 0.0 | 0.0 | n/a — crashed | n/a — crashed | n/a (KeyError before gates ran) | NO_SIGNAL | error: KeyError |
| 3. Rate hike odds surge | 0.55 | 0.5 | BEARISH | BEARISH | (a) confidence<0.6 | NO_SIGNAL | claude |
| 4. WarshGPT feature | 0.2 | 0.1 | NEUTRAL | NEUTRAL | (a) confidence<0.6 | NO_SIGNAL | claude |

## Run 1 vs Run 2 stability

| Headline | confidence (r1 -> r2) | surprise (r1 -> r2) | raw gold (r1 -> r2) | raw btc (r1 -> r2) |
|---|---|---|---|---|
| 1. US-Iran war | 0.45 -> 0.45 (stable) | 0.3 -> 0.35 (minor drift) | BULLISH -> BULLISH | NEUTRAL -> NEUTRAL |
| 2. Warsh testimony | crash both times (KeyError) | crash both times | crash both times | crash both times |
| 3. Rate hike odds surge | 0.55 -> 0.55 (stable) | 0.5 -> 0.5 (stable) | BEARISH -> BEARISH | BEARISH -> BEARISH |
| 4. WarshGPT feature | 0.2 -> 0.2 (stable) | 0.1 -> 0.1 (stable) | NEUTRAL -> NEUTRAL | NEUTRAL -> NEUTRAL |

At default (unset) temperature, directional reads and confidence were highly stable across the two runs
for the 3 headlines that didn't crash — only a small surprise_score drift on headline 1 (0.3 vs 0.35,
same side of the 0.1 gate either way). The KeyError crash was also perfectly stable — it reproduced both
times, consistent with it being a structural bug rather than a one-off fluke. This is a 2-run, 4-headline
sample; it establishes short-run stability under these exact headlines, not general calibration.

## Results vs Predictions

| # | Predicted | Actual | Verdict |
|---|---|---|---|
| 1. US-Iran war | Gate (a) fires (confidence <0.6) -> NO_SIGNAL | Gate (a) fired, confidence 0.45/0.45 -> NO_SIGNAL | **MATCH** |
| 2. Warsh testimony | Gate (a) fires (confidence <0.6) -> NO_SIGNAL, via an honest low-confidence read | Ended as NO_SIGNAL, but via a `KeyError` crash before any gate logic ran — the model's confidence read was never obtained | **DIVERGE on mechanism** (label coincidentally matches; the predicted *reasoning path* did not occur — see write-up above) |
| 3. Rate hike odds surge | Both gates clear -> SIGNAL, BEARISH/BEARISH | Raw read was BEARISH/BEARISH as predicted, but confidence landed at 0.55 — **below** the 0.6 gate by a margin of 0.05 -> gate (a) fired -> NO_SIGNAL | **DIVERGE** — my prediction of the *direction* was right, but I was wrong that confidence would clear 0.6. The mock's assumption in `test_confidence_exactly_at_gate_boundary_is_not_gated` (that a clearly-directional, concretely-worded headline produces confidence >=0.6) is not something the real model reliably does — a strongly-worded, mechanistically-clear headline still got a middling 0.55 both times. |
| 4. WarshGPT feature | Gate (a) fires (confidence <0.6) -> NO_SIGNAL | Gate (a) fired, confidence 0.2/0.2 -> NO_SIGNAL | **MATCH** |

**2 of 4 matched, 2 of 4 diverged** (one on mechanism, one on confidence calibration). Both divergences
point the same direction: the mocks encode assumptions (fixed content-block shape; "clear" headlines clear
the confidence gate) that the live model does not honor. Neither divergence was resolved by adjusting the
prediction after the fact — both are reported as originally predicted vs. what actually happened.

**Was the gate logic actually exercised?** Partially. Gate (a) (confidence) fired 3 of 4 times and is
well-exercised. Gate (b) (surprise) was **never triggered** in this run — every raw surprise_score that
reached the gate check (headlines 1, 3, 4) was already at or above 0.1, and headline 2 never reached the
gate check at all due to the crash. So this run validates gate (a) and the crash path, but does **not**
exercise gate (b) even once — a clean absence of low-surprise readings here is not evidence gate (b)
works, only that these 4 headlines didn't test it.

## Step 6 — Sanity checks

- **No writes to live scheduler config or strategy registry**: `git status --short` after the full run
  shows zero modifications to any tracked file (only the same pre-existing untracked local utility scripts
  the user asked to leave alone remain listed; those predate and are unrelated to this task). `git diff
  --stat` is empty. `register_llm_variant`/`register_default_variant` were never called by the runner
  script. Confirmed by inspection of the script (no call site) and by the empty diff.
- **No lookahead**: `_call_claude`'s prompt (see `news_sentiment_llm.py`) contains only the headline text
  string — no price data, no subsequent-candle data, nothing beyond the headline itself is passed to
  Claude. `analyze_headline` separately computes `publication_age_hours` from the headline's own RFC822
  `pubDate` (via the shared `parse_published`), never from price history. All 4 analyzed headlines were
  >=2h old at evaluation time (112h-302h), satisfying the lookahead buffer with wide margin.
- **Token usage / cost**: 8 real calls total (4 headlines x 2 runs). Total input tokens: 2,728. Total
  output tokens: 1,984 (of which 694 were "thinking" tokens — 400 wasted entirely on the crashed headline
  in run 1, 294 in run 2). Total tokens: 4,712. All calls used `claude-sonnet-5`, `max_tokens=400` per
  call as configured in `LLMNewsParameters`.

## What this run does NOT establish

- This is a 4-headline, 2-run sample. It validates plumbing (does the call path work end-to-end against
  the real API) and surfaces one reproducible structural bug — it does not validate calibration. No Brier
  score or resolved-prediction accuracy claim is made or implied anywhere in this document.
- Gate (b) (surprise) was never exercised — this run says nothing about whether that gate behaves
  correctly under real low-surprise headlines.
- The KeyError bug was reproduced twice for one specific headline; it has not been tested across a larger
  sample to determine how often extended thinking activates in general, nor whether raising `max_tokens`
  or restructuring the parse (search `content` for the block with `type == "text"` instead of indexing
  `[0]`) would fully resolve it. That is a fix for a future task, not something applied here — this task's
  scope was validation, not remediation, and the instructions were explicit that the production code path
  must not be modified for this run.
- Confidence/surprise stability was checked over 2 runs only; this bounds short-run noise, not long-run
  drift or seasonality in the model's behavior.

## Bugs Found and Fixed (follow-up, same branch)

The two bugs surfaced by this validation were fixed in two follow-up commits on this same branch. This
section is appended after the fact; the run results and predictions above are left exactly as originally
recorded — nothing above this section was reworded or softened.

- **Bug 1 — content-block parsing crash**, fixed in commit `bc7945f` ("Fix content-block parsing crash in
  LLM news sentiment (Bug 1)"). `_call_claude` indexed `payload["content"][0]["text"]` unconditionally;
  a `type: "thinking"` block preceding the text block (as captured live above) raised `KeyError`, and a
  non-list `content` value would have raised an uncaught `TypeError` clean past all error handling. Fixed
  by scanning the whole `content` array for `type == "text"` blocks (concatenating if more than one is
  present) instead of indexing positionally. The regression tests replay the exact captured live shapes
  from this document (thinking-only, and thinking-then-truncated-text) plus reconstructed edge cases
  (multiple text blocks, a block missing its `type` key, non-list content). Full trace and repo-wide
  pattern search were done before fixing — see the commit message for both.
- **Bug 2 — RSS timestamp parsing gap**, fixed in commit `2a6b02f` ("Add ISO8601 fallback to
  parse_published (Bug 2)"). `parse_published` only tried RFC822; Yahoo Finance's ISO8601 pubDates (see
  the excluded headline #5 above) were silently treated as unparseable and excluded regardless of true
  age. Fixed by falling back to `datetime.fromisoformat()` when RFC822 fails, with an explicit,
  documented rule for naive (zone-less) ISO8601 timestamps: excluded, not assumed UTC, since a wrong zone
  guess risks a lookahead leak rather than just a missed headline. A live re-check of all 5 configured
  sources found CNBC and CoinDesk both RFC822 (unaffected), Yahoo ISO8601 (confirmed affected), and
  Reuters / MarketWatch Economy unreachable at check time (DNS failure / 403 respectively) — their
  timestamp format remains unconfirmed, which is a separate, pre-existing connectivity gap, not part of
  this fix.

Both fixes were written test-first (regression tests confirmed failing against the pre-fix code before
either fix was applied) and verified against the full test suite: 1487 tests passing before, 1502 passing
after (15 new tests, 0 regressions, 0 failures either side beyond a pre-existing test that deliberately
mocks an `OSError` to exercise error handling).

Neither fix touches gate (b) (surprise_score) or extends live API validation — this document's "What this
run does NOT establish" section above still applies unchanged.
