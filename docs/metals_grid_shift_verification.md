# Metals Grid-Shift Verification — Asset Expansion Phase A, Task 3

Tool: `tools/backtest_metals_grid_shift_verification.py`. Mandatory follow-up to
every one of Task 2's 9 configs positive in both halves with >=20 trades each half
(see `docs/metals_phase_a_full_sweep.md`) — no exceptions, per the task.

## Structural finding, confirmed before writing any grid-shift logic

8 of the 9 Task 2 candidates are at the 24h timeframe. Direct testing showed
`resample_hourly_to_grid` produces **zero** complete 24h bins for SILVER at every
offset tried (0h, +6h, +12h, +18h):

```
hourly candles: 13732
24h offset+0h  -> 0 bins
24h offset+6h  -> 0 bins
24h offset+12h -> 0 bins
24h offset+18h -> 0 bins
2h offset+0h   -> 6556 bins
2h offset+1h   -> 6555 bins
```

Root cause, confirmed by inspecting real fetched 1h candles directly: COMEX/NYMEX
continuous futures (SI=F, PL=F) carry a **~2-hour daily settlement gap around 23:00
UTC on every single calendar day** (plus a longer weekend gap) —

```
2026-07-07 23:00:00+00:00   gap 2.0h
2026-07-08 23:00:00+00:00   gap 2.0h
2026-07-09 23:00:00+00:00   gap 2.0h
2026-07-12 23:00:00+00:00   gap 50.0h   (weekend)
2026-07-13 23:00:00+00:00   gap 2.0h
...
```

`resample_hourly_to_grid`'s contract requires a bin to contain *exactly* N
consecutive hourly candles with no gap (see its own docstring — this is deliberate,
so it never fabricates a candle over missing data). A 24-hour bin at ANY offset will
always straddle this daily ~2-hour gap, so it can never be satisfied. **This is not
a bug and not a data-quality problem** — CME-family futures genuinely do not trade a
full continuous 24 hours; the exchange's own daily settlement boundary already
anchors where one trading day ends and the next begins.

This also means the grid-shift *question itself* doesn't apply to these 8 configs
the same way it does to GOLD/BTC/crypto. The whole premise of grid-shift testing
(H6's original motivation) is: "the boundary between candles is an arbitrary human
UTC convention — does the edge survive moving it?" For a continuously-traded
instrument, that's a real question. For an exchange-settled future, there is no
arbitrary boundary to re-test — the daily close **is** the exchange's own real
settlement, not a convention this project chose.

**Consequence**: those 8 configs are reported grid-shift **NOT_APPLICABLE**, with
this exact rationale, rather than skipped silently or forced through an invented
workaround. They remain **PROMISING-WATCHLIST** — SURVIVED requires holding across
grid shifts, and a claim that cannot be tested cannot be promoted.

## The one genuinely testable candidate

Only **PLATINUM / 2h / VOLATILITY_SQUEEZE ma150** is at a timeframe (2h) that
doesn't span the daily settlement hour, so it gets a real grid-shift run — offsets
0h (control) and +1h, matching H6's own 2h offset choice:

```
=== PLATINUM / 2h / VOLATILITY_SQUEEZE ma150 ===
  offset+0h (control)  (6553 candles) — does not qualify
      TRAIN: N=32 ExpR=0.087
      TEST:  N=19 ExpR=-0.005
  offset+1h            (6551 candles) — does not qualify
      TRAIN: N=32 ExpR=0.047
      TEST:  N=20 ExpR=-0.181
  FINAL: PROMISING-WATCHLIST (does not hold across every grid shift)
```

It does not hold: even the control grid's test half is negative once resampled
independently from 1h (N=19, ExpR=-0.005 — Task 2's own native-fetch test half had
been N=20, ExpR=+0.051, just barely over the line), and the +1h shift is clearly
negative (ExpR=-0.181). This is exactly the kind of fragile, alignment-sensitive
result H6 was built to catch.

## Final classification for all 9 Task 2 candidates

| Config | Task 2 verdict | Grid-shift | Final |
|---|---|---|---|
| SILVER / 24h / BREAKOUT_MOMENTUM | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |
| SILVER / 24h / TREND_PULLBACK | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |
| PLATINUM / 24h / TREND_PULLBACK | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |
| SILVER / 24h / VOLATILITY_SQUEEZE ma200 | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |
| SILVER / 24h / VOLATILITY_SQUEEZE ma150 | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |
| PLATINUM / 2h / VOLATILITY_SQUEEZE ma150 | PROMISING-WATCHLIST | TESTED — fails | PROMISING-WATCHLIST (weaker) |
| SILVER / 24h / VOLATILITY_SQUEEZE ma100 | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |
| SILVER / 24h / BOS_CONTINUATION | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |
| SILVER / 24h / MACRO_RISK_ON | PROMISING-WATCHLIST | NOT_APPLICABLE | PROMISING-WATCHLIST |

**No config reaches SURVIVED in Phase A.** Zero of 76 tested configurations survive
the full bar (positive both halves, adequate sample, CI clears zero on both halves,
holds across grid shifts) — consistent with this project's stated ~1.5% historical
survival rate for new strategy/asset combinations. All 8 NOT_APPLICABLE configs stay
exactly where Task 2 left them (PROMISING-WATCHLIST); the one tested config is
actively weaker than it looked before grid-shift.
