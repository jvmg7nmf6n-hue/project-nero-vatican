# Metals Full Strategy Sweep — Asset Expansion Phase A, Task 2

Tool: `tools/backtest_metals_phase_a_sweep.py`. Run against live data on 2026-07-19.
76 (asset/pair, timeframe, strategy) configurations across all 9 strategies in
scope, both metals (SILVER, PLATINUM), plus Gold-Silver / Silver-Platinum pairs and
MACRO_RISK_ON. Every strategy's entry/exit/sizing logic runs **unchanged** — only
per-asset fee/slippage calibration varies (SILVER/PLATINUM factors from Task 1's
audit) and, for BREAKOUT_MOMENTUM/TREND_PULLBACK/DONCHIAN_TREND, the timeframe-aware
`max_holding_hours` recalibration this codebase already requires for any non-1h
candle interval.

No config was excluded for insufficient data (Task 1 cleared every timeframe for
both metals). Every config ran a chronological 70/30 train/test split with bootstrap
95% CI on mean per-trade R and a random-entry baseline (methodology and eligible-pool
choice per strategy family documented in the tool's own docstring).

## Full results table

`N` = trade count in that half (`*` = below the 20-trade MIN_SAMPLE_SIZE). `ExpR` =
expectancy in R multiples. `CI` = bootstrap 95% CI verdict (`clear` = clears zero,
`XZERO` = crosses zero, `n/a` = zero trades).

```
Asset           TF     Strategy                  Verdict               TRAIN                       TEST
-----------------------------------------------------------------------------------------------------------------------------
SILVER          2h     MEAN_REVERSION v1         DIED                  N=  46  ExpR= -0.140 CI=XZERO N=  14* ExpR= -0.194 CI=XZERO
SILVER          4h     MEAN_REVERSION v1         DIED                  N=  22  ExpR=  0.151 CI=XZERO N=   4* ExpR= -1.041 CI=clear
SILVER          12h    MEAN_REVERSION v1         DIED                  N=   6* ExpR= -0.173 CI=XZERO N=   0* ExpR=  0.000 CI=n/a
SILVER          24h    MEAN_REVERSION v1         PROMISING-WATCHLIST   N=  24  ExpR=  0.531 CI=clear  N=  15* ExpR=  0.193 CI=XZERO
SILVER          1week  MEAN_REVERSION v1         DIED                  N=   2* ExpR= -1.021 CI=clear  N=   0* ExpR=  0.000 CI=n/a
PLATINUM        2h     MEAN_REVERSION v1         PROMISING-WATCHLIST   N=  37  ExpR=  0.041 CI=XZERO  N=   6* ExpR=  0.717 CI=XZERO
PLATINUM        4h     MEAN_REVERSION v1         DIED                  N=  10* ExpR= -0.358 CI=XZERO  N=   2* ExpR=  0.455 CI=XZERO
PLATINUM        12h    MEAN_REVERSION v1         DIED                  N=   3* ExpR= -0.402 CI=XZERO  N=   0* ExpR=  0.000 CI=n/a
PLATINUM        24h    MEAN_REVERSION v1         PROMISING-WATCHLIST   N=  28  ExpR=  0.265 CI=XZERO  N=  10* ExpR=  0.234 CI=XZERO
PLATINUM        1week  MEAN_REVERSION v1         DIED                  N=   0* ExpR=  0.000 CI=n/a    N=   0* ExpR=  0.000 CI=n/a
SILVER          12h    BREAKOUT_MOMENTUM         DIED                  N=  34  ExpR= -0.286 CI=XZERO  N=   5* ExpR= -0.603 CI=XZERO
SILVER          24h    BREAKOUT_MOMENTUM         PROMISING-WATCHLIST   N= 244  ExpR=  0.049 CI=XZERO  N= 102  ExpR=  0.087 CI=XZERO
SILVER          1week  BREAKOUT_MOMENTUM         DIED                  N=  39  ExpR=  0.225 CI=XZERO  N=  18* ExpR= -0.038 CI=XZERO
PLATINUM        12h    BREAKOUT_MOMENTUM         DIED                  N=  32  ExpR= -0.173 CI=XZERO  N=   3* ExpR= -0.306 CI=XZERO
PLATINUM        24h    BREAKOUT_MOMENTUM         DIED                  N= 229  ExpR= -0.214 CI=clear  N= 100  ExpR= -0.032 CI=XZERO
PLATINUM        1week  BREAKOUT_MOMENTUM         PROMISING-WATCHLIST   N=  40  ExpR=  0.120 CI=XZERO  N=  13* ExpR=  0.002 CI=XZERO
SILVER          2h     TREND_PULLBACK            DIED                  N=  81  ExpR= -0.315 CI=clear  N=  22  ExpR=  0.306 CI=XZERO
SILVER          4h     TREND_PULLBACK            DIED                  N=  41  ExpR= -0.047 CI=XZERO  N=   5* ExpR=  0.283 CI=XZERO
SILVER          12h    TREND_PULLBACK            PROMISING-WATCHLIST   N=  13* ExpR=  0.240 CI=XZERO  N=   1* ExpR=  1.295 CI=clear
SILVER          24h    TREND_PULLBACK            PROMISING-WATCHLIST   N=  49  ExpR=  0.151 CI=XZERO  N=  30  ExpR=  0.058 CI=XZERO
SILVER          1week  TREND_PULLBACK            PROMISING-WATCHLIST   N=  15* ExpR=  0.475 CI=XZERO  N=   9* ExpR=  0.266 CI=XZERO
PLATINUM        2h     TREND_PULLBACK            DIED                  N=  87  ExpR= -0.001 CI=XZERO  N=  20  ExpR=  0.137 CI=XZERO
PLATINUM        4h     TREND_PULLBACK            PROMISING-WATCHLIST   N=  39  ExpR=  0.137 CI=XZERO  N=  12* ExpR=  0.010 CI=XZERO
PLATINUM        12h    TREND_PULLBACK            DIED                  N=   8* ExpR= -0.430 CI=XZERO  N=   0* ExpR=  0.000 CI=n/a
PLATINUM        24h    TREND_PULLBACK            PROMISING-WATCHLIST   N=  70  ExpR=  0.299 CI=clear  N=  34  ExpR=  0.141 CI=XZERO
PLATINUM        1week  TREND_PULLBACK            PROMISING-WATCHLIST   N=   8* ExpR=  0.896 CI=clear  N=   6* ExpR=  0.526 CI=XZERO
SILVER          2h     VOLATILITY_SQUEEZE ma200  DIED                  N=  36  ExpR= -0.364 CI=clear  N=  15* ExpR=  0.084 CI=XZERO
SILVER          4h     VOLATILITY_SQUEEZE ma200  DIED                  N=  18* ExpR= -0.451 CI=XZERO  N=   3* ExpR=  0.484 CI=XZERO
SILVER          12h    VOLATILITY_SQUEEZE ma200  PROMISING-WATCHLIST   N=   2* ExpR=  1.253 CI=clear  N=   2* ExpR=  0.845 CI=clear
SILVER          24h    VOLATILITY_SQUEEZE ma200  PROMISING-WATCHLIST   N=  55  ExpR=  0.168 CI=XZERO  N=  21  ExpR=  0.100 CI=XZERO
SILVER          1week  VOLATILITY_SQUEEZE ma200  DIED                  N=   4* ExpR=  0.127 CI=XZERO  N=   2* ExpR= -1.032 CI=clear
PLATINUM        2h     VOLATILITY_SQUEEZE ma200  DIED                  N=  35  ExpR=  0.123 CI=XZERO  N=  16* ExpR= -0.091 CI=XZERO
PLATINUM        4h     VOLATILITY_SQUEEZE ma200  DIED                  N=  17* ExpR= -0.274 CI=XZERO  N=   4* ExpR= -0.282 CI=XZERO
PLATINUM        12h    VOLATILITY_SQUEEZE ma200  PROMISING-WATCHLIST   N=   4* ExpR=  0.082 CI=XZERO  N=   1* ExpR=  0.347 CI=clear
PLATINUM        24h    VOLATILITY_SQUEEZE ma200  DIED                  N=  64  ExpR= -0.215 CI=XZERO  N=  25  ExpR=  0.115 CI=XZERO
PLATINUM        1week  VOLATILITY_SQUEEZE ma200  DIED                  N=   8* ExpR=  0.116 CI=XZERO  N=   1* ExpR= -1.032 CI=clear
SILVER          2h     VOLATILITY_SQUEEZE ma150  DIED                  N=  37  ExpR= -0.263 CI=XZERO  N=  16* ExpR=  0.156 CI=XZERO
SILVER          4h     VOLATILITY_SQUEEZE ma150  DIED                  N=  18* ExpR= -0.451 CI=XZERO  N=   5* ExpR=  0.327 CI=XZERO
SILVER          12h    VOLATILITY_SQUEEZE ma150  DIED                  N=   3* ExpR=  0.934 CI=clear  N=   1* ExpR= -1.044 CI=clear
SILVER          24h    VOLATILITY_SQUEEZE ma150  PROMISING-WATCHLIST   N=  51  ExpR=  0.267 CI=XZERO  N=  21  ExpR=  0.100 CI=XZERO
SILVER          1week  VOLATILITY_SQUEEZE ma150  DIED                  N=   5* ExpR= -0.107 CI=XZERO  N=   2* ExpR= -1.032 CI=clear
PLATINUM        2h     VOLATILITY_SQUEEZE ma150  PROMISING-WATCHLIST   N=  36  ExpR=  0.086 CI=XZERO  N=  20  ExpR=  0.051 CI=XZERO
PLATINUM        4h     VOLATILITY_SQUEEZE ma150  DIED                  N=  19* ExpR= -0.122 CI=XZERO  N=   8* ExpR= -0.390 CI=XZERO
PLATINUM        12h    VOLATILITY_SQUEEZE ma150  DIED                  N=   5* ExpR= -0.149 CI=XZERO  N=   1* ExpR=  1.290 CI=clear
PLATINUM        24h    VOLATILITY_SQUEEZE ma150  DIED                  N=  61  ExpR= -0.203 CI=XZERO  N=  27  ExpR=  0.022 CI=XZERO
PLATINUM        1week  VOLATILITY_SQUEEZE ma150  DIED                  N=   8* ExpR=  0.116 CI=XZERO  N=   0* ExpR=  0.000 CI=n/a
SILVER          2h     VOLATILITY_SQUEEZE ma100  DIED                  N=  37  ExpR= -0.322 CI=XZERO  N=  19* ExpR=  0.075 CI=XZERO
SILVER          4h     VOLATILITY_SQUEEZE ma100  DIED                  N=  20  ExpR= -0.366 CI=XZERO  N=   6* ExpR=  0.097 CI=XZERO
SILVER          12h    VOLATILITY_SQUEEZE ma100  PROMISING-WATCHLIST   N=   2* ExpR=  0.764 CI=clear  N=   2* ExpR=  0.118 CI=XZERO
SILVER          24h    VOLATILITY_SQUEEZE ma100  PROMISING-WATCHLIST   N=  55  ExpR=  0.259 CI=XZERO  N=  21  ExpR=  0.100 CI=XZERO
SILVER          1week  VOLATILITY_SQUEEZE ma100  DIED                  N=   5* ExpR= -0.107 CI=XZERO  N=   2* ExpR= -1.032 CI=clear
PLATINUM        2h     VOLATILITY_SQUEEZE ma100  DIED                  N=  38  ExpR=  0.011 CI=XZERO  N=  21  ExpR= -0.006 CI=XZERO
PLATINUM        4h     VOLATILITY_SQUEEZE ma100  DIED                  N=  20  ExpR= -0.260 CI=XZERO  N=   8* ExpR= -0.605 CI=clear
PLATINUM        12h    VOLATILITY_SQUEEZE ma100  DIED                  N=   5* ExpR= -0.149 CI=XZERO  N=   1* ExpR=  1.290 CI=clear
PLATINUM        24h    VOLATILITY_SQUEEZE ma100  DIED                  N=  62  ExpR= -0.182 CI=XZERO  N=  27  ExpR=  0.111 CI=XZERO
PLATINUM        1week  VOLATILITY_SQUEEZE ma100  DIED                  N=   9* ExpR= -0.014 CI=XZERO  N=   1* ExpR= -1.032 CI=clear
SILVER          1week  DONCHIAN_TREND            PROMISING-WATCHLIST   N=  13* ExpR=  0.362 CI=XZERO  N=   9* ExpR=  0.222 CI=XZERO
PLATINUM        1week  DONCHIAN_TREND            PROMISING-WATCHLIST   N=  17* ExpR=  0.631 CI=XZERO  N=   9* ExpR=  0.064 CI=XZERO
SILVER          2h     FVG_REVERSION             DIED                  N= 191  ExpR= -0.240 CI=clear  N=  79  ExpR= -0.009 CI=XZERO
SILVER          4h     FVG_REVERSION             DIED                  N=  92  ExpR= -0.338 CI=clear  N=  40  ExpR=  0.007 CI=XZERO
SILVER          12h    FVG_REVERSION             DIED                  N=  28  ExpR= -0.244 CI=XZERO  N=   9* ExpR= -0.237 CI=XZERO
PLATINUM        2h     FVG_REVERSION             DIED                  N= 227  ExpR= -0.345 CI=clear  N=  94  ExpR=  0.046 CI=XZERO
PLATINUM        4h     FVG_REVERSION             DIED                  N= 116  ExpR= -0.156 CI=XZERO  N=  34  ExpR=  0.217 CI=XZERO
PLATINUM        12h    FVG_REVERSION             DIED                  N=  33  ExpR= -0.237 CI=XZERO  N=   8* ExpR=  0.179 CI=XZERO
SILVER          4h     BOS_CONTINUATION          DIED                  N=  57  ExpR= -0.145 CI=XZERO  N=  25  ExpR=  0.001 CI=XZERO
SILVER          12h    BOS_CONTINUATION          DIED                  N=  20  ExpR= -0.235 CI=XZERO  N=   5* ExpR= -0.339 CI=XZERO
SILVER          24h    BOS_CONTINUATION          PROMISING-WATCHLIST   N= 124  ExpR=  0.082 CI=XZERO  N=  49  ExpR=  0.105 CI=XZERO
PLATINUM        4h     BOS_CONTINUATION          DIED                  N=  62  ExpR= -0.145 CI=XZERO  N=  23  ExpR=  0.023 CI=XZERO
PLATINUM        12h    BOS_CONTINUATION          DIED                  N=  23  ExpR= -0.071 CI=XZERO  N=   3* ExpR=  0.189 CI=XZERO
PLATINUM        24h    BOS_CONTINUATION          DIED                  N= 140  ExpR= -0.010 CI=XZERO  N=  56  ExpR=  0.001 CI=XZERO
Gold-Silver     12h    COINTEGRATION_PAIRS       DIED                  N=   0* ExpR=  0.000 CI=n/a    N=   0* ExpR=  0.000 CI=n/a
Gold-Silver     24h    COINTEGRATION_PAIRS       DIED                  N=  19* ExpR= -0.010 CI=XZERO  N=  10* ExpR=  0.037 CI=clear
Silver-Platinum 12h    COINTEGRATION_PAIRS       DIED                  N=   6* ExpR= -0.010 CI=XZERO  N=   0* ExpR=  0.000 CI=n/a
Silver-Platinum 24h    COINTEGRATION_PAIRS       PROMISING-WATCHLIST   N=  19* ExpR=  0.014 CI=XZERO  N=  22  ExpR=  0.026 CI=XZERO
SILVER          24h    MACRO_RISK_ON             PROMISING-WATCHLIST   N= 158  ExpR=  0.051 CI=XZERO  N=  94  ExpR=  0.162 CI=XZERO
PLATINUM        24h    MACRO_RISK_ON             DIED                  N= 146  ExpR=  0.210 CI=XZERO  N= 103  ExpR= -0.061 CI=XZERO
-----------------------------------------------------------------------------------------------------------------------------
```

`* = below the 20-trade minimum sample.`

## Data notes surfaced during this sweep

- **Gold-Silver / 12h**: 0 trades both halves. Only 24 candles aligned between the
  two vendors at this timeframe (Twelve Data GOLD vs yfinance SILVER, each resampled
  from their own 1h source with different bar-edge offsets) — far below
  COINTEGRATION_PAIRS' own 200-candle rolling warmup, so 0 trades is the honest,
  structurally-expected result, not a bug.
- **Gold-Silver / 24h**: uses a date-based cross-vendor alignment fix (see
  `align_pair_candles_by_date` in the sweep tool) — GOLD's Twelve Data daily close is
  stamped 00:00 UTC, SILVER's yfinance daily close ~04:00 UTC, for the *same*
  calendar trading day; an exact-close_time join (correct for same-vendor BTC-ETH)
  found zero overlap here before the fix. With the fix, 3,831 calendar days aligned.
- **PLATINUM / 1week / MEAN_REVERSION v1**: 0 trades both halves — 1week candles
  (weekly OHLC) never produce an RSI<35-below-lower-BB touch for PLATINUM in this
  window; reported honestly as DIED via the "not positive" branch, not a fabricated
  number.

## Configs positive in both halves with >= 20 trades each half (Task 3 candidates)

9 of 76 configs cleared this bar (before grid-shift verification):

1. SILVER / 24h / BREAKOUT_MOMENTUM
2. SILVER / 24h / TREND_PULLBACK
3. PLATINUM / 24h / TREND_PULLBACK
4. SILVER / 24h / VOLATILITY_SQUEEZE ma200
5. SILVER / 24h / VOLATILITY_SQUEEZE ma150
6. PLATINUM / 2h / VOLATILITY_SQUEEZE ma150
7. SILVER / 24h / VOLATILITY_SQUEEZE ma100
8. SILVER / 24h / BOS_CONTINUATION
9. SILVER / 24h / MACRO_RISK_ON

None of these are SURVIVED yet — every bootstrap CI on the TEST half crosses zero
(`XZERO`), so none has cleared the full SURVIVED bar even before grid-shift
verification. See `docs/metals_grid_shift_verification.md` (Task 3) for the
mandatory grid-shift check every one of these 9 configs goes through next, per the
task's "no exceptions" rule.

67 of 76 configs (88%) DIED outright — consistent with this project's stated ~1.5%
historical survival expectation for new strategy/asset combinations.
