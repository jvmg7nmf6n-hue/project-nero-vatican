# RMR Variant Research Cycle — Stage 2: Diagnosis

Numbers before any refinement, per the task's own 4 required questions. Combines
Stage 1's train/test statistics with new full-history exit-reason and
implied-short-leg-cost data from `tools/rmr_variant_research_stage2_diagnosis.py`
(full raw output: `docs/rmr_stage2_raw_output.txt`).

## (a) Does each filter IMPROVE test-half expectancy, or just shrink the sample?

| Variant | Baseline test ExpR | Variant test ExpR | Sample change | Verdict |
|---|---|---|---|---|
| EUR/USD long-only | -0.485 | -0.280 | 27 -> 12 (56% cut) | Improved, but still DIED |
| ETH adx-falling | -0.083 | +0.035 | 105 -> 61 (42% cut) | Improved in TEST, but TRAIN worsened (-0.162 -> -0.192) — inconsistent |
| BTC long-only | +0.366 | +0.535 | 18 -> 8 (56% cut) | Improved, flips baseline's mixed train (-0.202) to positive (+0.052) |
| BTC confirmation | +0.366 | +0.156 | 18 -> 11 (39% cut) | Test WORSE than baseline's test, but train flips to positive too |

Every variant cuts the sample substantially (39-56%). Cutting the sample alone would
be expected to occasionally look better by chance — the question is whether there's
a mechanistic reason to believe it, answered in (d) below. Short answer: **EUR/USD
and BTC's long-only variants have real, diagnosis-backed mechanistic support (see
(b)); ETH's adx-falling result is the weakest of the four — inconsistent across
halves, and the exit-reason shift (below) is real but smaller than BTC's.**

## (b) What did the short leg actually cost in the fresh v1.0.0 baseline?

Computed from the SAME full backtest history (not split), as (baseline total R) -
(long-only total R) — an approximation, since disabling shorts can also let a later
LONG trade fire where the baseline's concurrent short position would have blocked
it, so this isn't an exact attribution, but it's the right order of magnitude:

- **EUR/USD/4h**: baseline 86 trades, total R = -30.40. Long-only 42 trades, total R
  = -10.65. Implied short-leg: ~44 trades, total R = -19.74, **average ~-0.449 R per
  short-attributed trade.**
- **BTC/1d**: baseline 62 trades, total R = -3.98. Long-only 27 trades, total R =
  +5.26. Implied short-leg: ~35 trades, total R = -9.24, **average ~-0.264 R per
  short-attributed trade.**

**Both are substantial, not marginal.** -0.45 R/trade and -0.26 R/trade are real,
meaningful drags, not artifact-mining-scale noise (an artifact-mining concern would
look like a cost near 0, e.g. -0.02 R/trade, where removing it is just removing
noise). **Both long-only variants are diagnosis-justified**: the short side was a
genuine, substantial cost on both assets, corroborated by the exit-reason shift in
(d) — this is stated plainly per the task's own instruction, and it points AWAY from
"long-only is likely artifact-mining" for both EUR/USD and BTC.

## (c) Does edge-over-random hold within the ranging-regime pool?

Mixed, but several configs show a real, BOTH-HALVES-positive edge over random entry
within the same ADX<25 pool: EUR/USD long-only (+0.069/+0.104), BTC long-only
(+0.089/+0.579), BTC confirmation (+0.143/+0.208). ETH (both baseline and
adx-falling) never clears both halves positive. The baseline configs themselves show
edge-over-random close to zero or negative in most cases — consistent with Task 2's
own finding that band-extreme timing alone rarely beats random entry within the
regime; the REFINEMENTS (long-only, confirmation) appear to concentrate what edge
exists into a cleaner subset, at the cost of a much smaller sample.

## (d) Trade clustering / ADX-exit frequency / whipsaw patterns

**REGIME_BREAK (the market genuinely starting to trend) is the single most common
exit reason across EVERY v1.0.0 baseline tested**: EUR/USD 41% (35/86), ETH 39%
(144/368), BTC 39% (24/62). This is real, frequent, quantified whipsaw — the
strategy regularly gets caught by a range breaking into a trend shortly after entry,
not a rare tail event.

**The confirmation variant's exit-reason mix shifts dramatically**: BTC baseline is
32% REVERSION_TARGET / 39% REGIME_BREAK / 29% STOP; BTC confirmation is 68%
REVERSION_TARGET / 16% REGIME_BREAK / 16% STOP. This is the single clearest piece of
mechanistic evidence in the whole diagnosis — "waiting for the turn" measurably
avoids the regime-break/stop-out failure mode, not just a smaller, luckier sample.

**Long-only's exit mix also shifts, consistent with the short-cost finding**: BTC
STOP share drops from 29% (baseline) to 15% (long-only) — shorts were disproportionately
responsible for hitting the disaster stop (consistent with "shorting into a
breakout" being a common failure mode). EUR/USD's REGIME_BREAK share drops from 41%
(baseline) to 29% (long-only), with REVERSION_TARGET share rising from 28% to 40% —
the same pattern: shorts were disproportionately caught by regime breaks.

**ETH adx-falling's shift is real but smaller**: REGIME_BREAK share drops from 39% to
33% — a genuine but modest effect, consistent with (a)'s weaker, inconsistent-across-halves
result for this variant specifically.

## Summary going into Stage 3

Three of four variants (EUR/USD long-only, BTC long-only, BTC confirmation) show
real, mechanistically-corroborated improvements — not merely sample-shrinkage
artifacts — though none has an adequate sample yet. ETH's adx-falling variant is the
weakest: a real but smaller mechanistic effect, and an inconsistent train/test
result. This should inform which asset/timeframe Stage 3's refinements target.
