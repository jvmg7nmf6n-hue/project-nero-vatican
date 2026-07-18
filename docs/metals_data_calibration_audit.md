# Metals Data + Calibration Audit — Asset Expansion Phase A, Task 1

Audit tool: `tools/metals_data_calibration_audit.py`. Run against live data on
2026-07-19. Covers Silver and Platinum, the two metals in scope for Phase A.

## Summary

**Twelve Data (the same source GOLD uses) does not serve either metal on this
project's current plan.** A direct request against the live API returns:

```
XAG/USD 1day -> 404 {"code":404,"message":"This symbol is available starting with
                      the Grow or Venture plan. Consider upgrading now at
                      https://twelvedata.com/pricing"}
XPT/USD 1day -> 404 {"code":404,"message":"This symbol is available starting with
                      the Grow or Venture plan. Consider upgrading now at
                      https://twelvedata.com/pricing"}
```

Both symbols are valid and recognized by Twelve Data's own `symbol_search` endpoint —
this is a plan restriction, not a bad symbol or a missing instrument. GOLD's
`XAU/USD` is unaffected and continues to work on the same API key.

**Resolution (user-approved): yfinance continuous futures as a documented proxy.**
yfinance (already a project dependency) freely serves COMEX Silver (`SI=F`) and
NYMEX Platinum (`PL=F`) continuous front-month futures with strong depth — in some
timeframes deeper than GOLD's own Twelve Data history. `nero_core/data_sources/
market_data.py`'s `MarketDataClient` now falls back to yfinance for SILVER/PLATINUM
whenever Twelve Data fails, via a new `YFINANCE_FUTURES_SYMBOLS` cascade tier. Every
data-source string this produces says explicitly `"(continuous futures proxy, not
spot)"` — this is a genuine data-source substitution, not spot XAG/USD or XPT/USD,
and every report built on it repeats that caveat. Real basis/roll effects between a
continuous futures contract and true spot exist; short-horizon price ACTION (the
actual input every strategy in this codebase trades on — RSI, Bollinger Bands, ATR,
MA crossovers, breakout levels) tracks spot closely in practice for both metals, but
absolute levels and slow drifts can diverge.

## Side discovery: a real timestamp bug, fixed as part of this audit

While validating the yfinance fetch path, `close_time`/`open_time` came back wrong by
a factor of 1000 (seconds mislabeled as milliseconds) — traced to the installed
pandas being `3.0.3`, outside this project's own `requirements.txt` pin
(`pandas>=2.0,<3`). On that pandas version, `pd.to_datetime(...).astype("int64")`
does not reliably yield nanoseconds (resolution now varies — seconds, in the case
observed), so the existing `// 1_000_000` division silently produced garbage instead
of raising. This affected **only** GOLD/SILVER/PLATINUM (the datetime-string-based
sources) — the crypto assets get raw millisecond integers directly from
Binance/Coinbase/Kraken and were never affected. The practical consequence: with
`close_time` off by 1000x, `hours_held` computations come out ~1000x too small, so
the `TIME` (max-holding-hours) exit would never fire — trades would only ever close
via SL or TARGET.

Checked `data/truth_ledger.db`: `execution_log` has zero rows, so no live/committed
Truth Ledger data was affected. GitHub Actions installs fresh from `requirements.txt`
(which correctly excludes pandas 3.x), so the live scheduler is very likely
unaffected by this specific environment drift. Fixed in `market_data.py` by using
`.dt.as_unit("ms")` before the `int64` cast (correct regardless of whatever
resolution pandas infers) in both `_load_twelve_data` and the new `_load_yfinance`,
with a regression test (`TimestampMillisecondPrecisionRegressionTest` in
`tests/test_market_data.py`) that fails against the old code and passes against the
fix. This was not re-applied retroactively to any previously-reported GOLD numbers
from earlier research phases, per the scope agreed for this fix.

## (a) History depth per timeframe

| Metal | Timeframe | Candles | Span | Date range | Status |
|---|---|---:|---:|---|---|
| SILVER | 2h | 6,866 | 875.6d | 2024-02-23 to 2026-07-17 | ADEQUATE |
| SILVER | 4h | 3,433 | 875.5d | 2024-02-23 to 2026-07-17 | ADEQUATE |
| SILVER | 12h | 1,144 | 875.0d | 2024-02-23 to 2026-07-17 | ADEQUATE |
| SILVER | 24h | 6,495 | 9,452.0d (~25.9y) | 2000-08-31 to 2026-07-18 | ADEQUATE |
| SILVER | 1week | 1,350 | 9,443.0d | 2000-09-04 to 2026-07-13 | ADEQUATE |
| PLATINUM | 2h | 6,863 | 875.6d | 2024-02-23 to 2026-07-17 | ADEQUATE |
| PLATINUM | 4h | 3,431 | 875.4d | 2024-02-23 to 2026-07-17 | ADEQUATE |
| PLATINUM | 12h | 1,143 | 874.8d | 2024-02-23 to 2026-07-17 | ADEQUATE |
| PLATINUM | 24h | 6,521 | 10,488.0d (~28.7y) | 1997-10-30 to 2026-07-18 | ADEQUATE |
| PLATINUM | 1week | 1,377 | 10,479.0d | 1997-11-03 to 2026-07-13 | ADEQUATE |

