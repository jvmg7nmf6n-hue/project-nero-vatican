# Comprehensive Asset Expansion, Part A: Stocks — Task A2 Full Strategy Sweep

Tool: `tools/backtest_stocks_task_a2_sweep.py`. All 30 symbols (SPY/QQQ/IWM + 27
stocks), all 9 strategies per the task's timeframe mapping, flat 0.1%/side fee (per
spec, not a derived price/ATR scale factor), chronological 70/30 split, bootstrap 95%
CI + random-entry baseline, `classify_verdict`. Full raw output in
`docs/stock_task_a2_full_sweep_raw_output.txt`.

**Every single result below carries the permanent survivorship-bias caveat from Task
A1**: yfinance only serves currently-listed tickers, so this 27-stock universe cannot
see any company that was delisted, went bankrupt, or was acquired away. SPY/QQQ/IWM
are the bias-free reference set.

## Headline result

**937 of 939 configs completed** (0 fetch failures; 2 rows in the raw count are the
`=== N configs qualify ===` summary lines, not configs). **764 DIED (81.5%), 173
PROMISING-WATCHLIST (18.5%).**

**2 configs cleared EVERY statistical bar pre-grid-shift** — positive both halves,
adequate sample, bootstrap CI clears zero on both halves — and were classified
`SURVIVED` by `classify_verdict` before the mandatory grid-shift step:

| Config | TRAIN | TEST |
|---|---|---|
| AAPL / 1week / BREAKOUT_MOMENTUM | N=95, ExpR=0.296 | N=43, ExpR=0.419 |
| AAPL / 1day / BOS_CONTINUATION | N=202, ExpR=0.324 | N=85, ExpR=0.224 |

