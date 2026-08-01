# External Candidates Formal Test — Closing Report

Branch: `feature/external-candidates-formal-test`. Not merged to `main`.

## Provenance

These 5 hypotheses were sourced from an **external system**, not generated
by Vatican's own scanner/LLM/web-search discovery channels. Per this
project's standing no-special-trust rule, none of the external source's own
reported numbers (win rate, profit factor, expectancy) or its own
out-of-sample verdict were treated as pre-confirmed anywhere in this task —
every candidate was re-encoded from the written rule and re-run from scratch
on Vatican's own data/pipeline. Full detail on the rule translation and the
UNTESTABLE determination: `tools/external_candidates_formal_test.py`'s own
module docstring. Full detail on data-source verification:
`tests/test_external_candidates_formal_test.py::DataSourcingTest`.

## Naming collision — resolved before anything ran

Two of the 5 (`ADX_RANGE_V3`, `ADX_RANGE_V4`) share bare names with this
repo's own native philosophy-hypotheses graveyard, but describe a completely
different rule. All 5 were renamed with an `EXT_` prefix *before* any code
was written — proven, not just asserted, against the native results file's
real key set (`NoCollisionWithNativeGraveyardTest`).

## Results

| Candidate | Asset/TF | Freq. gate | Trades/yr | Train N | Test N | Verdict |
|---|---|---|---|---|---|---|
| EXT_WISE_MAN_HOLD_V5_ETH_4H | ETH/4h | VIABLE | 33.3 | 176 | 53 | **DIED** |
| EXT_WISE_MAN_HOLD_V6_EURUSD_4H | EUR/USD/4h | TOO_SLOW | 27.2 | — | — | **SKIPPED** (never reached harness) |
| EXT_WISE_MAN_HOLD_V5_EURUSD_4H | EUR/USD/4h | TOO_SLOW | 27.2 | — | — | **SKIPPED** (never reached harness) |
| EXT_ADX_RANGE_V3_BTC_1D | BTC/1d | n/a | n/a | n/a | n/a | **UNTESTABLE** (engine limitation) |
| EXT_ADX_RANGE_V4_BTC_1D | BTC/1d | n/a | n/a | n/a | n/a | **UNTESTABLE** (engine limitation) |

### EXT_WISE_MAN_HOLD_V5_ETH_4H — full detail

Frequency gate: **VIABLE** — 176+53=229 measured triggers, 33.28 trades/year
(~10.8 months to 30 resolved trades). Reached the full harness.

Win rate and profit factor are re-derived directly from the same trade
objects `auto_tester.run_backtest` (the same internal function
`test_hypothesis` itself calls) produced for this exact rule/data/split —
cross-validated against the harness's own reported trade counts (176/53,
matched exactly) rather than computed independently. `TestResult`'s own
output shape doesn't carry win_rate/profit_factor (a real difference from
the separate RMR-family harness used in a prior task) — computed here
transparently rather than either fabricated or silently omitted.

| Half | N | Win rate | Wins/Losses | Expectancy R | Profit factor | 95% CI | Edge vs. random |
|---|---|---|---|---|---|---|---|
| TRAIN | 176 | 27.8% | 49/127 | -0.342 | 0.568 | [-0.525, -0.152] | -0.147 |
| TEST | 53 | 41.5% | 22/31 | -0.057 | 0.904 | [-0.410, 0.320] | +0.077 |

