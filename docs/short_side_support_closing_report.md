# feature/short-side-support -- Closing Report

Implements exactly what `feature/short-side-investigation`'s report
(`docs/short_side_investigation_report.md`) scoped: bidirectional (short-side)
support for the research-agent `auto_tester` engine, end to end, applied to
resolve the two previously-UNTESTABLE external candidates to a real, final
verdict. This closes the external-candidates chapter completely.

## 1. The consolidated 5-candidate table -- FINAL

| Candidate | Final status |
|---|---|
| `EXT_WISE_MAN_HOLD_V5_ETH_4H` | **DIED** (confirmed independently) |
| `EXT_WISE_MAN_HOLD_V6_EURUSD_4H` | **TOO_SLOW** (data-source divergence) |
| `EXT_WISE_MAN_HOLD_V5_EURUSD_4H` | **TOO_SLOW** (data-source divergence) |
| `EXT_ADX_RANGE_V3_BTC_1D` | **TOO_SLOW** (real verdict, see below) |
| `EXT_ADX_RANGE_V4_BTC_1D` | **TOO_SLOW** (real verdict, see below) |

The 3 `EXT_WISE_MAN_HOLD_*` rows are unchanged from
`feature/external-candidates-formal-test`'s own recorded results
(`docs/external_candidates_formal_test_results.json`) -- not re-run for this
branch (out of Task 4's scope, and each carries a slow live grid-shift
re-fetch not worth re-paying for no reason); this branch's own backward-
compatibility proof (Section 3) separately confirms the code that WOULD
produce these values still produces them byte-for-byte.

### EXT_ADX_RANGE_V3_BTC_1D / EXT_ADX_RANGE_V4_BTC_1D -- the real result

Both candidates were run for the first time ever (previously UNTESTABLE, a
genuine engine capability gap, not a data problem) against Vatican's own
live, current Binance BTCUSDT daily history, through the full pipeline:
frequency_gate -> auto_tester -> bootstrap CI -> bidirectional random-entry
baseline. Grid-shift was correctly NOT run for either (see Section 2's
grid-shift note) -- `run_grid_shift=False` was passed explicitly, not
silently skipped.

Both came back **SKIPPED at the frequency gate**, classified **TOO_SLOW**:

```
EXT_ADX_RANGE_V3_BTC_1D: Bidirectional: long 45 trigger(s) + short 61
trigger(s) = 106 combined over 3270 eligible days (11.84 trades/year) ->
~30.4 months to 30 resolved trades -> TOO_SLOW.

EXT_ADX_RANGE_V4_BTC_1D: Bidirectional: long 61 trigger(s) + short 95
trigger(s) = 156 combined over 3270 eligible days (17.42 trades/year) ->
~20.7 months to 30 resolved trades -> TOO_SLOW.
```

This is a REAL, honest classification, not a fabricated SURVIVED/DIED to
satisfy a "give it a real verdict" instruction -- it is exactly what the
CLAUDE.md-level discipline this project runs under requires (honest null
over invented numbers). Neither candidate's backtest/bootstrap-CI/random-
baseline stage ever ran, because they never cleared the frequency gate --
the gate rejected both BEFORE reaching the part of the pipeline this
branch's own code changes touch. This is not a failure of the bidirectional
engine; it is BTC's own daily candle history being short (Binance's BTCUSDT
1d series is only 3271 candles, ~9 years) combined with a genuinely rare ADX
range-bound setup, even after this branch doubled the effective sample size
by adding the short side (combining long+short triggers under one shared ADX
gate, per the frequency-combining design in Section 2). The bidirectional
engine did its job correctly; the underlying setup is simply too infrequent
on native daily bars to resolve to a trustworthy trade sample within this
project's own frequency-gate discipline.

## 2. Design decision: the direction-declaration mechanism (Task 1)