Adequacy bar: >=700 total candles (see the tool's docstring — every train/test split
tool in this codebase recomputes indicators independently on each 70/30 half, and the
widest warmup any Phase A strategy needs is MA200; the 30% test half alone needs
>=200 candles for MA200 to ever produce a value, so the full series needs
>=200/0.30 ~= 667, rounded up to 700). **Every timeframe for both metals clears this
bar** — unlike GOLD, whose own Twelve Data intraday history is capped at roughly
210 days, yfinance's 1h history for these futures goes back to 2024-02-23 (~876
days), comfortably deeper. 2h/4h/12h are all resampled from that same 1h fetch (no
native 2h/4h/12h interval on yfinance); 24h and 1week are fetched natively.

**No metal or timeframe is blocked or skipped in Task 2** — all ten (metal,
timeframe) combinations proceed to the full sweep.

## (b) Gaps

The 2h/4h/12h/24h series show a recurring ~81-169 hour max gap for both metals —
this is the expected weekly market closure for CME-family futures (Friday afternoon
ET close to Sunday evening ET reopen, extended further by U.S. holidays), not a data
integrity problem. Spot metals and crypto trade closer to continuously; these
continuous futures contracts genuinely do not.

**One real gap worth flagging**: PLATINUM's daily/weekly series has an ~78-day hole
from **2004-04-28 to 2004-07-15** (1,872 hours — the reported max gap) with no
candles at all. This is a real historical data-quality characteristic of the
yfinance continuous-contract splice at that vintage, not a fabrication and not a
processing bug — confirmed by inspecting the actual candles bracketing the gap.
Any PLATINUM 24h/1week backtest whose train/test split boundary falls inside or near
this window should be read with that in mind; this audit does not attempt to patch,
interpolate, or drop the surrounding data, consistent with this project's "never
fabricate over missing data" rule.

## (c) ATR/price ratio and calibration decision

Methodology: identical to GOLD's own derivation
(`nero_core/strategies/mean_reversion_gold_calibrated.py`) — price/ATR(14) averaged
over every 4h candle where MEAN_REVERSION v1's entry rule set actually passes
(RSI<35, close below the lower Bollinger Band, close above MA200, MA20 target above
close).

| Reference | Ratio |
|---|---:|
| GOLD (4h, n=46) | 185.1868 |
| BTC (4h, n=141) | 70.2066 |
| GOLD_FEE_SCALE_FACTOR | 0.3791 |

| Metal | Ratio (4h) | n | Deviation from GOLD | Decision | Scale factor |
|---|---:|---:|---:|---|---:|
| SILVER | 68.0986 | 48 | 63.2% | **DERIVE_OWN** | 1.0310 |
| PLATINUM | 72.7826 | 16 (LOW SAMPLE) | 60.7% | **DERIVE_OWN** | 0.9646 |

Both metals fall well outside the +/-30% reuse tolerance — GOLD's calibration is
**not** reused. Each gets its own scale factor, derived the same way GOLD's was:
`BTC_MEASURED_PRICE_ATR_RATIO / metal's own measured ratio`. PLATINUM's n=16 is below
the project's standard MIN_SAMPLE_SIZE=20 threshold — its scale factor is usable but
should be treated as provisional and revisited once more live 4h history accrues
(the same LOW-SAMPLE convention used everywhere else in this project's reports).

**Notable finding**: both metals' price/ATR ratios sit much closer to BTC's (70.21)
than to GOLD's (185.19) — i.e., relative to their own price, SILVER and PLATINUM
futures are considerably MORE volatile than spot GOLD, on the order of BTC's own
volatility profile rather than GOLD's calmer one. This is a first, concrete data
point for the Phase A closing report's question of whether metals behave more like
GOLD (slow, macro-driven) or more like crypto (fast, volatile) — on this one
dimension, they look more like crypto.

Derived values live in `nero_core/strategies/metals_calibration.py`, wired into the
shared `nero_core.strategies.timeframe_calibration.FEE_SCALE_FACTOR_BY_ASSET` dict
that `build_calibrated_params` (and `volatility_squeeze.build_params_for_run`) already
use — GOLD's own calibration path is unchanged (verified via the existing test suite
before and after this refactor).

## Conclusion

Neither metal is blocked. All five standard timeframes (2h, 4h, 12h, 24h, 1week) are
adequate for both SILVER and PLATINUM. Task 2's full strategy sweep proceeds across
all ten (metal, timeframe) combinations, using each metal's own derived fee/slippage
scale factor.
