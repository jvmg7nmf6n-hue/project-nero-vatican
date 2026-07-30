# Research Agent — Real-Run Follow-Up (2026-07-30)

Follow-up to `docs/research_agent_closing_report.md`, after the user flagged
that the frequency gate — "the entire point of this agent" — had never seen a
real LLM-generated hypothesis, and asked for a real end-to-end run. Every
finding below is **CONFIRMED** (measured output shown inline) unless marked
**UNVERIFIED**.

## What actually happened, in order

1. Real pipeline run attempted with `ANTHROPIC_API_KEY` read from the
   environment (`os.environ.get`, never printed — presence/absence checked
   separately beforehand). **All 3 LLM calls returned `401 Unauthorized`.**
2. Diagnosed with a single cheap call (not the full budget) before reporting:
   confirmed 401, not a parsing/DSL issue.
3. User confirmed the likely cause: `ANTHROPIC_API_KEY` in this shell is the
   Claude Code harness's own session credential / a stale pre-rotation value
   never re-exported here, not a fresh key provisioned for direct `/v1/messages`
   calls. Per the user's own instruction, no alternate auth scheme was
   attempted — see the three tasks below instead.

## Task 1 — production auth path traced

`nero_core/execution/live_scheduler.py:746`:
```python
claude_key = os.getenv("ANTHROPIC_API_KEY", "")
...
llm_result = analyze_sentiment_llm(feed_result.headlines, asset, now, api_key=claude_key, params=NEWS_PARAMS_LLM)
```
confirmed against `.github/workflows/live_scheduler.yml`:
```yaml
ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```
So the production path is: `secrets.ANTHROPIC_API_KEY` → workflow env →
`os.getenv("ANTHROPIC_API_KEY", "")` → passed explicitly as `api_key=`.

`nero_core/research_agent/hypothesis_gen.py`'s `generate_hypotheses(..., api_key: str, ...)`
and `pipeline.py`'s `run_pipeline(api_key: str = "", ...)` take `api_key` as an
explicit parameter the exact same way `analyze_sentiment_llm` does — **no
variable-name mismatch, no bug in how the value would flow if handed in.**

**Real gap (not a bug):** no file under `nero_core/research_agent/` ever
calls `os.getenv("ANTHROPIC_API_KEY", ...)` itself. `live_scheduler.py` has
that read living inside the one function GitHub Actions actually invokes;
research_agent has no equivalent entrypoint yet — today, whoever calls
`run_pipeline` has to already have the key in hand (this session's own
diagnostic scripts did that manually, standing in for what a future scheduled
entrypoint would need to do). This was out of scope for what was asked
originally (no CI workflow for the research agent was requested) and is
flagged here, not built, pending a decision on whether/when to wire one.

## Task 2 — preflight key validation added

New: `hypothesis_gen.validate_api_key()` / `ApiKeyRejectedError`. Before the
per-finding loop, ONE minimal (`max_tokens=1`) call confirms the key is
accepted. On a genuine `401`, the run stops immediately with a single clear
error (`"ANTHROPIC_API_KEY is present but was rejected (401 Unauthorized)..."`)
instead of repeating the identical failure once per scan finding. Any other
outcome (200, a different error status, a network hiccup on the preflight
call itself) is **not** treated as fatal — it falls through to the normal
per-hypothesis handling, since only a 401 is guaranteed to repeat identically
on every subsequent call.

Verified against this exact incident: re-running the same failing key through
the new code path now makes **exactly 1 call** and reports 1 clear error,
where it previously made 3 (`test_401_stops_the_run_with_exactly_one_call_and_one_error`).
Skipped entirely when there's nothing that would need a call anyway (empty
key, or every finding already a known duplicate) so it never wastes a call
either. 10 new tests added (`ValidateApiKeyDirectTest`, `PreflightIntegrationTest`),
including one proving the key value never appears in the raised message.

## Task 3 — frequency gate against synthetic hypotheses over REAL market data

No LLM calls in this section — 5 hand-written hypotheses (shaped like
realistic LLM output, including the `structured_entry_rule`/
`structured_exit_plan` schema) run through the real `frequency_gate` +
`auto_tester` against the actual `docs/site_data/candles/` files. $0 cost.

| Hypothesis | Asset/TF | Measured trades/yr | Months to 30 | Classification | Harness verdict |
|---|---|---|---|---|---|
| SYN_FAST_BTC_ZSCORE (zscore20<-1.0) | BTC/12h | 216.6 | 1.7 | **FAST** | DIED (train N=17 ExpR=-0.520; test N=1 ExpR=1.421) |
| SYN_VIABLE_AMZN_DEEP_VALUE (zscore20<-1.5) | AMZN/1day | 31.3 | 11.5 | **VIABLE** | DIED (train N=8 ExpR=0.122; test N=6 ExpR=-0.070) |
| SYN_TOO_SLOW_GOLD_EXTREME (zscore20<-1.0) | GOLD/1week | 3.9 | 91.5 | **TOO_SLOW** | SKIPPED — never reached the harness |
| SYN_UNMEASURABLE_UNSUPPORTED_FIELD (rsi14<30) | TSLA/1day | — | — | **UNMEASURABLE** | SKIPPED — "unsupported field 'rsi14'" |
| SYN_UNMEASURABLE_FREE_TEXT_ONLY (entry_rule=null) | AMZN/1day | — | — | **UNMEASURABLE** | SKIPPED — "must be a dict with a 'conditions' list" |

