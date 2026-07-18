# Task C — Filter Test on the Existing Survivor (BNB/12h TREND_PULLBACK)

## What was built

Two new registered versions, both reusing TREND_PULLBACK's `size_entry` and
`evaluate_exit` **completely unchanged** — only an extra entry precondition is added:

- **`trend-pullback-v1.3.0-fvg-filtered`**: requires at least one OPEN bullish FVG
  (Task A's `nero_core.strategies.fvg_detection`) whose remaining zone overlaps the
  low-to-high range of the last 10 candles.
- **`trend-pullback-v1.4.0-bos-filtered`**: requires at least one BOS-up (Task B's
  `nero_core.strategies.bos_detection`) within the last 20 candles.

`tools/backtest_trend_pullback_filter_ab_report.py` compares both against unfiltered
v1 on identical BNB/12h data, 70/30 split, through the upgraded harness.

## Results (live Binance data, BNB/12h, 6351 candles)

| Variant | Split | N | ExpR | AvgWinR | AvgLossR | Win% | PF | MaxDD | CI | Edge/random |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 (unfiltered) | Train | 57 | 0.147 | 1.271 | -1.017 | 50.9% | 1.27 | -11.6% | crosses zero | +0.215 |
| v1 (unfiltered) | Test | 30 | 0.243 | 1.186 | -0.991 | 56.7% | 1.55 | -3.7% | crosses zero | +0.181 |
| fvg-filtered | Train | 32 | 0.168 | 1.296 | -0.960 | 50.0% | 1.33 | -5.9% | crosses zero | **+0.241** |
| fvg-filtered | Test | 12 *LOW SAMPLE* | 0.095 | 1.116 | -0.926 | 50.0% | 1.19 | -3.2% | crosses zero | +0.038 |
| bos-filtered | Train | 57 | 0.147 | 1.271 | -1.017 | 50.9% | 1.27 | -11.6% | crosses zero | +0.215 |
| bos-filtered | Test | 30 | 0.243 | 1.186 | -0.991 | 56.7% | 1.55 | -3.7% | crosses zero | +0.181 |

## Factual read

**bos-filtered produced IDENTICAL results to unfiltered v1** — same trade count, same
every metric, on both halves. The filter (at least one BOS-up within the last 20
candles) never once rejected a trade that v1 would otherwise have taken on this
asset/timeframe/window — it did not shrink the sample, and consequently could not have
changed quality either. Verified in isolation via unit tests
(`tests/test_trend_pullback_bos_filtered.py`) that the filter mechanism CAN reject when
its conditions genuinely aren't met — on this real data, they simply always were met
whenever the base strategy would have entered anyway. This is itself informative: BOS-up
events are frequent enough on BNB/12h that a 20-candle recency window is essentially
always satisfied during this strategy's actual entry windows.

**fvg-filtered materially shrank the sample** (57→32 train, 30→12 test — roughly
halved) and the result is mixed, not a clean improvement:

- Train-half edge over random improved modestly (+0.241 vs v1's +0.215), and max
  drawdown improved noticeably (-5.9% vs -11.6%).
- Test-half ExpR is WORSE than v1's (0.095 vs 0.243), and the sample is now a LOW
  SAMPLE (12 trades) — too small to draw a real conclusion from, and the edge over
  random on test collapsed to near zero (+0.038 vs v1's +0.181).
- Win% and profit factor are essentially unchanged from v1 on both halves.

**Bottom line: neither filter clearly raises per-trade quality.** The BOS filter is
functionally a no-op on this data (shrinks nothing, so obviously changes nothing). The
FVG filter meaningfully shrinks the sample and shows a mild in-sample improvement in
drawdown and random-edge, but its out-of-sample expectancy and random-edge are both
weaker than v1's, on a sample too small to trust either way. Neither filtered variant
is recommended to replace v1 in the live scheduler based on this evidence.
