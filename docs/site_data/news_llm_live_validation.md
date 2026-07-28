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

<!-- RESULTS APPENDED BELOW AFTER LIVE RUNS -->
