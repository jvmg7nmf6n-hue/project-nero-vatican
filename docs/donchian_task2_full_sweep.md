# Donchian Cross-Asset Deep-Dive, Task 2 — Focused Sweep at Maximum Data Depth

`tools/backtest_donchian_deep_dive.py`, 37 configs across forex/metals/stocks/crypto,
70/30 chronological split on each asset's **maximum available history** (decades, not
a recent window — the entire point of this batch). Bidirectional Donchian breakout
(`nero_core.strategies.donchian_breakout_bracket`), 2xATR stop, fixed 2R target,
holding cap matched to each N preset.

## Headline result: the sample-size ceiling is broken — once

**GOLD / 1week / N20 reached raw SURVIVED** — positive expectancy both halves
(TRAIN ExpR=+0.450, TEST ExpR=+0.448), adequate sample both halves (N=144 train,
N=38 test, both clear MIN_SAMPLE_SIZE=20), **and the bootstrap 95% CI clears zero on
both halves** (TRAIN [0.211, 0.691], TEST [0.007, 0.901]) — the first time
DONCHIAN_TREND has cleared every statistical bar in this project's history across
four prior batches. Per this project's own mandatory-grid-shift rule, it is still
**capped to PROMISING-WATCHLIST** here, since grid-shift is structurally
NOT_APPLICABLE at 1week (no finer native source exists to resample from without
crossing the Friday-close/Sunday-open gap) — the same limitation every other
1week/1day config in this project's history has hit. **This is not a data or
statistical shortfall — it's a structural verification-method limitation.** The
task this batch set out to answer — "is DONCHIAN_TREND permanently sample-limited,
or does deeper data resolve it?" — is answered: **deeper data resolves the sample
problem.** What remains unresolved is purely the grid-shift mechanism itself, which
no amount of additional history can fix for a weekly-bar strategy.

## Full results table (27 of 37 configs SURVIVED-raw or PROMISING-WATCHLIST)

| Asset | TF | N | Verdict | Train (N, ExpR, CI) | Test (N, ExpR, CI) |
|---|---|---|---|---|---|
| EUR/USD | 1week | N10 | PROMISING-WATCHLIST | 115, +0.307, [0.068,0.556] | 37, +0.083, [-0.294,0.473] |
| EUR/USD | 1week | N20 | PROMISING-WATCHLIST | 84, +0.407, [0.100,0.710] | 26, +0.280, [-0.238,0.811] |
| EUR/USD | 1week | N40 | PROMISING-WATCHLIST | 62, +0.171, [-0.176,0.526] | 17*, +0.273, [-0.347,0.908] |
| USD/JPY | 1week | N10 | PROMISING-WATCHLIST | 171, +0.254, [-0.001,0.503] | 50, +0.197, [-0.152,0.558] |
| USD/JPY | 1week | N20 | PROMISING-WATCHLIST | 135, +0.238, [-0.082,0.531] | 36, +0.241, [-0.196,0.711] |
| USD/JPY | 1week | N40 | PROMISING-WATCHLIST | 89, +0.468, [0.172,0.774] | 23, +0.244, [-0.303,0.867] |
| GBP/USD | 1week | N10 | DIED | 173, +0.378 | 45, **-0.041** |
| GBP/USD | 1week | N20 | PROMISING-WATCHLIST | 131, +0.463, [0.214,0.714] | 29, +0.032, [-0.413,0.483] |
| GBP/USD | 1week | N40 | DIED | 94, +0.583 | 20, **-0.211** |
| USD/CHF | 1week | N10 | DIED | 175, +0.354 | 51, **-0.291** |
| USD/CHF | 1week | N20 | DIED | 133, +0.530 | 37, **-0.328** |
| USD/CHF | 1week | N40 | DIED | 92, +0.349 | 22, **-0.501** |
| **GOLD** | 1week | N10 | PROMISING-WATCHLIST | 197, +0.255, [0.058,0.454] | 61, +0.139, [-0.188,0.478] |
| **GOLD** | 1week | **N20** | **PROMISING-WATCHLIST (raw: SURVIVED)** | 144, +0.450, [0.211,0.691] | 38, +0.448, [0.007,0.901] |
| **GOLD** | 1week | N40 | PROMISING-WATCHLIST | 112, +0.458, [0.174,0.748] | 28, +0.275, [-0.260,0.811] |
| SILVER | 1week | N10 | DIED | 76, **-0.164** | 32, +0.373 |
| SILVER | 1week | N20 | PROMISING-WATCHLIST | 51, +0.007, [-0.360,0.400] | 25, +0.175, [-0.424,0.774] |
| SILVER | 1week | N40 | PROMISING-WATCHLIST | 33, +0.336, [-0.208,0.792] | 16*, +0.664, [-0.084,1.412] |
| SPY | 1week | N10 | PROMISING-WATCHLIST | 76, +0.090, [-0.192,0.377] | 32, +0.438, [-0.019,0.870] |
| SPY | 1week | N20 | PROMISING-WATCHLIST | 57, +0.271, [-0.090,0.630] | 25, +0.461, [-0.072,1.020] |
| SPY | 1week | N40 | PROMISING-WATCHLIST | 42, +0.457, [0.026,0.904] | 22, +0.477, [-0.103,1.074] |
| SPY | 1day | N10/N20/N40 | DIED (all 3) | — | — |
| QQQ | 1week | N10/N20/N40 | PROMISING-WATCHLIST (all 3) | 64/46/41 | 26/20/15* |
| QQQ | 1day | N10/N20/N40 | PROMISING-WATCHLIST (all 3) | 146/110/81 | 73/64/54 |
| AAPL | 1week | N20 | PROMISING-WATCHLIST | 91, +0.193, [-0.096,0.490] | 39, +0.105, [-0.334,0.564] |
| MSFT | 1week | N20 | PROMISING-WATCHLIST | 70, +0.282, [-0.043,0.606] | 31, +0.474, [-0.023,0.951] |
| GOOGL | 1week | N20 | PROMISING-WATCHLIST | 36, +0.177, [-0.275,0.627] | 16*, +0.613, [-0.084,1.310] |
| BTC | 1week | N20 | PROMISING-WATCHLIST | 15*, +0.178 | 3*, +0.798 |
| BTC | 1day | N20 | PROMISING-WATCHLIST | 42, +0.334, [-0.094,0.763] | 15*, +0.169, [-0.628,0.967] |
| ETH | 1week | N20 | DIED | 16*, +0.366 | 4*, **-1.008** |
| ETH | 1day | N20 | PROMISING-WATCHLIST | 38, +0.561, [0.088,1.034] | 16*, +0.104, [-0.644,0.852] |