**Both are demoted to PROMISING-WATCHLIST — grid-shift cannot be run on either.** Of
the 56 configs qualifying for grid-shift consideration (positive both halves, N>=20
both halves), 55 are at 1day/1week (native yfinance daily/weekly data — no arbitrary
UTC boundary to re-test, the same structural exception established for metals'
settlement gap and forex's Friday-close gap) and the single remaining one
(MSTR/1h/FVG_REVERSION) is at **native** 1h — not a resampled timeframe the way 4h is
for stocks, so there is no finer-grained source to re-derive it from at a different
offset either. **Zero of the 56 qualifying configs are actually grid-shift testable.
No stock config reaches SURVIVED in this task.**

This is a genuinely different outcome from Asset Expansion Phase A (metals), where 1
of 9 qualifying configs WAS testable (PLATINUM/2h/VOLATILITY_SQUEEZE, a genuinely
resampled timeframe) and failed its shift test. Here, stocks' *only* resampled
timeframe is 4h, and exactly 0 of the 173 PROMISING-WATCHLIST configs are at 4h with
an adequate sample — the near-miss survivors cluster at native daily/weekly
resolution instead, where the grid-shift question doesn't apply at all.

## Sweet-spot timeframe: 1day and 1week, overwhelmingly

Of 173 PROMISING-WATCHLIST configs: 82 at 1week, 75 at 1day, 14 at 1h, 2 at 4h. **91%
of all positive-both-halves signals are at daily/weekly resolution** — the same
pattern forex just showed (predominantly 1week) and metals showed (24h) in earlier
phases. Intraday stock trading (1h/4h) essentially does not produce
positive-both-halves signals in this sweep.

## Per-strategy breakdown (PROMISING-WATCHLIST count out of configs tested)

| Strategy | PROMISING-WATCHLIST |
|---|---|
| MEAN_REVERSION v1 | 29 |
| BOS_CONTINUATION | 26 |
| TREND_PULLBACK | 24 |
| VOLATILITY_SQUEEZE ma100 | 18 |
| BREAKOUT_MOMENTUM | 17 |
| VOLATILITY_SQUEEZE ma200 | 16 |
| DONCHIAN_TREND | 16 (of 30 tested — the highest HIT RATE of any family) |
| VOLATILITY_SQUEEZE ma150 | 15 |
| FVG_REVERSION | 9 |
| COINTEGRATION_PAIRS | 2 (of 6) |
| MACRO_RISK_ON | 1 (of 3) |

**DONCHIAN_TREND stands out**: 16 of its 30 single-timeframe (1week-only) configs are
PROMISING-WATCHLIST — a 53% hit rate, far above every other family. This echoes
DONCHIAN's consistent 1week signal across GOLD (its original design target), SILVER,
and PLATINUM in Asset Expansion Phase A — a fourth asset class now showing the same
pattern for the same strategy at the same timeframe. Still sample-limited in most
cases and never reaching SURVIVED, but a striking cross-asset-class consistency worth
carrying into future research.

**FVG_REVERSION continues its clean cross-asset failure** (9 of 90 configs
PROMISING-WATCHLIST, 81 DIED) — a fourth asset class (after crypto, metals, forex)
where this family mostly doesn't work, though unlike forex (0/30) it isn't a
*total* wipeout here.

## MACRO_RISK_ON: only QQQ shows promise

Applied to the 3 index ETFs only (see Task A2's own scope note — testing all 27
individual stocks against a shared macro regime signal wasn't asked for and would
have multiplied the sweep sevenfold for limited additional insight). SPY DIED
(train negative, test barely positive), IWM DIED (same pattern), **QQQ
PROMISING-WATCHLIST** (TRAIN N=159 ExpR=0.010, TEST N=102 ExpR=0.076 — the
best-sampled MACRO_RISK_ON result of the three, though ExpR itself is thin). A
tech-heavy index showing more sensitivity to the dollar/real-yield regime than a
small-cap (IWM) or broad-market (SPY) index is a plausible, non-arbitrary pattern —
not over-claimed given the thin train-half ExpR.

## COINTEGRATION_PAIRS: same weak, sample-limited character as every prior asset class

2 of 6 configs (both timeframes for one pair) PROMISING-WATCHLIST; full results in the
raw output. Consistent with BTC-ETH, Gold-Silver, Silver-Platinum, and the forex
crosses already tested — this family's edge (where any exists) is real but
persistently thin across every asset class tried so far.

## Top 3 qualifying configs by test-half ExpR (used for Task A3)

| Config | TRAIN | TEST |
|---|---|---|
| INTU / 1day / MEAN_REVERSION v1 | N=39, ExpR=0.097 | N=20, ExpR=0.767 |
| NVDA / 1week / BREAKOUT_MOMENTUM | N=48, ExpR=0.281 | N=21, ExpR=0.687 |
| AAPL / 1week / BREAKOUT_MOMENTUM | N=95, ExpR=0.296 | N=43, ExpR=0.419 |

## Summary

- **939 configs tested (937 with a distinct verdict), 0 SURVIVED, 173
  PROMISING-WATCHLIST (81.5% DIED)** — within this project's expected survival-rate
  range, though the PROMISING-WATCHLIST share (18.5%) is notably higher than forex's
  7.5% or metals' earlier rate, driven mostly by DONCHIAN_TREND's unusually high hit
  rate.
- **2 configs cleared every bar except grid-shift applicability** (AAPL/1week/
  BREAKOUT_MOMENTUM, AAPL/1day/BOS_CONTINUATION) — the closest this task comes to a
  real survivor, blocked purely by the structural fact that daily/weekly stock data
  has no arbitrary boundary to re-test, not by any weakness in the result itself.
- **Sweet-spot timeframe: 1day/1week** (91% of promising configs) — matching forex and
  metals, not crypto's faster 12h/2h cadence.
- **DONCHIAN_TREND's cross-asset consistency continues** into a 4th asset class.
- Recommended for Task A3: INTU/1day/MEAN_REVERSION v1, NVDA/1week/BREAKOUT_MOMENTUM,
  AAPL/1week/BREAKOUT_MOMENTUM (top 3 by test-half ExpR among the qualifying pool).
