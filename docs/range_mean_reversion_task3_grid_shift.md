# RANGE_MEAN_REVERSION — Task 3 Grid-Shift Verification

Tool: `tools/range_mean_reversion_grid_shift.py`. Mandatory per the task spec, run in
full rather than skipped under time pressure — the result is that there is nothing
to grid-shift, which this tool proves rather than assumes.

## Result: 0 configs qualify — nothing to grid-shift

Task 2's sweep (`docs/range_mean_reversion_task2_sweep.md`) found **0 of 28 configs**
positive in both halves with an adequate sample (>=20 trades) in BOTH halves — the
precondition this task's own spec requires before a config is even eligible for
grid-shift consideration.

The 2 PROMISING-WATCHLIST configs fall short purely on **test-half sample size**, not
direction:

| Config | Train | Test | Why it doesn't qualify |
|---|---|---|---|
| GOLD / 1week | N=36 (adequate) | N=11 | test-half N=11 < 20 (LOW SAMPLE) |
| SILVER / 1week | N=23 (adequate) | N=15 | test-half N=15 < 20 (LOW SAMPLE) |

## Applicability check, for completeness (per the task's "note per config, don't skip silently")

Independent of whether anything qualified, this task's own universe is checked for
which timeframes are even structurally resampled (grid-shift-testable) vs native:

- **Forex (1h/4h/1day)**: all three are NATIVE Twelve Data intervals — no resampling
  happens anywhere in this pipeline for forex. Not applicable to any forex config.
- **GOLD (4h/1day/1week)**: all NATIVE Twelve Data intervals. Not applicable.
- **SILVER (1day/1week)**: NATIVE via yfinance's own daily/weekly intervals. Not
  applicable. **SILVER/4h is the ONE genuinely resampled timeframe in this task's
  entire universe** (built from yfinance's native 1h) — grid-shift would have applied
  here had it qualified. It DIED in Task 2 (TRAIN ExpR=-0.023, TEST ExpR=-0.302), so
  this is moot.
- **Crypto 4h/12h/1day (BTC/ETH/SOL/NEAR)**: all NATIVE Binance intervals. Not
  applicable to any crypto config.

**Even setting the 0-qualifying-configs finding aside, only one single
(asset, timeframe) combination in this entire 28-config universe — SILVER/4h — was
ever structurally grid-shift-testable, and it didn't qualify either.** This isn't a
loophole avoided by the sample-size shortfall; the two paths to "nothing to test"
are independent and both point the same way.

## Final classification

**No config in RANGE_MEAN_REVERSION Task 2 reaches SURVIVED.** GOLD/1week and
SILVER/1week remain PROMISING-WATCHLIST (positive both halves, band-extreme timing
shows a real edge over random entry in both halves, but the sample is too thin to
promote further). All other 26 configs remain DIED.
