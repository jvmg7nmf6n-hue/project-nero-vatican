# Research Infrastructure Upgrade + New Data Source Batch — Consolidated Report

Three tasks, live data throughout, standard rigor (registry versioning, tests, 70/30
chronological split, LOW SAMPLE flags, factual reporting). Full detail in each task's
own doc: `docs/statistical_harness_upgrade.md`, `docs/funding_extreme_report.md`,
`docs/trail_exit_ab_report.md`.

## 1. Did the 3 live-scheduler survivors hold up under bootstrap CI + random-entry baseline?

**Partially. No survivor clears the strictest possible bar (CI clear of zero on both
halves AND a clear random-entry edge on both halves), but the three differ meaningfully
from each other:**

- **GOLD/1week BREAKOUT_MOMENTUM — holds up best.** CI clears zero on both train
  (0.395, [0.142, 0.648]) and test (0.426, [0.062, 0.789]), with a consistent,
  meaningful edge over random entries in the same trend regime (+0.171 / +0.134).
- **BNB/12h TREND_PULLBACK — point estimate matches all prior work exactly (57/30
  trades, ExpR 0.147/0.243), but its CI crosses zero on both halves** — at this trade
  count, the absolute expectancy isn't statistically distinguishable from zero. It does
  show the largest edge over random of the three (+0.215/+0.181), meaning the specific
  pullback trigger clearly outperforms randomly-timed entries in the same regime, even
  though the absolute number is noisy.
- **BTC-ETH/12h COINTEGRATION_PAIRS — weakest.** CI crosses zero on both halves, and
  its edge over random is close to zero (+0.003/-0.003) — the specific z-score-timed
  entries performed about as well as random entries within the same warmup-valid pool.

No survivor was un-registered or pulled from the live scheduler as a result — that
decision is out of scope for this report.

## 2. Did FUNDING_EXTREME show anything?

**No.** Across all 8 configurations tested (BTC/ETH/SOL/BNB x 8h/24h), **no
asset/timeframe combination shows a robust, cross-validated edge.** Every train half
looks positive on paper (ExpR 0.006–0.400), but only one (BNB/8h) has a CI that clears
zero. Three test halves are **statistically significantly negative**: ETH/8h (-0.191),
SOL/8h (-0.194), SOL/24h (-0.160) — real evidence of out-of-sample degradation, not
just noise. BNB/8h train is the single strongest number in the sweep (CI clears zero
positive, +0.325 edge over random) but its test half is a 12-trade low sample that
neither confirms nor refutes it. The strategy is registered (`funding-extreme-v1.0.0`,
versionable per project convention) but is not a candidate for the live scheduler.

Two real, material bugs were caught by actually running the tool against live data
before reporting — both documented with regression tests in
`docs/funding_extreme_report.md`: the funding-history fetch was silently truncated to
~166 days (Binance returns only its most-recent window when `startTime` is omitted),
and the 8h candle-to-settlement join matched zero rows (Binance kline `close_time` is
`period_end - 1ms`, not the boundary itself). Both are fixed; the results above are
post-fix.

## 3. Did the EMA-trail exits beat their fixed-target counterparts?

**No, on out-of-sample expectancy — but yes, on trade quality shape.** On both BNB/12h
and GOLD/1week, the trail variant shows a clear, consistent, in-sample improvement in
win/loss asymmetry (bigger average winners, smaller average losers, higher profit
factor, lower max drawdown) — a real structural consequence of "let winners run,"
not noise. That advantage does not survive to the test half on either config:

- **BNB/12h**: test expectancy flips negative under the trail (-0.089 vs v1's +0.243).
- **GOLD/1week**: test expectancy stays positive under the trail (0.182) but is weaker
  than v1's (0.426), and its CI crosses zero where v1's doesn't.

Both variants are registered (`trend-pullback-v1.2.0-trail`,
`breakout-momentum-v1.5.0-gold-calibrated-1week-trail`) as required. Neither is a
candidate to replace its v1 counterpart in the live scheduler based on this evidence.

## Commits

1. `tools/backtest_statistics.py` + `tools/backtest_survivor_verification.py` —
   statistical harness upgrade, survivors re-verified.
2. `nero_core/data_sources/funding_data.py` + `nero_core/strategies/funding_extreme.py`
   + `tools/backtest_funding_extreme_sweep.py` — funding data source and strategy.
3. `nero_core/strategies/ema_trail_exit.py` + the two `*_trail.py` variants +
   `tools/backtest_trail_exit_ab_report.py` — trail-exit A/B.

No interpretation beyond what the numbers above say. No strategy's live-scheduler
status changed as part of this work.
