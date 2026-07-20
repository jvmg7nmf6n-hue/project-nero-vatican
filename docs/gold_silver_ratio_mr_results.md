# GOLD_SILVER_RATIO_MR v1.0.0 — Results

See `docs/gold_silver_ratio_data_audit.md` for the data audit (cleared, with the
GOLD/SILVER timestamp-alignment gotcha found and fixed). Strategy:
`nero_core/strategies/gold_silver_ratio_mr.py`. 27 passing unit tests
(`tests/test_gold_silver_ratio_mr.py`). Sweep tool:
`tools/gold_silver_ratio_sweep.py`.

## Full results, both timeframes

| Timeframe | Verdict | Train N/ExpR/CI | Test N/ExpR/CI | Edge over random (train/test) |
|---|---|---|---|---|
| 1d | **PROMISING-WATCHLIST** | 59/+0.077/[-0.325,0.537] | 26/+0.309/[-0.224,0.889] | +0.088 / +0.193 |
| 1week | **PROMISING-WATCHLIST** | 11\*/+0.239/[-0.764,1.384] | 6\*/+0.282/[-1.166,1.907] | +0.266 / -0.203 |

**Both timeframes positive on both halves.** 1d clears the 20-trade adequacy bar
on BOTH halves (N=59 train, N=26 test); 1week is thin on both halves (11/6
trades, flagged LOW SAMPLE). Every CI still crosses zero on both timeframes — not
yet statistically distinguishable from noise at this sample size, but genuinely,
consistently positive in direction across both timeframes and (mostly) across
the random-entry comparison too.

## Mechanistic read

- **The pairs-aware stop, not reversion, is the dominant exit path**: 1d train
  shows 42 RATIO_STOP exits vs 17 REVERSION (71% stop rate); 1week train shows 8
  vs 3 (73%). The strategy is net profitable DESPITE this — reversion trades, when
  they land, evidently carry enough edge to outweigh a high stop-out rate — but
  this is a real, worth-watching characteristic: most individual attempts fail to
  reach the median before the ratio diverges further.
- **Edge over random is positive in 3 of 4 half-configs** (1d train +0.088, 1d
  test +0.193, 1week train +0.266) — entering at the FIRST candle an extreme
  fires beats a random candle within the same eligible (outside-the-band) pool,
  suggesting timing precision at the extreme itself does add something beyond
  the regime filter alone. The one negative (1week test, -0.203) is on the
  thinnest sample in the whole sweep (N=6) and should not be over-read.
- **Eligible pools are large relative to trade counts** (1d train: 898 eligible
  candles, 59 actual trades) — the band correctly restricts entries to genuine
  extremes, not accidentally starving the strategy of opportunities.

## Grid-shift

**1d is explicitly capped at PROMISING-WATCHLIST per this task's own rule** — not
tested for grid-shift regardless of its numbers (it would numerically qualify:
both halves N>=20 and positive). **1week is NOT_APPLICABLE**: both GOLD (Twelve
Data) and SILVER (yfinance futures) fetch native, non-resampled 1week candles in
this pipeline — the same "native data, not resampled" reasoning that has capped
every prior metals config in this project (settlement-gap convention).

## Verdict

**0 SURVIVED. 2 of 2 PROMISING-WATCHLIST. 0 DIED.** Per this batch's own explicit
instruction to classify generously toward watch-list wherever a real (if
unproven) signal exists: both timeframes show a consistent, mechanistically
sensible, positive-both-halves signal with a plausible edge-over-random story —
exactly the profile this batch is designed to route toward live forward-testing,
not to demand proof from on a sample this size. **1d is the stronger candidate**
(adequate sample on both halves, N=59/26, vs 1week's thin N=11/6) and is the one
recommended for the promotion list in the closing report.
