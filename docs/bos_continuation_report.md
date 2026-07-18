# BOS_CONTINUATION v1.0.0 — Data Source, Strategy, and Verification Report

## What was built

`nero_core/strategies/bos_detection.py` — a shared, sequential Break-of-Structure pivot
tracker. A candle is a confirmed swing high/low only once the 5 candles both before AND
after it are known (confirmed at `j+5`, never earlier — no lookahead). Only the single
most-recently-confirmed, unbroken pivot is ever "active" per direction; a newer
confirmed pivot immediately supersedes an older one regardless of whether the older one
had broken. Each pivot can trigger at most one BOS signal ever (one-shot). Every
confirmed pivot (not just the active one) is retained so a BOS event can report "the
swing low/high preceding the broken pivot" for stop placement.

`nero_core/strategies/bos_continuation.py` — BOS_CONTINUATION v1.0.0: LONG on a BOS-up
while close > MA200; SHORT (paper-only, mirrored accounting) on a BOS-down while
close < MA200. Stop = the preceding swing low/high ± 0.25x ATR buffer, **capped at 3.0x
ATR total distance** — every trade records which was actually used
(`stop_type`: "structural" or "capped"). Target = 2x the actual (possibly capped) stop
distance. No preceding extreme confirmed yet → no valid stop → entry rejected, never
fabricated.

`tools/backtest_bos_continuation_sweep.py` runs this across 7 crypto assets × {4h,
12h, 24h}, 70/30 split, upgraded harness, plus the structural-vs-capped stop tally per
half. Same random-baseline eligible-pool narrowing as FVG_REVERSION was required here
too (BOS_CONTINUATION's `size_entry` needs the broken pivot's preceding-extreme data,
only non-NaN on an actual BOS candle).

## Results (live Binance data, all 7 assets × 3 timeframes)

| Asset/TF | Verdict | Train N/ExpR | Test N/ExpR | Edge/random (train/test) | Stop split (train) |
|---|---|---|---|---|---|
| BTC/4h | PROMISING-WATCHLIST | 321/0.072 | 141/0.029 | -0.008/+0.002 | 49 struct / 272 capped |
| BTC/12h | DIED | 102/0.165 | 42/-0.070 | -0.022/-0.027 | 20 / 82 |
| BTC/24h | DIED | 40/0.162 | 19/-0.039 *LOW* | -0.014/-0.044 | 2 / 38 |
| ETH/4h | PROMISING-WATCHLIST | 321/0.096 | 123/0.144 | -0.011/+0.011 | 54 / 267 |
| ETH/12h | PROMISING-WATCHLIST | 97/0.208 | 38/0.063 | -0.015/-0.033 | 17 / 80 |
| ETH/24h | DIED | 45/0.250 | 15/-0.061 *LOW* | +0.014/-0.067 | 6 / 39 |
| SOL/4h | DIED | 217/0.159 | 86/-0.082 | +0.003/-0.013 | 37 / 180 |
| SOL/12h | PROMISING-WATCHLIST | 65/0.360 | 25/0.010 | -0.001/-0.071 | 11 / 54 |
| SOL/24h | PROMISING-WATCHLIST | 28/0.434 | 7/0.598 *LOW* | -0.016/+0.160 | 2 / 26 |
| BNB/4h | PROMISING-WATCHLIST | 302/0.093 | 139/0.080 | -0.020/-0.006 | 55 / 247 |
| BNB/12h | PROMISING-WATCHLIST | 91/0.201 | 37/0.084 | -0.028/-0.004 | 14 / 77 |
| BNB/24h | PROMISING-WATCHLIST | 45/0.282 | 16/0.006 *LOW* | -0.017/+0.034 | 3 / 42 |
| XRP/4h | DIED | 292/0.078 | 123/-0.002 | -0.007/+0.005 | 45 / 247 |
| XRP/12h | DIED | 89/0.185 | 40/-0.004 | +0.021/-0.036 | 17 / 72 |
| XRP/24h | PROMISING-WATCHLIST | 44/0.163 | 16/0.299 *LOW* | +0.027/+0.063 | 7 / 37 |
| DOGE/4h | PROMISING-WATCHLIST | 229/0.107 | 105/0.164 | -0.009/-0.001 | 23 / 206 |
| DOGE/12h | PROMISING-WATCHLIST | 69/0.068 | 33/0.100 | +0.017/-0.001 | 8 / 61 |
| DOGE/24h | PROMISING-WATCHLIST | 36/0.194 | 10/0.200 *LOW* | -0.010/+0.040 | 3 / 33 |
| NEAR/4h | DIED | 206/0.075 | 79/-0.014 | +0.004/+0.002 | 35 / 171 |
| NEAR/12h | DIED | 59/0.239 | 26/-0.057 | +0.003/-0.024 | 13 / 46 |
| NEAR/24h | PROMISING-WATCHLIST | 26/0.194 | 11/0.010 *LOW* | -0.001/-0.018 | 5 / 21 |

## Factual read

**13 of 21 configs are PROMISING-WATCHLIST (positive both halves), 8 DIED, 0
SURVIVED** — a notably higher "positive both halves" rate than FVG_REVERSION's 3/21,
but two other findings temper that:

- **The edge over the random-entry baseline is mostly negative or negligible** —
  roughly half of all (asset, timeframe, half) cells show a *negative* edge, meaning
  random entry timing within the same MA200 regime would have done as well or better
  than the specific BOS-up/down trigger. This is a materially weaker signal-quality
  result than FVG_REVERSION's (which was at least consistently small-positive). It
  suggests most of BOS_CONTINUATION's apparent "promise" comes from the regime filter
  and exit/sizing mechanics (an uptrend-following long bias with an ATR-based stop and
  2x-stop target), not from the structure-break entry timing itself.
- **The capped 3.0x ATR stop dominates over the structural stop almost everywhere** —
  typically 75-95% of trades use the cap, not the preceding swing point. The "swing low
  preceding the broken high" is usually farther away than 3x ATR, so in practice this
  strategy is closer to "enter on a BOS-up/down with a fixed 3x-ATR stop and 6x-ATR
  target" than "enter with a structurally-derived stop" — worth noting for anyone
  reading "BOS_CONTINUATION" as primarily a structure-based risk model.
- Several PROMISING-WATCHLIST test halves are LOW SAMPLE (BTC/24h, ETH/24h, SOL/24h,
  BNB/24h, XRP/24h, DOGE/24h, NEAR/24h) — every 24h config's test half has under 20
  trades, a direct consequence of daily candles simply producing fewer signals in a
  30%-of-history test window.

**Bottom line: BOS_CONTINUATION classifies as PROMISING-WATCHLIST on more configs than
FVG_REVERSION, but its random-entry edge is weaker and often negative** — the higher
"positive both halves" rate looks more attributable to the regime filter than to the
break-of-structure trigger itself. None of the 21 configs SURVIVED the strict bar.
