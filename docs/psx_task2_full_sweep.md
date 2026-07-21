# PSX Strategy Sweep, Task 2 — Full 9-Strategy Sweep

`tools/backtest_psx_sweep.py`, run against real yfinance data (OGDC/LUCK/HBL, `.KA`
suffix), most recent 10 years, 70/30 chronological split, flat 0.15%/side fee
(Meezan Invest/Arif Habib-tier online brokerage), 2.0 bps slippage (unchanged
crypto-baseline default).

## Headline result: the corporate-action guard did real work

Task 1's guard (`detect_corporate_action_breaks`, >40% single-day close move) fired
on **2 of the 3** universe tickers on this sweep's first real run against their
**full** history:

- **OGDC**: 1 break — 2010-02-22, 29.21 → 43.77 (**+49.9%**)
- **LUCK**: 3 breaks — worst 2025-03-03, 282.45 → 1,400.89 (**+396.0%**)
- **HBL**: 0 breaks — clean across its full ~10-year window used here

This is not a contradiction of `docs/psx_data_audit.md`'s "OGDC/LUCK/HBL confirmed
clean" finding — that audit's gap/corporate-action check only scanned **2024**
full-year data. This sweep is the first time the full multi-year history was
scanned for corporate actions, and it found genuine breaks the narrower 2024-only
check had no way to see. This is exactly the scenario the guard exists for: PSX's
frequent bonus-share issuance corrupting a price series in a way a single-year spot
check can miss. **HBL is the only one of the three tickers clean enough to produce
a real backtest in this sweep.**

Practical consequence: every config touching OGDC or LUCK is **SKIPPED** (not
DIED — the data itself is halted, never fed into a backtest), including **all
three COINTEGRATION_PAIRS configs** (OGDC-LUCK, OGDC-HBL, LUCK-HBL each need a leg
that got halted). Every single-asset config ran successfully on **HBL** only.

## Full results table (HBL, 1day, 2,589 candles after the 10-year cutoff)

| Strategy | Verdict | Train (N, ExpR) | Test (N, ExpR) |
|---|---|---|---|
| MEAN_REVERSION v1 | DIED | 13*, -0.535 | 11*, +0.103 |
| BREAKOUT_MOMENTUM | DIED | 25, -0.099 | 37, +0.243 |
| TREND_PULLBACK | **PROMISING-WATCHLIST** | 10*, +0.145 | 9*, +0.333 |
| VOLATILITY_SQUEEZE ma200 | **PROMISING-WATCHLIST** | 8*, +0.350 | 9*, +0.714 |
| VOLATILITY_SQUEEZE ma150 | **PROMISING-WATCHLIST** | 8*, +0.350 | 10*, +0.612 |
| VOLATILITY_SQUEEZE ma100 | **PROMISING-WATCHLIST** | 8*, +0.350 | 10*, +0.612 |
| DONCHIAN_TREND | DIED | 26, -0.204 | 14*, +0.430 |
| FVG_REVERSION | DIED | 74, -0.209 | 32, -0.049 |
| BOS_CONTINUATION | DIED | 38, -0.099 | 16*, +0.295 |
| COINTEGRATION_PAIRS (all 3 pairs) | SKIPPED | — | — |
| MACRO_RISK_ON (currency-only, USD/PKR) | DIED | 216, -0.053 | 112, +0.092 |

`*` = below `MIN_SAMPLE_SIZE=20` in that half.

Note: VOLATILITY_SQUEEZE's ma100 and ma150 variants produced **identical** trade
counts and expectancy on HBL (N=8/10, ExpR=+0.350/+0.612 both halves) — the
regime/trigger condition evidently selected the same trade set regardless of the
100-vs-150 MA period difference for this specific ticker's price action. Reported
as observed, not adjusted.

## MACRO_RISK_ON — Pakistan adaptation notes

- **OGDC** (oil-and-currency regime: `USD/PKR rising AND oil rising`) — SKIPPED,
  data halted by the corporate-action guard before the regime frame could even be
  built.
- **LUCK** (currency-only regime: `USD/PKR rising`) — SKIPPED, same reason.
- **HBL** (currency-only regime) — the only one that ran: DIED, negative train
  expectancy (-0.053) with a genuinely adequate sample (N=216/112, well above
  MIN_SAMPLE_SIZE) — this is a real, non-low-sample negative result, not a
  statistical-noise DIED.
- USD/PKR (5,860 business days) and WTI oil (6,504 business days) both fetched
  cleanly via yfinance, confirming Task 1's macro-proxy pipeline works end to end
  against live data.

## Grid-shift

**NOT_APPLICABLE for every config in this sweep** — no PSX intraday data source
exists anywhere (confirmed in `docs/psx_data_audit.md`) to resample from at a
shifted clock offset, so grid-shift verification is structurally impossible to
run, exactly as it was for metals'/stocks' own 1day/1week configs. No config in
this sweep reached a raw SURVIVED classification regardless (every promotion
candidate here is PROMISING-WATCHLIST purely from `classify_verdict`'s own
sample-size gate, N<20 in at least one half) — the sweep tool's grid-shift cap
logic (`_apply_grid_shift_cap`) exists and is exercised by its own unit-equivalent
check, but had nothing to downgrade in this particular run.

## Promotion candidates (4)

All four are on **HBL** only, all **PROMISING-WATCHLIST** (positive both halves,
sample below 20 in at least one half — genuinely promising, not yet statistically
adequate):

1. HBL / TREND_PULLBACK
2. HBL / VOLATILITY_SQUEEZE ma200
3. HBL / VOLATILITY_SQUEEZE ma150
4. HBL / VOLATILITY_SQUEEZE ma100

See `docs/psx_phase_a_report.md` for the consolidated business framing and
promotion-list recommendation.
