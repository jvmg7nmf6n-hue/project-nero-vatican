# Repair Lab v1 — Closing Report

**Branch:** `feature/repair-lab-v1` (based on `feature/short-side-support`, since Repair Lab's `direction_add_mirror` repair type requires the bidirectional/`mirror_condition` infrastructure that branch built and that does not exist on `main`). Isolated, not merged to `main`.

Implements exactly what `docs/repair_lab_investigation_report.md` scoped and recommended, nothing more: a closed loop for **DIED hypotheses only**, diagnosis from aggregate failure stats, one LLM-proposed modification per attempt within an approved repair-scope boundary, retested on genuinely fresh data (historical reservation or forward paper-tracking), capped at 4 launched attempts, full chain transparency.

## What was built, by task

1. **Eligibility gate** (`nero_core/research_agent/repair_lab.py::check_eligibility`) — only `VERDICT_DIED` passes; `SKIPPED` (TOO_SLOW/UNMEASURABLE), `UNTESTABLE`, `SURVIVED`, `PROMISING-WATCHLIST` are all explicitly rejected with the real disqualifying classification named.
2. **Diagnosis + modification boundary** (`build_diagnosis_prompt`, `propose_modification`, `validate_modification`) — 4 approved modification types (`entry_threshold`, `exit_structure`, `direction_add_mirror`, `asset_timeframe_change`), each with a precise, testable invariant. `asset_timeframe_change` is excluded from the prompt itself unless the original result's own sample is thin, and is validated post-hoc against the real `docs/site_data/repair_candidates.json` file, never the LLM's own claim.
3. **In-chain duplicate check** (`check_in_chain_duplicate`) — exact `StructuredRule`/`ExitPlan` equality against the original hypothesis and every prior attempt in the same chain, scoped narrow per the investigation's own recommendation.
4. **Fresh-data mechanisms** — `repair_historical_reservation.py` (non-overlapping segment reservation + frozen-snapshot grid-shift, fixing the live-fetch non-determinism `feature/short-side-support` found) and `repair_forward_tracker.py` (a tick-based forward-tracking mechanism reusing `ORDERFLOW_IMBALANCE`'s own pattern via `nero_core.truth_ledger.execution_log`'s generic functions, but writing to its own separate `data/repair_lab_forward_tracking.db`, plus the verdict-computation step that gap in the codebase never had before).
5. **The 4-attempt cap** (`can_launch_new_attempt`, `evaluate_chain_terminal_state`) — counts launches, not resolutions; `PERMANENTLY_DIED` is explicit and never silently bypassed.
6. **Chain record** (`repair_attempts.json` event log, `reconstruct_chain_state`) — append-only, immutable events, lineage structural (a chain's attempts are never returned in isolation from their own history).
7. **Architectural isolation** (`tests/test_repair_lab_no_auto_wire.py`) — proven, not assumed, that every new file is covered by the existing static glob and reports zero offenders, plus a new dynamic end-to-end test confirming `default_registry` is untouched.

## Real DIED hypotheses used as test cases

- **`EXT_WISE_MAN_HOLD_V5_ETH_4H`** — this session's own real DIED result from `feature/short-side-support`'s backward-compat baseline (`train: N=176 ExpR=-0.330; test: N=53 ExpR=-0.057 -> DIED`). Used across the eligibility, diagnosis-boundary, in-chain-duplicate, and no-auto-wire dynamic tests — its real entry rule (`close < bb_lower AND adx14 < 25`) and exit plan drove the `entry_threshold`/`exit_structure`/`direction_add_mirror` validation tests, including the mirror-check bug this build found and fixed (see below).
- **`docs/site_data/repair_candidates.json`** — the REAL, existing file, not mocked, loaded directly in tests. Its `RMR_CONFIRMATION_METALS_WEEKLY` entry (a real, already-authored diagnosis: RANGE_MEAN_REVERSION's confirmation filter tested only on BTC/1d's thin 7-19-trade sample, proposing GOLD/1week and SILVER/1week instead) is the exact precedent `test_repair_lab_diagnosis_boundary.py`'s `asset_timeframe_change` tests validate against — a synthetic `RMR_CONFIRMATION_BTC_1D` original hypothesis (modeled directly on that real diagnosis text) proposing GOLD/1week is approved; a target with no support in the file is rejected.
- **`tests/fixtures/frozen_candles/BTC_4h.json`** — the real, committed frozen BTC candle fixture from `feature/short-side-support`'s own backward-compat proof, reused directly for `reserve_historical_segment`'s non-overlap tests (not synthetic data).
- **`EXT_ADX_RANGE_V3_BTC_1D`** (real TOO_SLOW result, 11.84 trades/year) — used in the eligibility-gate test proving TOO_SLOW is correctly rejected with the specific frequency classification named.

## Safety and anti-p-hacking guarantees — confirmed via passing tests, not assumption

| Guarantee | Proven by |
|---|---|
| Only DIED hypotheses enter Repair Lab | `test_repair_lab_eligibility.py` (8 tests) — every non-DIED verdict explicitly rejected |
| Every proposal stays within the approved repair-scope boundary | `test_repair_lab_diagnosis_boundary.py` (25 tests) — each of the 4 types' invariant tested both for legitimate proposals and for boundary-violating ones (structural changes disguised as threshold retunes, asset changes smuggled into the wrong type, unsupported asset/timeframe targets) |
| No re-testing on data an attempt or the original already touched | `test_repair_lab_historical_reservation.py::test_reserved_segment_never_overlaps_a_consumed_window` and `test_reserving_twice_produces_disjoint_segments` — direct, per-candle non-overlap assertions, not a claim |
| Grid-shift verification is immune to the live-fetch non-determinism `feature/short-side-support` found | `test_two_calls_with_the_same_hourly_frame_produce_byte_identical_grids` — `pd.testing.assert_frame_equal` on two independent calls |
| `PENDING_FORWARD_DATA` is never mistaken for a resolved verdict | `test_pending_forward_data_is_never_the_same_value_as_any_resolved_status` (chain record) + `test_pending_below_two_times_min_sample_size_returns_none_not_a_fabricated_verdict` (forward tracker: `compute_forward_verdict` returns `None`, not a guess, below the threshold) |
| The 4-attempt cap counts launches, including still-pending attempts, not resolutions | `test_cannot_launch_a_5th_when_some_attempts_are_still_pending_forward_data` — the task's own explicit 2-DIED-plus-2-pending edge case, hard-rejected |
| A chain never reaches `PERMANENTLY_DIED` while any attempt is still pending | `test_chain_stays_open_at_the_cap_if_any_attempt_is_still_pending` |
| Exactly one modification per attempt, decided before any retest data is seen | Structural: `propose_modification` makes exactly one LLM call per invocation, returns exactly one proposal; there is no re-roll/retry-and-keep-best code path anywhere in this module — confirmed by reading `nero_core/research_agent/repair_lab.py` in full, not just by a passing test |
| Duplicate/near-duplicate attempts within a chain can't silently consume a cap slot | `test_repair_lab_in_chain_duplicate.py` (7 tests) — exact repeats of the original or any prior attempt caught, including when a different attempt sits in between |
| Every proposal is recorded, including rejected ones | `test_rejected_proposals_are_recorded_but_never_counted_as_launched` (chain record) |
| Lineage is structurally unambiguous | `test_lineage_is_structural_attempt_3_always_comes_with_attempts_1_and_2` — there is no accessor that returns one attempt in isolation from its chain |

## Zero auto-wiring — confirmed

- `git diff` of `nero_core/execution/live_scheduler.py`, `nero_core/strategies/registry.py`, `nero_core/research_agent/hypothesis_gen.py`, and `nero_core/research_agent/frequency_gate.py` against this branch's own base commit is **empty** — none of these were touched, confirmed directly, not asserted from memory.
- `nero_core/research_agent/auto_tester.py`'s only change is two additive public re-export aliases (`size_entry_for_hypothesis`, `evaluate_exit_for_hypothesis`) at the end of the file — reuse, not reimplementation, per the task's own explicit allowance.
- `tests/test_research_agent_no_auto_wire.py` — **zero modification** (`git diff` empty), still passes 3/3 unmodified.
- `tests/test_repair_lab_no_auto_wire.py` (new, 3 tests) — proves the static glob genuinely covers every new file (not assumed) and runs a full, realistic Repair Lab flow end to end (eligibility → diagnosis validation → duplicate check → historical reservation → a forward-tracking tick → chain-record append/reconstruct → cap check) with `default_registry`'s variant count asserted unchanged before and after.
- Forward-tracking writes to its own, separate `data/repair_lab_forward_tracking.db` — never the production `data/truth_ledger.db` `ORDERFLOW_IMBALANCE` and every live strategy share. Same tested plumbing (`nero_core.truth_ledger.execution_log`'s own functions), physically separate storage.

## A real bug found and fixed during this build

An early version of the `direction_add_mirror` validator required the proposed short rule to be the LITERAL output of `rule_dsl.mirror_condition()` applied condition-by-condition. This would have **rejected this project's own real, already-accepted `EXT_ADX_RANGE_V3/V4_BTC_1D` hypothesis shape** — its real short rule mirrors `close < bb_lower` to `close > bb_upper` (swapping `compare_to_field`, which a literal `mirror_condition()` call never does) and leaves its shared ADX regime condition completely unchanged (matching `regime_break_condition`'s own never-mirrored precedent). Caught by writing a test using that exact real shape, which failed. Fixed with `_is_legitimate_direction_mirror`: same field tested per condition, and each condition either completely unchanged (a shared gate) or with its op exactly flipped — matches the real precedent while still blocking a threshold change hidden behind an unchanged op (also directly tested).

## Full regression

Split into two runs because a single `python -m unittest discover` invocation was repeatedly killed by this environment's background-task wall-clock limit once this branch's own test additions pushed the total past it (not a test failure — the harness terminated the process mid-run):

- **1994/1994** — every test file except the one known-slow inherited file (`test_short_side_support_backward_compat.py`, ~215s alone re-running real backtests with bootstrap CI on large frozen datasets): **OK**, 123.4s.
- **4/4** — `test_short_side_support_backward_compat.py` run separately: **OK**, 215.4s.
- **1998/1998 total, zero failures.**

1994 = 1906 (the full suite `feature/short-side-support` left behind, minus the 4 tests in the one file run separately) + 88 new Repair Lab tests across the 7 tasks above (8+25+7+10+10+12+13+3).

## Merge readiness

Ready for CC-1 to review. Every task (1-7) is implemented with real, working code (not stubs), backed by 88 new tests plus the extended no-auto-wire coverage, all passing. The critical anti-p-hacking constraint from the investigation is enforced structurally, not just documented: fresh-data non-overlap is asserted directly, the cap counts launches, `PENDING_FORWARD_DATA` can never be mistaken for a resolution, and every rejection (in-chain duplicate or out-of-boundary) is recorded rather than silently discarded. Not merged to `main` by this work, per the task's own instruction.

**Not built in this branch, by design** (matching the investigation's own explicit v1 scope): TOO_SLOW hypothesis handling, cross-chain duplicate detection, any real production scheduling/cron wiring for the forward-tracking tick (the tick function itself is complete and tested; a human or a future cron invokes it — this branch deliberately does not add that wiring, since doing so was never asked for and would risk exactly the kind of scope creep this project's own discipline warns against), and a timeout/expiry policy for an attempt that never accrues enough forward-tracked trades (left honestly open rather than an invented arbitrary cutoff).
