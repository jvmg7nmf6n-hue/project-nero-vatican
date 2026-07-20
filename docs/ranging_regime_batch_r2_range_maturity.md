# Ranging-Regime Research Batch — R2: RANGE_MATURITY

**Question: does range AGE fix RANGE_MEAN_REVERSION's reversion signal?**

RMR's closing report found its only PROMISING-WATCHLIST results were on weekly
precious metals — the slowest, most "mature" ranges the whole cycle tested. R2 tests
range age as the missing variable directly: `nero_core/strategies/
range_mean_reversion_maturity.py` (range-mean-reversion-v1.5.0-range-maturity) is
IDENTICAL to v1.0.0 in every respect (bands, exits, sizing) plus ONE new gate — entry
additionally requires ADX < 25 for >= `mature_range_min_candles` CONSECUTIVE closed
candles immediately before the entry candle (not merely at the entry candle itself,
which is all v1.0.0 checks). `mature_range_min_candles`: 20 for 4h/1d configs, 8 for
1week (task-specified: 20 weekly candles would be ~5 months of continuous range,
emptying the sample; 8 weeks is mature but achievable).

9 new unit tests (`tests/test_range_mean_reversion_maturity.py`): gate rejection/
acceptance, coexistence with v1.0.0's own rejection reasons, streak-counter behavior
across a full backtest run (including reset-on-trend-break). All pass.

## v1.0.0 vs v1.5.0, same data window, same run (never a stale comparison)

| Config | v1.0.0 baseline | v1.5.0 maturity gate |
|---|---|---|
| GOLD / 1d | DIED (84/-0.037, 34/-0.050) | DIED (18\*/+0.020, 8\*/-0.504) |
| GOLD / 1week | **PROMISING-WATCHLIST** (36/+0.026, 11\*/+0.107) | **DIED** (24/-0.038, 4\*/+0.157) |
| SILVER / 1d | DIED (131/-0.169, 67/+0.030) | DIED (25/-0.306, 9\*/-0.223) |
| SILVER / 1week | **PROMISING-WATCHLIST** (23\*/+0.320, 15\*/+0.263) | **PROMISING-WATCHLIST** (18\*/+0.187, 11\*/+0.210) |
| BTC / 1d | DIED (42/-0.202, 18\*/+0.366) | DIED (0\*/0.000, 1\*/-0.700) |
| EURUSD / 4h | DIED (59/-0.293, 27/-0.485) | DIED (8\*/+0.053, 3\*/-1.246) |
| EURUSD / 1d | DIED (91/+0.044, 31/-0.145) | DIED (24/+0.069, 5\*/-0.657) |

## Reading this factually

- **The maturity gate never rescues a DIED baseline.** Every config that DIED under
  v1.0.0 also DIED under the maturity gate — most with a WORSE test-half expectancy
  under the gate (EURUSD/4h: -0.485 -> -1.246; EURUSD/1d: -0.145 -> -0.657; BTC/1d:
  the mature pool nearly vanished, train N=0). Shrinking to only the most mature
  ranges did not turn any losing config into a winning one.
- **GOLD/1week — the single BEST result in the entire RMR/R1/R2 body of work so far —
  got WORSE under the maturity gate**, flipping train-half expectancy from +0.026 to
  -0.038. This directly contradicts the hypothesis this variant was built to test:
  if range age were the missing variable, GOLD/1week's own already-mature weekly
  ranges should have concentrated the edge, not erased it.
- **SILVER/1week is the one config that holds its PROMISING-WATCHLIST status** under
  the gate — but with a smaller sample on both halves (23->18 train, 15->11 test) and
  a SMALLER edge, not a larger one (train ExpR 0.320->0.187). This is the same
  "shrinks the sample without concentrating the effect" pattern RMR's own Stage 3
  stacking experiment already established as evidence AGAINST a robust underlying
  effect, not for one.
- **Mature-pool sizes are large relative to actual trade counts** (e.g. GOLD/1d:
  184 mature-eligible candles in train, but only 18 trades fire) — the gate is
  correctly restricting the ELIGIBLE window, not accidentally starving it to zero
  (except BTC/1d, where the pool collapsed to 3 candles train-side — BTC/1d's price
  action essentially never sustains a 20-candle unbroken range).

## Grid-shift

**0 of 7 configs meet the qualifying bar** (both halves >= 20 trades AND positive
both halves). SILVER/1week comes closest on sample count relative to its own history
but both halves remain below 20, and 1week is native (not resampled) for both GOLD
and SILVER in this pipeline regardless — grid-shift would be NOT_APPLICABLE there
even had it qualified, per this project's own established precedent.

## Verdict: does maturity fix reversion?

**No.** Across every config tested, the maturity gate either left a losing baseline
losing (usually worse) or, in its single "success," merely shrank an already-thin
sample without improving the edge. Range age is not the missing variable RMR's own
closing report speculated it might be. **Nothing from R2 is promoted or wired
anywhere** — v1.0.0's own registration is unaffected; the maturity variant is
registered (v1.5.0) purely as a tested, documented negative result.
