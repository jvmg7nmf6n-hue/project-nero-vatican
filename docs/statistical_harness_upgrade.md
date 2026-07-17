# Statistical Harness Upgrade — Survivor Re-Verification

## What was added

`tools/backtest_statistics.py` — two deterministic (fixed-seed) additions to the
verification harness:

1. **Bootstrap 95% CI on mean per-trade R** (`bootstrap_mean_r_ci`): resample trades
   with replacement, 5000 iterations, seed `20260718`, report the `[2.5th, 97.5th]`
   percentile of the resampled means. A CI that crosses zero means the point-estimate
   expectancy is not statistically distinguishable from zero at this sample size,
   regardless of how positive it looks.
2. **Random-entry baseline** (`random_entry_baseline_single_asset` /
   `random_entry_baseline_pairs`): 200 runs, seed `20260718`. Each run replays the exact
   same exit rule, sizing, and fees as the real strategy, but replaces the entry
   TRIGGER with a random draw from the same regime-filtered eligible pool
   (`close > MA200` for BREAKOUT_MOMENTUM; `close > MA200 AND MA50 > MA200` for
   TREND_PULLBACK), calibrated so the expected trade count matches the real strategy's
   count for that half. Reports mean/95th-percentile random ExpR and the real
   strategy's edge over that mean. For COINTEGRATION_PAIRS, there is no regime concept
   separate from the z-score trigger itself, so the eligible pool is every
   warmup-valid candle and entry side is chosen 50/50 — a deliberately weaker null
   hypothesis, flagged as a caveat on every pairs result.

`tools/backtest_survivor_verification.py` wires both into a standard report for the 3
live-scheduler survivors, chronological 70/30 split, with a `< 20 trades` LOW SAMPLE
flag carried over from the existing convention.

## Bug caught before reporting

The first run of this tool showed BNB/TREND_PULLBACK with NEGATIVE expectancy
(-0.048 train, -0.030 test) — a result that contradicted every prior established number
for this exact config (`docs/grid_shift_robustness_followup.md` shows +0.147 to +0.243
across every grid tested). Root cause: `TREND_PULLBACK`'s registered
`max_holding_hours=24` is a 1h-reference default; on 12h candles that's only a
**2-candle** hold cap, silently force-closing nearly every trade via the TIME rule
before a real stop or target could fire — the identical bug class already fixed for
GOLD/1week, and already documented as a required step in
`tools/backtest_regime_scaled_risk_report.py`, which this new tool simply forgot to
apply. Fixed by adding the same `needs_timeframe_calibration` flag and
`build_calibrated_params` call that tool already uses; the corrected run's trade counts
(57 train / 30 test) and ExpR (0.147 / 0.243) now match the prior established numbers
exactly. A regression test (`TimeframeCalibrationRegressionTest` in
`tests/test_backtest_survivor_verification.py`) guards against this specific
regression recurring. GOLD's config is explicitly flagged `needs_timeframe_calibration:
False` — its registered params already bake in the 1week holding-cap fix and GOLD fee
scaling; re-running calibration on it would double-apply the fee scale factor.

## Results (live data, run against real Binance/Twelve Data feeds)

| Config | Split | N | ExpR | Bootstrap 95% CI | Verdict | Random baseline mean ExpR | Edge over random |
|---|---|---|---|---|---|---|---|
| GOLD/1week BREAKOUT_MOMENTUM | Train | 63 | 0.395 | [0.142, 0.648] | clears zero | 0.224 | **+0.171** |
| GOLD/1week BREAKOUT_MOMENTUM | Test | 31 | 0.426 | [0.062, 0.789] | clears zero | 0.291 | **+0.134** |
| BNB/12h TREND_PULLBACK | Train | 57 | 0.147 | [-0.151, 0.447] | **crosses zero** | -0.068 | **+0.215** |
| BNB/12h TREND_PULLBACK | Test | 30 | 0.243 | [-0.154, 0.619] | **crosses zero** | 0.062 | **+0.181** |
| BTC-ETH/12h COINTEGRATION_PAIRS | Train | 61 | 0.047 | [-0.001, 0.108] | **crosses zero** | 0.044 | +0.003 |
| BTC-ETH/12h COINTEGRATION_PAIRS | Test | 22 | 0.003 | [-0.024, 0.036] | **crosses zero** | 0.006 | -0.003 |

All three configs are below (GOLD, BNB) or near (PAIRS) the 20-trade LOW SAMPLE
threshold on at least one half; none of these numbers should be read as conclusive at
this sample size.

## Factual read, no more than the numbers say

- **GOLD/1week BREAKOUT_MOMENTUM** holds up best under this stricter lens: positive CI
  on both halves (doesn't cross zero) and a consistent, meaningful edge over random
  entries in the same trend regime (+0.171 train, +0.134 test). This is the strongest
  of the three survivors by this measure.
- **BNB/12h TREND_PULLBACK**: the point-estimate expectancy is positive and matches
  every prior measurement of this config exactly, but the bootstrap CI crosses zero on
  both halves — at only 57/30 trades, the absolute expectancy is not statistically
  distinguishable from zero. Separately, its edge over the random-entry baseline is the
  largest of the three configs (+0.215 / +0.181), meaning the specific pullback-to-MA50
  trigger does noticeably better than randomly-timed entries in the same uptrend
  regime — a genuine relative signal sitting on top of a small absolute sample.
- **BTC-ETH/12h COINTEGRATION_PAIRS**: the weakest result under this lens. Expectancy is
  small (0.047/0.003), the CI crosses zero on both halves, and — most notably — the
  edge over random is close to zero (+0.003 train, -0.003 test), meaning random entry
  timing within the same warmup-valid pool performed about as well as the actual
  z-score-triggered entries. This is reported with the caveat that PAIRS' random
  baseline is a weaker null hypothesis than the single-asset ones (no regime filter to
  isolate, random 50/50 side selection), but the near-zero edge is the most
  unfavorable reading of any of the three survivors.

No strategy is being un-registered or pulled from the live scheduler as a result of
this report — that decision is out of scope for this task, which is to report the
stricter-lens numbers factually, not to re-adjudicate survivor status.