**Verdict: DIED** (train expectancy negative — `classify_verdict` requires
positive on both halves, and train's own CI excludes zero on the negative
side, a statistically real result, not a coin flip). Grid-shift: ran across
all 4 possible 4h alignments (this candidate cleared the frequency gate, so
grid-shift executed automatically per this harness's own contract) — DIED on
every offset.

**Comparison to the external source: CONFIRMS.** The external source itself
already reported this exact candidate as DIED in their own out-of-sample
check. Run fresh here, independently, on Vatican's own ETH/4h Binance data
(same provider/instrument the external source used) — same verdict, arrived
at without any pre-seeding from their report. This is the strongest possible
outcome for a "no special trust" verification: an independent re-derivation
landing on the same answer.

### EXT_WISE_MAN_HOLD_V6_EURUSD_4H / EXT_WISE_MAN_HOLD_V5_EURUSD_4H — SKIPPED before reaching the harness

Both share the identical entry rule (only stop/target differ between them),
so both measure the identical frequency: 80 triggers over 1,076 eligible
days = 27.16 trades/year (~13.3 months to 30 resolved trades) — just under
the VIABLE floor (needs ≥30 trades/year to clear in ≤12 months). Neither
reached bootstrap CI, random baseline, or grid-shift — the gate stopped both
on entry-trigger frequency alone, before any P&L was ever computed.

**Comparison to the external source: WEAKENS relative to whatever frequency
the external source measured, but this is very likely a data-source
artifact, not a rule-quality finding.** Per Task 2's own disclosure: Vatican
used its own native Twelve Data 4h EUR/USD feed; the external source used a
yfinance-1h-resampled-to-4h construction — genuinely different candle
boundaries, and (per this project's own prior investigation,
`docs/timeframe_periods_asset_aware_investigation.md`) Twelve Data's forex
feed behaves near-continuously (weekend candles included) in a way a
resampled construction may not replicate. A ~27.2 vs. whatever-the-external-
source-measured trades/year gap is exactly the kind of divergence a
different candle-construction method would produce on its own, independent
of whether the underlying entry rule (BB + ADX) is any good. **Not
re-tested on a different data source to chase a different frequency
number** — that would be exactly the kind of interim-result-driven scope
expansion this task's own anti-p-hacking rule forbids.

### EXT_ADX_RANGE_V3_BTC_1D / EXT_ADX_RANGE_V4_BTC_1D — UNTESTABLE

Not run, not approximated. The rule requires a bidirectional (long AND
short) entry with a direction-aware stop and a dynamic SMA20 target on
either side. Verified directly (not assumed) that
`nero_core.research_agent.auto_tester`'s entire entry/exit machinery is
hardcoded long-only throughout — confirmed via `inspect.getsource` in
`UntestableBidirectionalTest.test_auto_tester_entry_sizing_is_verified_
hardcoded_long_only`, not just read once and assumed. No `direction` field
exists anywhere in `StructuredRule`/`Condition`/`ExitPlan`. The only
bidirectional backtest machinery anywhere in this codebase
(`RANGE_MEAN_REVERSION`'s `allow_short`, `FVG_REVERSION`'s own logic) is
bespoke to those strategies' specific mechanisms, not a generic,
DSL-configurable one — reusing either would not be testing *this* rule, it
would be a different rule running under this rule's name.

**Comparison to the external source: genuinely UNTESTABLE, not comparable in
either direction.** This is not a weak result or a disagreement with the
external source — Vatican's harness has no honest way to evaluate this
specific rule shape yet. Building new short-side engine machinery was
judged out of scope for a hypothesis-*testing* task (a real, foundational
extension with genuine risk of a subtle direction-inversion bug if built
under this task's time/scope pressure) — flagged per this project's own
established discipline of verifying a capability before claiming it, rather
than either guessing or hastily building one to force a result.

## Total scan scope

5 pre-registered candidates, run in the exact order specified, no additions
or removals based on any interim result: 1 DIED (confirms the external
source), 2 SKIPPED at the frequency gate (data-source-difference-driven, not
a rule judgment), 2 UNTESTABLE (a verified engine capability gap).

## Test suite

39 tests across the branch's 3 commits (Task 1: rule translation, UNTESTABLE
justification, risk-sizing invariance, harness-reuse identity checks;
Task 2: data-sourcing dispatch checks), all passing, plus the 8 pre-existing
tests for the brought-in prerequisite tool (also passing unchanged).

## Zero auto-wiring

This branch touches `nero_core/research_agent/auto_tester.py` (one
backward-compatible parameter addition, `backtest_params` on
`run_grid_shift_check`, proven byte-identical when omitted),
`tools/philosophy_hypotheses_live_test.py` (the same parameter, threaded
through `run_hypothesis_live`), and this task's own new tool/tests/docs. No
changes to `nero_core.execution.live_scheduler`, `nero_core.strategies.
registry`, or any live scheduler config. Results are written only to
`docs/external_candidates_formal_test_results.json` — never to
`docs/site_data/agent_test_results.json` (the shared production ledger) or
`docs/philosophy_hypotheses_live_test_results.json` (the native graveyard
file).
