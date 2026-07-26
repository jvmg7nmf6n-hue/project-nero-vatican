# REPAIR_BREAKOUT_QUALITY v1.0.0 — Verification Report

## Origin

User-supplied external spec (display name `FIX_BREAKOUT_QUALITY`), already forward-tested
outside Vatican on a small sample (12 trades, 66.7% win rate, +0.158R expectancy, profit
factor 1.63, reported CI -0.647R to +0.964R). Per explicit instruction, those external
numbers are **not used as evidence anywhere in this codebase** — this report is Vatican's
own, independent measurement, run from scratch.

## Mechanism, as implemented

`nero_core/strategies/repair_breakout_quality.py` — 4H long-only:

1. Close > prior 30-candle high (no lookahead: `shift(1)` before the rolling max).
2. Close > MA200, and MA20 > MA200 (trend support).
3. ATR(14)/close <= 4%.
4. A candle satisfying 1-3 **arms** a pending setup at that breakout level (does not
   enter yet).
5. **Retest confirmation** (external-testing finding #1, fixed): a later closed candle,
   within 10 candles of arming, whose low touches the armed level and whose close
   finishes back above it, confirms the setup.
6. **Entry fires on the candle AFTER confirmation** — never the confirmation candle
   itself, since "did this candle's low touch and close back above the level" is only
   knowable once that candle has already closed. Every regime filter (MA200, MA20>MA200,
   ATR cap) is re-checked at this later entry candle too, not just at the original
   breakout.
7. Stop = entry − 1.0×ATR. **No gap tolerance** (external-testing finding #2, fixed): if
   a candle's low touches the stop but its close recovers back above it, that's a normal
   same-bar wick, filled at the stop price. If the candle's close *also* finishes at or
   below the stop (the whole bar broke through), no same-bar fill is assumed — the exit
   is realized on the next candle's open, honestly, even if that's worse than -1.0R.
8. Target = fixed 1.5R.
9. Rule 6 from the external spec ("planned reward >= 1.35R") is implemented but
   structurally a no-op given the fixed 1.5R target (1.5 > 1.35 always) — kept visible in
   the code rather than silently dropped; see the module docstring.
10. 1% fixed-fractional risk per trade. 10bps fee, 2bps slippage (this codebase's
    standard crypto convention).
11. Holding cap: 240 hours (10 days), a backstop **not specified in the external spec** —
    disclosed here as this implementation's own addition, not smuggled in.

## Harness

`tools/backtest_repair_breakout_quality.py`, following this project's established
verification pattern (`tools/backtest_donchian_deep_dive.py`,
`tools/backtest_metals_grid_shift_verification.py`):

- **70/30 chronological split** (`tools.backtest_train_test_split.split_chronological`)
  on the last 3 years of native 4H candles, built by resampling native 1h candles at UTC
  offset 0 (not fetched as Binance's own native "4h" series), so every grid-shift offset
  is a directly comparable re-run of the same mechanism on a shifted bin boundary.
- **Bootstrap 95% CI** on mean per-trade R (`tools.backtest_statistics.bootstrap_mean_r_ci`,
  5000 iterations), per half.
- **Random-entry baseline** (`tools.backtest_statistics.random_entry_baseline_single_asset`,
  200 runs) against the regime-only eligible pool (close>MA200, MA20>MA200, ATR<=4%),
  excluding the specific breakout/retest trigger — isolates whether the trigger timing
  itself adds anything over the regime alone.
- **Grid-shift**: exhaustive offsets +0h/+1h/+2h/+3h (a 4H bin has exactly 4 possible UTC
  offsets). Demotion-only, per project convention: can knock a raw SURVIVED down to
  PROMISING-WATCHLIST, never promotes anything.
- Assets: BTC, XRP, BNB (PAXG skipped — no data source exists anywhere in this codebase;
  see prior analysis). Last 3 years of history (`2023-07-27` to `2026-07-26`), all three
  assets have far more Binance history available than that, so the 3-year cap is what
  actually bound, not data availability.

## Results

| Asset | Train N | Train ExpR | Train CI | Test N | Test ExpR | Test CI | Verdict |
|---|---|---|---|---|---|---|---|
| BTC | 41 | -0.473 | [-0.883, -0.064] | 9 | -0.232 | [-1.120, 0.696] | **DIED** |
| XRP | 25 | -0.351 | [-0.797, 0.154] | 9 | +0.032 | [-0.963, 1.023] | **DIED** |
| BNB | 50 | -0.356 | [-0.721, 0.005] | 7 | -0.553 | [-1.338, 0.419] | **DIED** |

All three DIED under `classify_verdict` (requires positive expectancy on **both** halves;
every train half here is negative). Grid-shift (offsets +1h/+2h/+3h) was run for
completeness but is moot — none of these reached raw SURVIVED to begin with.

Edge over the random-entry baseline (same regime, randomized entry timing) was mixed and
mostly unremarkable: BTC train -0.247R / test +0.091R, XRP train +0.007R / test +0.654R,
BNB train -0.056R / test -0.175R. No asset shows the breakout+retest trigger consistently
beating random entry timing within the same trend/low-volatility regime, on top of the
mechanism already being unprofitable overall.

**Why this is a stronger negative than many other graveyard entries**: the negative signal
sits on the *larger* (train) half specifically, for all three assets, with an adequate
sample (25-50 trades) — not a thin, ambiguous, small-N result. BTC's train CI
([-0.883, -0.064]) doesn't even cross zero; it's negative with statistical confidence at
this sample size.

## Disposition

- Strategy code and its 22-test suite are committed (`nero_core/strategies/
  repair_breakout_quality.py`, `tests/test_repair_breakout_quality.py`) as a permanent,
  reproducible record of exactly what was tested and how the two external-testing fixes
  (multi-candle retest, no-gap-tolerance stop) were implemented.
- **Not wired to live paper trading.** No entry added to
  `nero_core/execution/verification_status.py` (reserved for live-wired strategies only).
- Added to `docs/site_data/graveyard.json`.

## What would change this verdict

Nothing tested here suggests a small tweak would flip this to positive — the train-half
CI on BTC is negative with real confidence, and the pattern (negative train, mixed test)
repeats identically across all three assets. If revisited, the more informative next
questions would be whether the specific 30-candle/10-candle/4%/1.35R parameter choices
were arbitrary (a parameter sweep, not just a single point, might tell a different story)
or whether the mechanism simply doesn't have an edge on this asset class/timeframe at all,
consistent with several other momentum/structure-break families already in the graveyard
(FVG_REVERSION, BOS_CONTINUATION) dying the same way.
