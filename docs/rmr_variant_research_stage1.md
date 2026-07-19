# RMR Variant Research Cycle — Stage 1: Backtest 4 Variants vs Fresh Baselines

Tool: `tools/rmr_variant_research_stage1.py`. Every variant was run against a FRESH,
in-the-same-run v1.0.0 baseline on the exact same asset/timeframe/data — never a
stale stored comparison. All four variants registered as new, append-only versions
under `RANGE_MEAN_REVERSION`: `range-mean-reversion-v1.1.0-long-only`,
`-v1.2.0-adx-falling`, `-v1.3.0-confirmation`. Fees: EUR/USD flat 0.05%/side
(matching every prior forex task), ETH/BTC unscaled crypto-baseline default. Full raw
output in `docs/rmr_stage1_raw_output.txt`.

## Side-by-side results

### (a) EUR/USD / 4h — long-only vs baseline

| | Half | N | ExpR | Win% | PF | MaxDD | Edge-over-random | 95% CI |
|---|---|---|---|---|---|---|---|---|
| **v1.0.0 baseline** | TRAIN | 59 | -0.293 | 39.0% | 0.39 | -10.58% | +0.029 | [-0.511, -0.071] |
| | TEST | 27 | -0.485 | 14.8% | 0.25 | -4.57% | -0.084 | [-0.801, -0.132] |
| **v1.1.0-long-only** | TRAIN | 30 | -0.243 | 40.0% | 0.49 | -4.42% | +0.069 | [-0.542, 0.051] |
| | TEST | 12\* | -0.280 | 33.3% | 0.65 | -1.71% | +0.104 | [-0.895, 0.416] |

**Verdict: both DIED.** Long-only improves both halves (less negative ExpR, lower
MaxDD) but never turns positive.

### (b) ETH / 4h — ADX-falling vs baseline

| | Half | N | ExpR | Win% | PF | MaxDD | Edge-over-random | 95% CI |
|---|---|---|---|---|---|---|---|---|
| **v1.0.0 baseline** | TRAIN | 262 | -0.162 | 42.7% | 0.58 | -36.04% | -0.099 | [-0.262, -0.063] |
| | TEST | 105 | -0.083 | 50.5% | 0.77 | -9.14% | -0.014 | [-0.235, 0.071] |
| **v1.2.0-adx-falling** | TRAIN | 141 | -0.192 | 42.6% | 0.57 | -23.90% | -0.134 | [-0.330, -0.054] |
| | TEST | 61 | +0.035 | 54.1% | 1.10 | -6.35% | +0.108 | [-0.154, 0.231] |

**Verdict: both DIED.** Test half flips positive but train half WORSENS — mixed,
inconsistent across halves.

### (c)+(d) BTC / 1d — long-only and confirmation vs the SAME baseline

| | Half | N | ExpR | Win% | PF | MaxDD | Edge-over-random | 95% CI |
|---|---|---|---|---|---|---|---|---|
| **v1.0.0 baseline** | TRAIN | 42 | -0.202 | 38.1% | 0.56 | -7.93% | -0.170 | [-0.443, 0.053] |
| | TEST | 18\* | +0.366 | 72.2% | 3.75 | -1.21% | +0.415 | [0.066, 0.638] |
| **v1.1.0-long-only** | TRAIN | 19\* | +0.052 | 52.6% | 1.14 | -3.33% | +0.089 | [-0.329, 0.437] |
| | TEST | 8\* | +0.535 | 87.5% | 9.51 | -0.51% | +0.579 | [0.168, 0.884] |
| **v1.3.0-confirmation** | TRAIN | 14\* | +0.118 | 64.3% | 1.38 | -1.03% | +0.143 | [-0.304, 0.527] |
| | TEST | 11\* | +0.156 | 81.8% | 2.08 | -0.56% | +0.208 | [-0.196, 0.468] |

**Verdict: baseline DIED (train negative, test positive — mixed); BOTH long-only and
confirmation are PROMISING-WATCHLIST (positive both halves)** — but every single
half across all three BTC configs is LOW SAMPLE (`*`, below 20 trades), and every
train-half CI still crosses zero. A real signal shift, not yet a proven one.

## What changed structurally, not just numerically

A companion diagnosis run (`tools/rmr_variant_research_stage2_diagnosis.py`, full
history, not train/test split) shows WHY these numbers moved, not just that they did
— see `docs/rmr_variant_research_stage2_diagnosis.md` for the full analysis. Headline:
REGIME_BREAK (the market genuinely starting to trend) is the single most common exit
reason across every v1.0.0 baseline tested (39-41% of all trades) — real, frequent
whipsaw, not a rare edge case — and the BTC confirmation variant's exit mix shifts
dramatically toward REVERSION_TARGET (68%, vs baseline's 32%), the clearest evidence
in this whole cycle that "waiting for the turn" is a mechanistic change, not sample
noise dressed up as one.
