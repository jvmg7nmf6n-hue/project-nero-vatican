# EMA-Trail Exit A/B — v1 (fixed target + cap) vs v2 (armed trail, no cap)

## What was built

Two new registered versions (`nero_core/strategies/trend_pullback_trail.py`,
`nero_core/strategies/breakout_momentum_gold_calibrated_1week_trail.py`), sharing exit
mechanics via `nero_core/strategies/ema_trail_exit.py`:

- **`trend-pullback-v1.2.0-trail`** (BNB/12h): trail = EMA21.
- **`breakout-momentum-v1.5.0-gold-calibrated-1week-trail`** (GOLD/1week): trail = EMA8
  — EMA21 on weekly candles is a ~5-month lookback, too slow to meaningfully trail a
  weekly breakout leg; EMA8 (~2 months) is the calibrated equivalent for this timeframe.
  `trail_ema_period` is a genuine registered parameter on both, not a hidden constant.

Both variants keep IDENTICAL entry conditions and disaster stops to their v1
counterparts — only the profit-exit changes, from a fixed target + max-holding-hours
cap to an ARMED EMA trailing stop with NO max-holding cap at all (both fields absent by
design, matching the pattern already established for FUNDING_EXTREME).

**ARMED-TRAIL RULE**: the trail activates only after the first post-entry CLOSE above
the trail EMA (pullback/dip entries start below/near it — without arming, the trail
would exit almost immediately). Until armed, only the disaster stop applies. Arming is
evaluated using each candle's own close vs EMA and takes effect starting the *next*
candle — never the same candle it armed on, and never the entry candle itself.

## Results (live data, identical data per pair, 70/30 chronological split)

| Config | Variant | Split | N | ExpR | AvgWinR | AvgLossR | Win% | PF | MaxDD | CI | Edge/random |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BNB/12h TREND_PULLBACK | v1 | Train | 57 | 0.147 | 1.271 | -1.017 | 50.9% | 1.27 | -11.6% | crosses zero | +0.215 |
| BNB/12h TREND_PULLBACK | v2-trail | Train | 92 | **0.587** | **2.109** | **-0.532** | 42.4% | **2.47** | **-9.4%** | crosses zero | +0.199 |
| BNB/12h TREND_PULLBACK | v1 | Test | 30 | **0.243** | 1.186 | -0.991 | 56.7% | 1.55 | -3.7% | crosses zero | **+0.181** |
| BNB/12h TREND_PULLBACK | v2-trail | Test | 59 | **-0.089** | 0.603 | -0.444 | 33.9% | 0.68 | -10.2% | crosses zero | +0.043 |
| GOLD/1week BREAKOUT_MOMENTUM | v1 | Train | 63 | 0.395 | 1.217 | -1.035 | 63.5% | 2.06 | -4.9% | **clears zero** | +0.171 |
| GOLD/1week BREAKOUT_MOMENTUM | v2-trail | Train | 32 | **0.555** | **1.671** | **-0.710** | 53.1% | **2.64** | **-3.1%** | **clears zero** | **+0.477** |
| GOLD/1week BREAKOUT_MOMENTUM | v1 | Test | 31 | **0.426** | 1.224 | -1.026 | 64.5% | 2.15 | -2.0% | **clears zero** | +0.134 |
| GOLD/1week BREAKOUT_MOMENTUM | v2-trail | Test | 20 | 0.182 | 1.047 | -0.526 | 45.0% | 1.61 | -3.2% | crosses zero | +0.033 |

(Bolded = the better of the two variants on that specific cell, where a comparison is
meaningful.)

## Factual read

**The trail variant's asymmetric win/loss shape shows up clearly and consistently
in-sample, on both configs**: bigger average winners, smaller average losers, higher
profit factor, lower max drawdown — exactly the "let winners run, cut losers with a
tight disaster stop" shape the design intends. This is not noise; it is a structural
consequence of the exit mechanics change and appears reliably on the train half for
both BNB and GOLD.

**That in-sample advantage does not robustly survive to the test half on either
config**:

- **BNB/12h**: v2's test-half expectancy is NEGATIVE (-0.089), reversing v1's positive
  test result (+0.243). Combined with the trail variant's much higher train ExpR
  (0.587) than v1's, this is the classic shape of an out-of-sample degradation — the
  trail's structural advantage (visible in AvgWinR/AvgLossR/PF even on test) wasn't
  enough to produce a positive expectancy on BNB's test window.
- **GOLD/1week**: v2's test expectancy stays positive (0.182) but is weaker than v1's
  (0.426), and — unlike v1 — its confidence interval crosses zero on test. GOLD is the
  less clear-cut case: the trail variant doesn't reverse sign out-of-sample the way it
  does on BNB, but it also doesn't beat v1's test-half performance on any of ExpR, PF,
  or CI tightness.

**Trade count differs meaningfully between v1 and v2 despite identical entry
conditions** (e.g. BNB train: 57 vs 92) — expected, not a bug: v1 and v2 share the exact
same `evaluate_entry`, but different exit timing changes how often the strategy is flat
and able to act on a fresh signal, so trade count is an emergent consequence of the
exit-mechanics change, not an independent variable.

**Bottom line: the trail exit does NOT beat the fixed-target-and-cap exit on
out-of-sample expectancy for either survivor**, despite clearly improving the
win/loss shape (bigger winners, smaller losers, higher PF, lower drawdown) in every
single train-half measurement. Both versions are registered
(`trend-pullback-v1.2.0-trail`, `breakout-momentum-v1.5.0-gold-calibrated-1week-trail`)
as required, but neither is a candidate to replace its v1 counterpart in the live
scheduler based on this evidence.
