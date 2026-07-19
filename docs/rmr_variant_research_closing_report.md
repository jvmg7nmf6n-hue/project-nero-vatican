# RMR Variant Research Cycle — Closing Consolidated Report

Four stages, four commits (plus this closing report): Stage 1 (backtest 4 variants
vs fresh baselines), Stage 2 (diagnosis), Stage 3 (2 diagnosis-justified
refinements), Stage 4 (verdict + promotion list). Full detail in
`docs/rmr_variant_research_stage1.md`, `docs/rmr_variant_research_stage2_diagnosis.md`,
`docs/rmr_variant_research_stage3.md`, and `docs/rmr_variant_research_stage4_verdict.md`.
Per the task's explicit instruction, **nothing was wired into the live scheduler in
this batch**.

## Stage 1: side-by-sides (fresh baselines, same run, same data)

| Config | Asset/TF | Baseline verdict | Variant verdict |
|---|---|---|---|
| RMR_LONG_ONLY_EURUSD_4H | EUR/USD/4h | DIED | DIED (improved, still negative) |
| RMR_ADX_FALLING_ETH_4H | ETH/4h | DIED | DIED (test flips positive, train worsens) |
| RMR_LONG_ONLY_BTC_1D | BTC/1d | DIED (mixed) | PROMISING-WATCHLIST |
| RMR_CONFIRMATION_BTC_1D | BTC/1d | DIED (mixed) | PROMISING-WATCHLIST |

Full ExpR/win%/PF/MaxDD/CI/edge-over-random tables: `docs/rmr_variant_research_stage1.md`.

## Stage 2: diagnosis, in one paragraph each

**(a) Improvement or just sample shrinkage?** Every filter cuts the sample 39-56%.
EUR/USD and BTC long-only show real, mechanistically-corroborated improvement (not
just shrinkage — see (d)); ETH adx-falling is the weakest, most inconsistent case.

**(b) Short-leg cost.** Substantial, not marginal: ~-0.449 R/trade (EUR/USD),
~-0.264 R/trade (BTC), from full-history data. Both long-only variants are
diagnosis-justified, not artifact-mining.

**(c) Edge-over-random within the regime pool.** Mixed overall, but BTC's variants
(long-only, confirmation) and EUR/USD long-only show a real, both-halves-positive
edge over random entry — the regime filter isn't doing all the work for these
specific configs.

**(d) Whipsaw/clustering.** REGIME_BREAK is the single most common exit reason
across every v1.0.0 baseline (39-41% of trades) — real, frequent whipsaw. BTC
confirmation's exit mix shifts dramatically toward REVERSION_TARGET (32% -> 68%),
the clearest mechanistic evidence in the cycle that "waiting for the turn" measurably
works, not sample luck.

## Stage 3: two refinements, cited and scoped

**Refinement 1 (BTC/1d only)**: stacked long-only + confirmation, citing both of
Stage 2's BTC findings. Result: PROMISING-WATCHLIST (positive both halves) but did
NOT clearly outperform either individual filter — it just shrank the sample to the
thinnest in the whole cycle (7-8 trades), undercutting rather than building
confidence in a real, compounding effect.

**Refinement 2 (ETH/4h only)**: applied the already-registered long-only filter to
ETH, testing whether its Stage 1 weakness was also short-side driven. Result: DIED —
refutes the hypothesis for ETH specifically. This was also the ONE config in the
entire cycle genuinely eligible for grid-shift testing (crypto's continuous trading
means no structural gap blocks it, confirmed directly), and it didn't even reach the
point of qualifying for that test.

## Stage 4: verdict

**0 of 6 configs SURVIVED. 3 PROMISING-WATCHLIST (all BTC/1d). 3 DIED.** Every
PROMISING-WATCHLIST config is capped there because BTC's 1d data is native, not
resampled — grid-shift cannot run regardless of the numbers, mirroring the
established precedent from metals/stocks/forex's own native-daily-data findings.

## Promotion list: NOTHING

**No config merits live paper-tracking wiring in a follow-up batch.** Stated plainly:
every PROMISING-WATCHLIST config carries a LOW SAMPLE flag on every half (7-19
trades), every train-half CI crosses zero, and Stage 3's own stacking experiment
weakened rather than strengthened the case (a genuine, robust effect should
concentrate under stacking, not merely lose sample size while the edge stays flat).
The one config that was genuinely, rigorously grid-shift-testable in this whole cycle
DIED outright. If revisited, the three BTC/1d configs are reasonable to re-check once
more daily history accrues — a "keep watching" recommendation, not a "wire it now"
one.

## Data decided

Two of six configs (both BTC/1d) show a real, mechanistically-explained improvement
over v1.0.0's baseline — the short leg was genuinely costly, and waiting for
confirmation genuinely reduces whipsaw exposure, both backed by exit-reason evidence,
not just p-hacked expectancy numbers. But neither reaches a sample size or
statistical confidence that would justify calling it proven, and the one avenue that
could have settled the ETH question and the one refinement designed to compound the
BTC findings both came back negative or inconclusive. Reported factually: this cycle
found real signal in the diagnosis, but not yet a survivor.
