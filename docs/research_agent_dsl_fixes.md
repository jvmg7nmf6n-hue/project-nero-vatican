# Research Agent — DSL Fixes + Missing Auth Entrypoint (2026-07-30)

Follow-up to `docs/research_agent_real_run_followup.md`, which reported (but
did not fix) two DSL-narrowness findings and a missing auth-path entrypoint.
Per the user's instruction, all three are now fixed, not just documented.

## Fix 1 — RSI added to the allowed-field list

`rule_dsl.ALLOWED_FIELDS` now includes `rsi14`, computed in
`compute_indicator_frame` by reusing `nero_core.strategies.mean_reversion.rsi`
unchanged (MEAN_REVERSION's own indicator, not re-derived), then re-masking
the leading `RSI_PERIOD + 1` rows back to `NaN`: that function's own
`.fillna(100.0)` is correct for its own caller (a genuine "no losses in this
window" reading legitimately IS RSI 100), but during warmup — before enough
closes exist for a real reading — it would otherwise fabricate a 100.0
indistinguishable from a genuine extreme reading. Verified this masking is
exactly right (not an off-by-one guess) via `close.rolling(15).count() >= 15`,
confirmed empirically before writing the fix.

**Live re-confirmation against real data** (no LLM, $0 cost):
```
TSLA/1day rsi14<30: classification=TOO_SLOW triggers=8 trades/yr=10.0
```
Previously this exact rule was rejected `UNMEASURABLE` ("unsupported field
'rsi14'"). It is now genuinely measured — TOO_SLOW here is a real result on
real data, not an ambiguity rejection.

## Fix 2 — field-vs-field comparison

`Condition` now takes either a fixed `value` (a number) or a
`compare_to_field` (another `ALLOWED_FIELDS` name) — exactly one of the two.
`compare_to_field` must itself be an allowed field and must differ from
`field`. `evaluate_condition`'s `cross_above`/`cross_below` logic generalizes
cleanly: for a fixed `value`, `prev_threshold == threshold == condition.value`
(constant across rows), which reduces to the original single-level-crossing
check bit-for-bit; for a `compare_to_field`, each row uses its own threshold
(the other field's value at that row) — a genuine two-series crossover, e.g.
a moving-average golden cross:
```json
{"field": "ma50", "op": "cross_above", "compare_to_field": "ma200"}
```

**Live re-confirmation against real data**:
```
BTC/12h ma20 crosses above ma50:        classification=TOO_SLOW triggers=1  trades/yr=3.67
BTC/12h ma50 crosses above ma200 (golden cross): classification=TOO_SLOW triggers=0  trades/yr=0.0
```
Previously, no crossover-style hypothesis was expressible at all, regardless
of the field list's size. Both are now genuinely measured. (Both land
TOO_SLOW on 200 real candles — crossovers are inherently rare events; this is
an honest result, not evidence the fix doesn't work.)

The LLM prompt in `hypothesis_gen.py` was updated to actually tell the model
both capabilities exist (`rsi14` in the field list, `compare_to_field` usage
with a golden-cross example) — the fix would otherwise be invisible to a real
run.

## Fix 3 — the missing `ANTHROPIC_API_KEY` read

`pipeline.py` gained a `main()` CLI entrypoint (`python -m
nero_core.research_agent.pipeline`): `api_key = os.getenv("ANTHROPIC_API_KEY",
"")`, then `run_pipeline(api_key=api_key)` — matching
`nero_core.execution.live_scheduler.py`'s own `claude_key = os.getenv(
"ANTHROPIC_API_KEY", "")` pattern exactly. Every other function in this
package still takes `api_key` as an explicit parameter only, by design; this
is the one place that now reads the environment, so the pipeline can actually
run unattended (e.g. on GitHub Actions, where the key is valid) once this
merges.

`main()` prints only aggregate, non-secret counts (hypotheses generated,
cost, verdict breakdown) — never the key. The static "no print anywhere"
guard from the previous follow-up was refined accordingly: rather than
banning `print()` outright (which would have blocked this legitimate
entrypoint), it now checks — via `ast`, not a text scan — that no `print()`
call's arguments ever reference a credential-shaped identifier (`api_key`,
`secret`, `token`, `password`, `credential`), which is the actual risk the
2026-07-29 incident exposed. A dedicated test proves the check would still
catch a real offender.

## Tests

- `rule_dsl`: 14 new tests (RSI field allowed + warmup-masking + matches the
  reused `mean_reversion.rsi` after warmup; `compare_to_field` parsing —
  valid, both-set, neither-set, unsupported, self-referential; field-vs-field
  evaluation — `gt`, NaN-either-side, `cross_above`/`cross_below`, a full
  end-to-end MA20/MA50 crossover on a real `compute_indicator_frame`).
- `rule_dsl` consistency: 1 new test proving frequency_gate and auto_tester
  still agree on entry timestamps for a field-vs-field (MA crossover) rule,
  not just a field-vs-constant one.
- `hypothesis_gen`: 1 new test proving the prompt actually mentions `rsi14`
  and `compare_to_field`.
- `pipeline` (`main()`): 4 new tests — reads the env var and passes it
  through correctly, defaults to `""` when unset, never prints the key
  value, prints only the aggregate counts.
- `secret_handling`: replaced the blanket "no print anywhere" test with the
  precise credential-identifier-reference check described above, plus its
  own "would catch a real offender" sanity test.
- 3 pre-existing tests that used `rsi14` as their "genuinely unsupported
  field" example were updated to use `macd` (still unsupported) instead,
  since `rsi14` is now legitimately supported.

## Test counts (real, not asserted from memory)

Runner: `python -m unittest discover -s tests -p "test_*.py"`.

| | Count |
|---|---|
| Original baseline | 1538 |
| After the 7-task branch | 1633 |
| After the preflight follow-up | 1643 |
| After this DSL-fix follow-up | **1665** |
| New tests added this follow-up | 22 |
| Result | **OK** — 0 failures, 0 errors |

## Still unverified

- The real LLM call path itself remains unexercised against a genuinely
  valid key this session (unchanged from the previous follow-up) — the fixes
  above were verified via the frequency gate directly against real market
  data, not via a real hypothesis-generation run.
- Website Jest tests remain unverified (no Node.js in this environment).
