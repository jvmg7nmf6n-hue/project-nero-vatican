# FVG_REVERSION v1.0.0 — Data Source, Strategy, and Verification Report

## What was built

`nero_core/strategies/fvg_detection.py` — a shared, sequential Fair Value Gap
lifecycle tracker: gap formation (bullish `low[i] > high[i-2]`, bearish
`high[i] < low[i-2]`), partial fills (the untested zone ratchets toward whichever side
price has revisited), full fills (gap dies), 100-candle expiry, a 5-open-gaps-per-
direction cap (oldest evicted first), and a strict one-signal-per-gap-ever rule (the
first candle to touch a gap's zone consumes its only shot, regardless of whether some
other filter later turns it into a real entry — documented as a deliberate, spec-
faithful reading of "first touch only," since the spec doesn't pin down what happens
when a first touch fails an additional filter).

`nero_core/strategies/fvg_reversion.py` — FVG_REVERSION v1.0.0: LONG on the first touch
of an open bullish gap while close > MA200; SHORT (paper-only, mirrored accounting —
see `short_momentum.py`) on the first touch of an open bearish gap while close < MA200.
Stop = the gap's far zone boundary ± 0.5x ATR(14); target = 1.5x that stop distance.
Timeframe-aware max holding, standard 1% sizing/fees.

`tools/backtest_fvg_reversion_sweep.py` runs this across 7 crypto assets × {2h, 4h,
12h}, 70/30 chronological split, through the upgraded harness (bootstrap 95% CI +
random-entry baseline). The random-entry baseline's eligible pool had to be narrowed to
"candles with an actual touch signal" rather than "any candle in the MA200 regime" —
`size_entry` needs the specific touched gap's own zone data, which is NaN everywhere
else, so a broad regime pool would produce NaN geometries. Documented in both the tool
and a regression test.

## Results (live Binance data, all 7 assets × 3 timeframes)

| Asset/TF | Verdict | Train N / ExpR | Test N / ExpR | Edge over random (train/test) |
|---|---|---|---|---|
| BTC/2h | DIED | 891 / -0.104 | 469 / -0.145 | +0.002 / +0.002 |
| BTC/4h | DIED | 473 / 0.044 | 240 / -0.230 | +0.001 / -0.011 |
| BTC/12h | DIED | 178 / 0.128 | 85 / -0.108 | +0.012 / +0.007 |
| ETH/2h | DIED | 1042 / -0.036 | 465 / -0.115 | +0.003 / +0.004 |
| ETH/4h | DIED | 540 / -0.037 | 234 / -0.071 | +0.001 / +0.006 |
| ETH/12h | DIED | 178 / 0.260 | 73 / -0.117 | +0.015 / +0.028 |
| SOL/2h | DIED | 749 / -0.039 | 327 / -0.158 | +0.001 / +0.008 |
| SOL/4h | DIED | 381 / 0.003 | 151 / -0.108 | +0.001 / +0.010 |
| **SOL/12h** | **PROMISING-WATCHLIST** | 111 / 0.165 | 51 / 0.048 | +0.032 / +0.004 |
| BNB/2h | DIED | 1043 / -0.109 | 445 / -0.152 | +0.003 / +0.003 |
| BNB/4h | DIED | 496 / -0.058 | 232 / -0.087 | -0.002 / +0.003 |
| BNB/12h | DIED | 163 / -0.002 | 71 / -0.155 | +0.007 / -0.006 |
| XRP/2h | DIED | 861 / -0.041 | 409 / -0.091 | +0.002 / -0.004 |
| XRP/4h | DIED | 431 / -0.011 | 193 / -0.091 | +0.000 / -0.011 |
| **XRP/12h** | **PROMISING-WATCHLIST** | 134 / 0.104 | 62 / 0.111 | +0.006 / -0.001 |
| DOGE/2h | DIED | 705 / -0.101 | 346 / -0.039 | +0.000 / -0.003 |
| DOGE/4h | DIED | 331 / 0.006 | 173 / -0.024 | +0.007 / +0.004 |
| DOGE/12h | DIED | 122 / 0.094 | 57 / -0.086 | +0.006 / +0.021 |
| NEAR/2h | DIED | 741 / 0.014 | 317 / -0.078 | -0.001 / -0.001 |
| NEAR/4h | DIED | 373 / 0.081 | 149 / -0.075 | +0.003 / +0.003 |
| **NEAR/12h** | **PROMISING-WATCHLIST** | 116 / 0.003 | 42 / 0.233 | +0.003 / +0.031 |

## Factual read

**18 of 21 configs DIED** (negative or flat expectancy on at least one half). **3 of 21
are PROMISING-WATCHLIST** — SOL/12h, XRP/12h, NEAR/12h — **none SURVIVED**. Every single
promising config is on the 12h timeframe; the strategy DIED on 100% of 2h and 4h
configs across all 7 assets, a clean and consistent pattern rather than scattered noise.

**The edge over the random-entry baseline is negligible almost everywhere** — mostly in
the ±0.01 range, occasionally reaching +0.02 to +0.03 on the three watchlist configs.
This is the most important number in this report: even where FVG_REVERSION shows a
positive point estimate, it is barely distinguishable from randomly-timed entries in
the same MA200 regime. The specific "first touch of an open gap" trigger is not adding
meaningful value over random timing on this evidence.

**Bottom line: FVG_REVERSION v1.0.0 is a weak strategy on this evidence.** The 3
watchlist configs (all 12h) are eligible for live forward-testing per this batch's
verdict rules (positive both halves), but the near-zero random-entry edge across the
whole sweep — including the watchlist configs — is a genuine caution, not just a
sample-size artifact.
