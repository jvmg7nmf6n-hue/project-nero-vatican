# Watchlist Candidates Recheck — Task 1: Scope Disclosure

Branch: `feature/watchlist-candidates-recheck`. Isolated from `main` and every
other in-flight branch. Not merged to `main`.

## Premise correction (read first)

The task brief that kicked off this branch named 5 candidates
(`WISE_MAN_HOLD_V5` on ETH/4h, `WISE_MAN_HOLD_V6` on EUR/USD/4h,
`WISE_MAN_HOLD_V5` on EUR/USD/4h, `ADX_RANGE_V3` on BTC/1d, `ADX_RANGE_V4` on
BTC/1d) as PROMISING-WATCHLIST results to recheck. Verified against every
result-bearing file in this repo before writing any code: **none of these 5
combinations exist anywhere.** The actual `philosophy_hypotheses_live_test.py`
run (a separate, unrelated branch, `feature/philosophy-hypotheses-live-test`)
tested `WISE_MAN_HOLD_V5`/`V6` and `ADX_RANGE_V3`/`V4` **only on BTC/4h**, and
**all four DIED** — zero PROMISING-WATCHLIST results exist in that run at all.

A genuine watchlist story does exist in this repo, spanning ETH/4h, EUR/USD/4h,
and BTC/1d with real PROMISING-WATCHLIST verdicts — the **RMR Variant Research
Cycle** (`docs/rmr_variant_research_stage1.md` through `_stage4_verdict.md`,
commits `dd24839`/`373a8fb`, mid-July 2026, predates and is unrelated to the
philosophy-hypotheses work). This branch rechecks *that* story's real
candidates — approved 2026-08-01, after disclosing the discrepancy rather than
silently building on the wrong premise.

## What triggered testing against ETH/4h, EUR/USD/4h, and BTC/1d

Not a scan that surfaced these combinations opportunistically — the original
Stage 1 task brief explicitly specified all three asset/timeframe pairs
up front, one per new `RANGE_MEAN_REVERSION` variant registered in that same
batch:
- `range-mean-reversion-v1.1.0-long-only` → tested on **EUR/USD/4h**
- `range-mean-reversion-v1.2.0-adx-falling` → tested on **ETH/4h**
- `range-mean-reversion-v1.1.0-long-only` (same variant, second asset) and
  `range-mean-reversion-v1.3.0-confirmation` → both tested on **BTC/1d**

Stage 3's two refinements were each scoped to exactly the asset where the
underlying Stage 2 diagnosis applied — not a fresh scan either:
- Refinement 1 (`v1.4.0-long-only-confirmation`) → BTC/1d only, citing two
  Stage 2 findings diagnosed specifically on BTC/1d.
- Refinement 2 (`v1.1.0-long-only` re-applied) → ETH/4h only, testing whether
  ETH's Stage 1 weakness was short-side driven like EUR/USD's and BTC's were.

## Total combinations run (all of them, not just the 3 that looked good)

Per `docs/rmr_variant_research_stage4_verdict.md`'s own consolidated table —
**6 distinct (variant, asset, timeframe) combinations** across Stages 1 and 3:

| # | Config | Asset/TF | Verdict |
|---|---|---|---|
| 1 | RMR_LONG_ONLY_EURUSD_4H (v1.1.0-long-only) | EUR/USD/4h | DIED |
| 2 | RMR_ADX_FALLING_ETH_4H (v1.2.0-adx-falling) | ETH/4h | DIED |
| 3 | RMR_LONG_ONLY_BTC_1D (v1.1.0-long-only) | BTC/1d | **PROMISING-WATCHLIST** |
| 4 | RMR_CONFIRMATION_BTC_1D (v1.3.0-confirmation) | BTC/1d | **PROMISING-WATCHLIST** |
| 5 | RMR_LONG_ONLY_CONFIRMATION_BTC_1D (v1.4.0, Stage 3 Refinement 1) | BTC/1d | **PROMISING-WATCHLIST** |
| 6 | v1.1.0-long-only on ETH/4h (Stage 3 Refinement 2) | ETH/4h | DIED |

**3 of 6 SURVIVED-track combinations classified DIED. 3 of 6 (all BTC/1d)
classified PROMISING-WATCHLIST. 0 of 6 SURVIVED.** This exact count — not a
"5 good ones" framing — is the honest context: half the combinations tested
against these three assets failed outright, including the ONE refinement
(ETH/4h, Refinement 2) that was genuinely grid-shift-eligible and came back
negative. Every PROMISING-WATCHLIST result is capped there for a documented,
structural reason (see below), not a borderline judgment call.

## Why grid-shift wasn't run for the 3 real candidates (a structural fact, not a gap)

All three PROMISING-WATCHLIST configs are BTC/**1d**. Per
`tools/rmr_variant_research_stage3.py`'s own docstring and the Stage 4 verdict:
*"BTC/1d is structurally limited (native daily data, per this task's own
rule) — capped at PROMISING-WATCHLIST if positive both halves, not tested."*
This branch's own Task 2 instructions (written against the wrong premise)
named `ADX_RANGE_V3`'s grid-shift as "a gap in the original run, not a new
ask" — that instruction doesn't transfer to Story A's real candidates:
`ADX_RANGE_V3` doesn't appear anywhere in this story, and none of the 3 real
BTC/1d candidates were ever flagged as having an *unrun* grid-shift check —
they were flagged as *not eligible* for one, a different and already-settled
question. Re-litigating that eligibility call (e.g. attempting a new
hourly→daily resampling path for BTC that the original research never built)
would be a genuine scope expansion beyond "recheck these exact candidates,"
which this branch's own anti-p-hacking instruction rules out. Grid-shift is
therefore correctly reported as N/A for this recheck, inherited from the
original research's own settled convention, not re-opened here.

## Disclosure, not a gate

Per this task's own instruction, this is disclosure, not a blocker — proceeding
to Task 2 (out-of-sample recheck of the 3 real BTC/1d PROMISING-WATCHLIST
candidates) regardless of this count.