**Chosen**: `hypothesis["structured_entry_rule_short"]` -- an OPTIONAL,
independently-parsed second `StructuredRule`, alongside the always-required
`structured_entry_rule` (now implicitly the LONG rule). A hypothesis becomes
bidirectional purely by this second key's PRESENCE; there is no separate
`is_bidirectional` flag to fall out of sync with it -- the same
presence-implies-feature convention `ExitPlan.regime_break_condition`/
`regime_break_consecutive_bars` already uses in this same module.
`nero_core.research_agent.rule_dsl.parse_bidirectional_entry_rules(hypothesis)`
is the ONE place both rules are read off the dict (matching this module's own
pre-existing charter: "the ONE place `entry_rule` is parsed," so
`frequency_gate.py` and `auto_tester.py` can never silently diverge on what a
hypothesis's rule(s) even are).

A second, small piece completes the design: `rule_dsl.mirror_condition`,
which flips an `ExitPlan.dynamic_target_condition`'s comparison operator
(`gt<->lt`, `gte<->lte`, `cross_above<->cross_below`, `eq` unchanged) so a
hypothesis authors exactly ONE dynamic-target condition (implicitly
LONG-shaped, matching every existing hypothesis exactly) and a SHORT trade's
exit evaluator mirrors it rather than requiring a second, separately-authored
condition. `ExitPlan.regime_break_condition` is deliberately NEVER mirrored
-- it describes a market-REGIME observation (e.g. "ADX >= 28"), not a
price-vs-entry relationship, so it fires identically for both directions
(confirmed directly against `range_mean_reversion.evaluate_exit`, which
checks its own regime-break condition identically for LONG and SHORT).

**Criteria used**: (a) consistency with DSL conventions -- both pieces reuse
an existing convention already live in this exact module rather than
inventing a new one; (b) minimal footprint -- `StructuredRule`/`Condition`
themselves are completely unchanged, no new DSL surface at the condition
level; (c) backward compatibility -- every hypothesis before this branch has
exactly one key (`structured_entry_rule`) and nothing else, so
`parse_bidirectional_entry_rules` returns `(that_same_rule, None)` for every
one of them, byte-for-byte what `parse_structured_rule` alone always
produced.

**Rejected alternative 1**: a `direction` sub-field on individual `Condition`
entries within one ANDed list. Rejected -- breaks `StructuredRule`'s clean
"every condition ANDed together" contract by requiring OR-like
special-casing inside what is currently a pure AND; a rule like EXT_ADX_
RANGE's ("long iff close < bb_lower, short iff close > bb_upper, under a
shared ADX gate") cannot be expressed as one ANDed list with per-condition
directions without changing what AND means.

**Rejected alternative 2**: a single rule plus an auto-inferred "mirror
rule" for the opposite direction (e.g. auto-flip `rsi14 < 30` to `rsi14 >
70`). Rejected -- auto-inferring the short version of an arbitrary condition
would be a GUESS (there is no unambiguous mirror for every condition shape:
what is the "short mirror" of `adx14 < 25`, a regime-strength gate with no
inherent direction at all?), directly violating `rule_dsl.py`'s own
Requirement 1 ("never guess a substitute" -- unsupported shapes must raise
`RuleAmbiguousError`, never silently fall back to a guessed interpretation).

## 3. Backward-compatibility proof (Task 3, the hard merge gate)

**Methodology**: frozen-candle snapshots (`tests/fixtures/frozen_candles/
{BTC,ETH,EURUSD}_4h.json`) were captured ONCE, before any Task 2 code change,
from live data. A detached git worktree checked out at this branch's
pre-Task-2 commit ran 5 spot-check hypotheses (`WISE_MAN_HOLD_V1`,
`ADX_RANGE_V4` from the native graveyard; `EXT_WISE_MAN_HOLD_V5_ETH_4H`,
`EXT_WISE_MAN_HOLD_V6_EURUSD_4H`, `EXT_WISE_MAN_HOLD_V5_EURUSD_4H` from the
external set) against those frozen candles through the genuinely OLD code --
recorded to `tests/fixtures/frozen_candles/backward_compat_baseline_before.
json`, now committed as the recorded golden fixture.
`tests/test_short_side_support_backward_compat.py` re-runs the SAME 5
hypotheses against the SAME frozen candles through the CURRENT (post-Task-2)
code and asserts `assertEqual`-exact equality against those recorded values
-- not a re-run-and-eyeball comparison, and not a same-run comparison (the
"before" values were computed from actually-different, pre-Task-2 source, via
a separate worktree, before this branch's implementation existed).

**Result**: all 5 cases' `result` field (frequency gate + backtest +
bootstrap CI + random-entry baseline -- everything this branch's own code
changes touch) is byte-for-byte identical, proven with a real `assertEqual`
test, not eyeballed similarity.

**A real finding, investigated and resolved, not swept under the rug**: an
early live diff-before-after run (before the committed proof above existed)
surfaced ONE divergence, confined to a single grid-shift offset variant for
one case's `random_baseline`/frequency numbers. Root cause: `run_hypothesis_
live`'s grid-shift re-run (`build_4h_grids` -> `fetch_hourly_for_grid` ->
`client.load_intraday`) performs its OWN independent, LIVE, unfrozen network
fetch every time it runs, completely bypassing the frozen `candles` argument
-- a pre-existing property of `tools/philosophy_hypotheses_live_test.py`
(confirmed unmodified by this branch via `git diff` against this branch's own
merge-base with `main`, zero output), not a code regression. The two live
runs (started ~25 minutes apart) simply saw slightly different live hourly
data for that one resample, which is why `verdict`/`review_status`/
`frequency_classification`/`reason`/the underlying `train`/`test` trade lists
were UNAFFECTED even in the one offset that showed drift -- only the
random-baseline's own numeric draws (which sample from a pool whose
composition depends on that live-fetched data) shifted slightly. The
committed proof test therefore calls `run_hypothesis_live(..., run_grid_
shift=False)`: it proves exactly the part of the pipeline this branch
changed, and does not fabricate a false byte-equality claim over a sub-step
that was never frozen to begin with. This is documented in the test file's
own module docstring, not just here.

**A real regression, found and fixed during this work**: an early version of
`mean_reversion.evaluate_exit` read `trade.direction` via direct attribute
access. `evaluate_exit` is duck-typed-reused (not via `mean_reversion`'s own
`OpenTrade` class) by roughly a dozen OTHER strategies' own locally-defined
`OpenTrade`-shaped dataclasses (`breakout_momentum.py`, `trend_pullback.py`,
`volatility_squeeze.py`, `leadlag_follow.py`, and others), none of which
carry a `direction` field -- the direct access broke every one of them
(`AttributeError`) the moment this branch's implementation landed, caught by
the full regression suite (37 errors). Fixed by reading `direction` via
`getattr(trade, "direction", "LONG")` instead -- every existing caller's
long-only behavior is completely unchanged (the full suite was re-run and
confirmed clean, 1871/1871, before proceeding). This is exactly the kind of
finding Task 2's own instruction anticipated ("if the investigation's
direction-agnostic-already finding turns out wrong once implementing against
real code, STOP and report") -- it wasn't about `frequency_gate`/bootstrap
CI/grid-shift/cost model (those genuinely needed zero changes, confirmed),
but about a shared-reuse surface the original investigation didn't scope
into, found and fixed rather than silently expanding scope elsewhere.

`range_mean_reversion.py`/`short_momentum.py`'s own production behavior:
provably untouched. `git diff <merge-base-with-main> -- nero_core/strategies/
range_mean_reversion.py nero_core/strategies/short_momentum.py` is empty --
proven with an `assertEqual("", diff)` test
(`UntouchedProductionStrategiesTest`), not asserted from memory. Neither
strategy goes through `auto_tester` today, and this branch's own new code
imports nothing beyond the one PRE-EXISTING (unrelated to this branch) pure
`range_mean_reversion.adx()` indicator reuse -- proven via an `ast`-based
import-statement check (not a source-text substring search, which would
false-positive on this module's own prose references to
`range_mean_reversion.evaluate_exit`).

## 4. Zero auto-wiring, confirmed

`tests/test_research_agent_no_auto_wire.py` -- ZERO modification to its own
assertions (`git diff HEAD` on that file is empty). All 3 of its tests still
pass: the static AST-walk proving no research-agent source file imports
`live_scheduler`/`default_registry`, and the dynamic full-pipeline-run proof
that the strategy registry is never mutated by a real run -- verified AFTER
this branch's real code changes landed, not assumed.

## 5. Full regression

The entire pre-existing test suite passes unchanged: 1871/1871 (before this
branch's own new test files are added). With this branch's 3 new test files
(`test_short_side_support_backward_compat.py`,
`test_research_agent_rule_dsl_direction.py`,
`test_research_agent_auto_tester_direction.py` -- 39 new tests covering
direction-declaration parsing, `mirror_condition` completeness over every
`ALLOWED_OPS` value, short-side entry sizing (stop/target mirroring,
sell/buy slippage side), short-side exit evaluation (stop/target hit
mirroring, dynamic-target mirroring, regime-break NON-mirroring, gross_pnl
sign correctness for both a short profit and a short loss), `run_backtest`'s
long-checked-first mutual exclusivity, `_half_stats`' bidirectional-baseline
wiring (spied, not inferred), and `_measure_frequency_for_hypothesis`'s
combining/UNMEASURABLE-propagation logic), the full suite is 1910/1910.

## 6. Explicit backlog note (flagged, not built)

`nero_core/research_agent/hypothesis_gen.py` is completely untouched by this
branch (`git diff` against both `HEAD` and this branch's merge-base with
`main` is empty) and its LLM prompts still only ever propose LONG-only
hypotheses. Teaching the LLM to propose direction-aware (bidirectional)
hypotheses -- prompt changes, schema changes to accept a genuinely
LLM-authored short rule, and the anti-p-hacking discipline that would need to
govern it -- is explicitly OUT OF SCOPE for this branch and is filed here as
future backlog, not attempted.

## 7. Merge readiness

This branch is ready for CC-1 to review and merge, pending that review --
NOT merged to `main` by this work. Every task (1-6) is complete: the design
is documented with its 2 rejected alternatives, the implementation is
backward-compatible (proven, not asserted), the 2 previously-UNTESTABLE
candidates now have a real, honest final verdict, the full regression suite
plus 39 new dedicated tests all pass, the no-auto-wire guarantee holds
unmodified, and the one explicit scope boundary (hypothesis_gen.py) is
flagged rather than silently expanded into.