The FAST and VIABLE hypotheses both DIED in the harness — expected and not a
gate/prompt problem: these were bare single-condition z-score triggers with
none of the confirming filters this project's real strategies use (trend
filter, RSI, frozen target). Passing the frequency gate was never meant to
imply an edge; it only means the harness gets a chance to check for one, and
here it correctly found none.

Live-confirmed (against real GOLD/1week data, not a synthetic fixture): the
TOO_SLOW hypothesis above never called `split_chronological` — `patch`+assert
showed `split_chronological called: False`.

### The single most valuable number: TOO_SLOW rejections

An earlier exploratory sweep (6 z-score thresholds × 6 real assets, still
$0/no LLM) found something sharper than any one hypothesis's result:
**every weekly-timeframe asset tested — USD/JPY, GOLD, SILVER — was TOO_SLOW
at literally every threshold from -0.5 to -3.0**, with no exception. Daily
(TSLA, AMZN) and 12h (BTC) assets spanned FAST → VIABLE → TOO_SLOW as the
threshold tightened, as expected. This independently reconfirms — from fresh
measurement, not restating the prior audit — the frozen design's own
founding claim: weekly-cadence configurations are structurally rate-limited
regardless of threshold tuning, and no prompt or gate change can fix that;
only a different timeframe can.

### Did the LLM follow the 20-30 trades/year instruction?

**UNVERIFIED — cannot be answered this run.** Zero real LLM calls succeeded
(all 3 attempts hit the 401 described above), so there is no
`expected_frequency_claim` from a real response to compare against a measured
value. This is the one question in the user's ask that flatly cannot be
answered without a working key. Flagging honestly rather than extrapolating
from the mocked-response unit tests, which only prove the *plumbing* handles
an `expected_frequency_claim` field correctly, not what a real model would
put in it.

### UNMEASURABLE — genuine ambiguity, or is the DSL too narrow?

**Both of today's UNMEASURABLE cases were genuinely ambiguous given the DSL
as built** — but the honest answer to "is the DSL too narrow" is **yes, in
two distinct ways**, reported here rather than fixed:

1. **The field allowlist excludes very common indicators.** `rsi14` isn't in
   `ALLOWED_FIELDS` (`close, ma20, ma50, ma200, zscore20, atr14, ret_1, volume`)
   — yet RSI is the primary signal in `MEAN_REVERSION`, the *first* strategy
   this whole project ported from the original NERO codebase. A field list
   that excludes the project's own oldest strategy's core indicator is
   narrower than it probably should be, by simple omission, not deliberate
   exclusion.

2. **A deeper, structural limitation (the more important of the two):** every
   `Condition.value` is a fixed numeric constant — `rule_dsl.py` has no way
   to express a comparison between two *fields* (e.g. "close below its own
   MA20", "MA50 crosses above MA200" — a golden cross). Adding `rsi14` to the
   allowlist would fix case 1 above, but would NOT fix this — no number of
   added fields helps, because the comparison model itself only supports
   `field <op> constant`, never `field <op> field`. This excludes an entire,
   very natural class of trading hypotheses (any moving-average relationship,
   which is arguably the single most common technical-analysis pattern)
   regardless of the field list's size.

Per instruction, **neither has been changed** — this is a report, not a fix.
Whether to extend the DSL (and how — a `field2` slot on `Condition`? a
ratio-of-two-fields helper field like `close_vs_ma20_pct`?) is left for the
user to decide.

## Actual API cost for this session's real-run attempt

**$0.00.** 3 real calls, all 401 (not billed). 1 additional diagnostic call
(also 401, also not billed). The synthetic hypothesis run in Task 3 made zero
LLM calls by design.

## Confirm: zero auto-wiring

Unchanged from the original closing report — no code touched here affects
`nero_core.execution.live_scheduler` or `nero_core.strategies.registry`;
both static (`ast`-based) and dynamic no-auto-wire tests still pass (see
below).

## Test counts (real, not asserted from memory)

Runner: `python -m unittest discover -s tests -p "test_*.py"`.

| | Count |
|---|---|
| Original baseline | 1538 |
| After the original 7-task branch | 1633 |
| After this follow-up (preflight + tests) | **1643** |
| New tests added this follow-up | 10 |
| Result | **OK** — 0 failures, 0 errors |

## Unverified / residual risk

- **Root cause of the 401 not fully resolved.** Most likely explanation per
  the user: this shell's `ANTHROPIC_API_KEY` is either the Claude Code
  harness's own session credential, or a pre-rotation value never re-exported
  here. Neither was tested directly (no alternate auth scheme was attempted,
  per instruction) — a genuinely fresh, exported key is needed to actually
  exercise the LLM call path end-to-end.
- **Whether the LLM follows the 20-30 trades/year instruction is completely
  unanswered** (see above) — the one question in this task that a working
  key is strictly required for.
- **Website Jest tests remain unverified** (Node.js still not installed in
  this environment) — unchanged from the original closing report.
- **DSL narrowness findings are reported, not acted on** — both are real and
  reproducible (shown above), and the fix (if any) is the user's call.
