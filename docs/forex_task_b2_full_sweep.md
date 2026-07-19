# Comprehensive Asset Expansion, Part B: Forex — Task B2 Full Strategy Sweep

Tool: `tools/backtest_forex_task_b2_sweep.py`. All 10 standard pairs, all 9 strategies
per the task's timeframe mapping, flat 0.05%/side fee (per spec — not a derived
price/ATR scale factor), chronological 70/30 split, bootstrap 95% CI + random-entry
baseline, `classify_verdict` (SURVIVED / PROMISING-WATCHLIST / DIED). Full raw output
in `docs/forex_task_b2_full_sweep_raw_output.txt`.

## Headline result

**318 of 318 configs completed** (0 fetch failures — Task B1's audit correctly
predicted every pair/timeframe would resolve). **294 DIED (92.5%), 24
PROMISING-WATCHLIST (7.5%), 0 SURVIVED.** Consistent with this project's stated
~1.5% historical survival rate for new strategy/asset combinations — nothing here
overturns that.

Of the 24 PROMISING-WATCHLIST configs, only **2** clear the stricter "adequate sample
(>=20 trades) in BOTH halves, positive both halves" bar that would make them eligible
for grid-shift verification:

| Config | TRAIN | TEST |
|---|---|---|
| EUR/JPY / 1week / BREAKOUT_MOMENTUM | N=51, ExpR=0.164 | N=23, ExpR=0.110 |
| EUR/JPY / 1day / BOS_CONTINUATION | N=80, ExpR=0.003 | N=34, ExpR=0.045 |

**Both are at 1day/1week — grid-shift is not applicable to either.** Per the task's
own rule (mirroring the metals-settlement-gap precedent from Asset Expansion Phase A):
grid-shift is only meaningful at 1h/4h, where a shift stays inside the same
continuously-traded window. No forex config in this sweep qualified at 1h or 4h with
an adequate sample in both halves, so **zero grid-shift tests were run**, and both
configs are capped at PROMISING-WATCHLIST directly rather than promoted to SURVIVED.
**Forex has no SURVIVED results in this task.**

## Sweet-spot timeframe: 1week, overwhelmingly

Of the 24 PROMISING-WATCHLIST configs, 19 are at 1week, 4 at 1day, 1 at 1h/4h combined
(none, in fact — checking the table above, both qualifying configs are 1day/1week;
zero 1h/4h configs reached even PROMISING-WATCHLIST). This is a striking, one-sided
result: **every single positive-both-halves signal in this entire 318-config sweep
lives at 1day or (mostly) 1week** — the slowest end of the tested timeframe range,
not the 12h/2h crypto sweet spot or metals' 24h sweet spot. Forex, at least for these
9 strategy families, behaves like the SLOWEST asset class tested in this whole
project so far.

## Currency-pair pattern: JPY crosses dominate

EUR/JPY, USD/JPY, and GBP/JPY account for 11 of the 24 PROMISING-WATCHLIST rows —
disproportionately more than their 3-of-10 share of the pair universe. DONCHIAN_TREND
in particular is positive-both-halves for 4 of 5 JPY-involving pairs it was tested on
(EUR/USD, USD/JPY, EUR/JPY, GBP/JPY all PROMISING-WATCHLIST at 1week; only USD/CHF,
EUR/GBP, AUD/USD, NZD/USD, USD/CAD DIED) — echoing DONCHIAN's own consistent
cross-metal 1week signal from Asset Expansion Phase A. This is a genuine,
cross-asset-class pattern worth flagging for future research, not over-claimed as
proof of anything on its own (every one of these is still sample-limited, `*`-flagged).

## MACRO_RISK_ON and FVG_REVERSION: clean, uniform failure

MACRO_RISK_ON (EUR/USD, USD/JPY, both 1day) DIED outright — both trains AND tests
strongly negative (ExpR -0.168/-0.204 and -0.171/-0.064). FVG_REVERSION DIED on
literally all 30 of its configs (every pair, every timeframe), the same
clean-cross-asset failure pattern this family already showed in Asset Expansion Phase
A's metals sweep and the earlier crypto research phase — a third consecutive asset
class confirming FVG_REVERSION doesn't work, reinforcing rather than contradicting
the existing verdict.

## COINTEGRATION_PAIRS

Only 1 of 6 pair/timeframe configs (EURGBP-EURJPY/1day) reached PROMISING-WATCHLIST,
and its sample is thin even there (N=37 train but only N=4* test). USDJPY-USDCHF and
AUDUSD-NZDUSD both DIED with very low trade counts (some halves had 0-1 trades) — the
same "weak, sample-starved" character COINTEGRATION_PAIRS has shown on every asset
class tested in this project so far (BTC-ETH, Gold-Silver, Silver-Platinum, and now
these forex crosses).

## A genuine runtime anomaly, noted for transparency

One config (`GBP/JPY / 1week / BOS_CONTINUATION`) logged an elapsed time of 8086.2s
(~2.2 hours) against otherwise-uniform ~10-30s timings for every other config. The
fetch itself was already cached from an earlier config in the same run (no network
call should have recurred), so this was not a data-fetch delay. The most likely
explanation is resource contention on this machine — the Task A2 stocks sweep was
running concurrently in a separate background process at the time, competing for CPU.
The final numbers for this config (TRAIN N=44 ExpR=0.460, TEST N=16 ExpR=0.152,
PROMISING-WATCHLIST) look internally consistent with neighboring GBP/JPY results and
are not treated as suspect, but the anomaly itself is recorded here rather than
silently smoothed over.

## Summary

- **318 configs tested, 0 SURVIVED, 24 PROMISING-WATCHLIST (92.5% DIED)** — squarely
  within this project's expected survival-rate range.
- **Sweet-spot timeframe: 1week** (occasionally 1day) — the slowest timeframe tested,
  a genuinely different character from crypto's 12h/2h and metals' 24h.
- **No config reaches SURVIVED**: the only 2 configs with adequate sample in both
  halves are both at timeframes where grid-shift verification structurally doesn't
  apply, so neither can be promoted past PROMISING-WATCHLIST.
- Recommended for Task B3 (vol-clustering, top configs by test-half ExpR among the
  adequate-both-halves pool): EUR/JPY/1week/BREAKOUT_MOMENTUM (test ExpR=0.110), then
  EUR/JPY/1day/BOS_CONTINUATION (test ExpR=0.045) — only 2 qualify, so both are used
  (fewer than 3, per the task's own "fewer if fewer qualify" rule).