`*` = below MIN_SAMPLE_SIZE=20 in that half.

## Reading the pattern

- **N20 is the standout cross-asset value**: GOLD/N20 is the only raw SURVIVED
  result anywhere; EUR/USD/N20 and GBP/USD/N20 both reach "adequate sample, train CI
  clearly positive" (only the test-half CI crosses zero) — the classic Donchian
  parameter is earning its name.
- **USD/CHF died on every N** — the one Priority Tier pair where deeper history
  made things WORSE, not better: strongly positive TRAIN but consistently negative
  TEST across all three N values. A real out-of-sample breakdown, not a sample-size
  artifact (adequate N in both halves throughout).
- **SPY/1day died on every N** while **SPY/1week and QQQ/1day both stayed
  promising** — the daily-bar version of this exact same strategy, on the exact
  same underlying instrument, does not work; only the weekly bar does. This is a
  genuine timeframe-specific finding, not noise.
- **Crypto (comparison baseline) behaved as expected**: short history (466-3260
  candles vs. decades elsewhere) kept every crypto config sample-limited (`*`
  flags throughout), and ETH/1week's test half (N=4) produced an extreme,
  meaningless CI — exactly the kind of result this task predicted crypto would
  produce as the "expect shorter history" baseline.

## Grid-shift

NOT_APPLICABLE for every config, per this task's own instruction — 1week (all
forex/metals/most stocks) hits the Friday-close/Sunday-open settlement-gap
precedent; 1day (SPY/QQQ/BTC/ETH) has a genuine intraday (1h) source but only over
a recent window (~730 days for stocks) far shorter than this batch's multi-decade
samples, so resampling over that short a window would test a different, much
smaller sample than the one actually classified here — not a like-for-like
grid-shift. GOLD/1week/N20's raw SURVIVED is capped to PROMISING-WATCHLIST for
exactly this reason, consistently with every other 1week/1day config in this
project's history.

See `docs/donchian_task3_mechanism_validation.md` for the follow-up mechanism check
on the standout configs, and `docs/donchian_deep_dive_closing_report.md` for the
consolidated business framing.
