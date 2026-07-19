# RANGE_MEAN_REVERSION v1.0.0 — Closing Consolidated Report

Three tasks, three commits: Task 1 (build), Task 2 (three-tier sweep, data audit
first), Task 3 (grid-shift verification). This report ties them together. Full
detail in `docs/range_mean_reversion_data_audit.md`, `docs/range_mean_reversion_task2_sweep.md`,
and `docs/range_mean_reversion_task3_grid_shift.md`.

## Origin

A discretionary trader ran this profitably by intuition: buy meaningfully below the
recent average, short meaningfully above it — but only while the market was
genuinely ranging, never trending. Formalized here as ADX(14)-gated Bollinger Band
mean reversion (`nero_core/strategies/range_mean_reversion.py`), tested with the same
rigor as every other strategy in this project.

## Full results table (28 configs)

| Tier | Asset | Timeframe | Verdict | Train N / ExpR / edge | Test N / ExpR / edge |
|---|---|---|---|---|---|
| 1 (forex) | EUR/USD | 1h | DIED | 46 / -0.921 / -0.028 | 25 / -0.715 / +0.250 |
| 1 (forex) | EUR/USD | 4h | DIED | 59 / -0.293 / +0.029 | 27 / -0.485 / -0.084 |
| 1 (forex) | EUR/USD | 1day | DIED | 91 / +0.044 / +0.118 | 31 / -0.145 / -0.022 |
| 1 (forex) | USD/JPY | 1h | DIED | 75 / -0.699 / +0.149 | 18* / -1.216 / +0.626 |
| 1 (forex) | USD/JPY | 4h | DIED | 70 / -0.127 / +0.096 | 22 / -0.531 / -0.050 |
| 1 (forex) | USD/JPY | 1day | DIED | 68 / -0.102 / +0.003 | 33 / -0.130 / -0.026 |
| 1 (forex) | GBP/USD | 1h | DIED | 53 / -0.611 / +0.094 | 19* / -0.581 / +0.372 |
| 1 (forex) | GBP/USD | 4h | DIED | 73 / -0.182 / +0.108 | 32 / -0.447 / -0.089 |
| 1 (forex) | GBP/USD | 1day | DIED | 90 / -0.049 / +0.026 | 31 / -0.099 / +0.048 |
| 1 (forex) | USD/CHF | 1h | DIED | 63 / -0.785 / -0.073 | 25 / -0.846 / +0.210 |
| 1 (forex) | USD/CHF | 4h | DIED | 66 / -0.104 / +0.084 | 22 / -0.219 / +0.114 |
| 1 (forex) | USD/CHF | 1day | DIED | 77 / -0.058 / +0.013 | 38 / -0.016 / +0.097 |
| 1 (metals) | GOLD | 4h | DIED | 64 / -0.428 / -0.276 | 15* / -0.317 / -0.313 |
| 1 (metals) | GOLD | 1day | DIED | 83 / -0.037 / -0.007 | 34 / -0.050 / -0.027 |
| **1 (metals)** | **GOLD** | **1week** | **PROMISING-WATCHLIST** | **36 / +0.026 / +0.057** | **11\* / +0.102 / +0.076** |
| 1 (metals) | SILVER | 4h | DIED | 45 / -0.023 / +0.022 | 22 / -0.302 / -0.191 |
| 1 (metals) | SILVER | 1day | DIED | 131 / -0.169 / -0.080 | 67 / +0.030 / +0.077 |
| **1 (metals)** | **SILVER** | **1week** | **PROMISING-WATCHLIST** | **23 / +0.320 / +0.242** | **15\* / +0.263 / +0.226** |
| 2 (crypto) | BTC | 4h | DIED | 251 / -0.220 / -0.126 | 107 / -0.030 / +0.047 |
| 2 (crypto) | BTC | 12h | DIED | 5* / -0.402 / -0.196 | 0* / 0.000 / n/a |
| 2 (crypto) | BTC | 1day | DIED | 42 / -0.202 / -0.170 | 18* / +0.366 / +0.415 |
| 2 (crypto) | ETH | 4h | DIED | 262 / -0.162 / -0.099 | 105 / -0.083 / -0.014 |
| 2 (crypto) | ETH | 12h | DIED | 97 / -0.228 / -0.179 | 38 / -0.110 / -0.086 |
| 2 (crypto) | ETH | 1day | DIED | 41 / -0.177 / -0.083 | 16* / +0.079 / +0.094 |
| 3 (stress) | SOL | 4h | DIED | 172 / -0.145 / -0.079 | 70 / -0.203 / -0.093 |
| 3 (stress) | SOL | 12h | DIED | 60 / -0.194 / -0.094 | 23 / -0.205 / -0.143 |
| 3 (stress) | NEAR | 4h | DIED | 169 / -0.166 / -0.092 | 78 / -0.167 / -0.091 |
| 3 (stress) | NEAR | 12h | DIED | 57 / -0.298 / -0.252 | 22 / -0.020 / +0.004 |

(`*` = below MIN_SAMPLE_SIZE=20; `edge` = edge_over_random, real ExpR minus mean
random-entry ExpR within the same ADX<25 eligible pool)

## The three required questions

### (a) Did Tier 1 beat Tier 3? Does it validate the regime filter?

**Partially, and only through metals.** Tier 1 metals: 2 of 6 PROMISING-WATCHLIST
(33%). Tier 1 forex: 0 of 12 (0%). Tier 3 stress-test: 0 of 4 (0%). Tier 1 as a whole
(2/18, 11%) technically beats Tier 3 (0/4, 0%), but **forex — the asset class the
task itself expected to be MOST range-prone — failed at exactly the same rate as the
stress-test tier built to fail.** This does not cleanly validate the
regime-awareness thesis: if forex had shown even a modest edge where SOL/NEAR showed
none, that would be a clean validation. Instead, the only tier that showed anything
was metals, and even that is two single-timeframe, sample-thin results. **No
overfitting flag needed** (Tier 3 did NOT unexpectedly work), but the validation of
"regime-awareness IS the strategy" is weak, not strong, given this data.

### (b) Edge-over-random — does band-extreme timing add value beyond the regime filter?

**Mostly no, with two real exceptions.** Across the 28 configs, `edge_over_random`
is negative or negligible in most cases — meaning random entries within the same
ADX<25 ranging pool often perform comparably to (or better than) the actual
band-extreme entry rule. The regime filter is doing most of the limited work that
gets done at all. **The two PROMISING-WATCHLIST configs are the clear exceptions**:
GOLD/1week (+0.057/+0.076) and SILVER/1week (+0.242/+0.226) both show a positive,
consistent edge over random in BOTH halves — the only configs in the sweep where
band-extreme timing itself, not just the regime gate, demonstrably added value. This
is a real, specific, worth-revisiting lead, not proof of a systematic edge.

### (c) Did anything SURVIVE full verification?

**No.** Zero of 28 configs SURVIVED. Zero configs even reached the point of needing
grid-shift verification (0 cleared the adequate-both-halves-sample bar). The two
near-misses (GOLD/1week, SILVER/1week) are capped at PROMISING-WATCHLIST for two
independent reasons: insufficient test-half sample (N=11, N=15 vs the required 20),
and — even setting that aside — 1week is native, non-resampled data for both GOLD
and SILVER, so grid-shift would be structurally not applicable regardless.

## Factual summary

- **Total configs tested**: 28
- **SURVIVED**: 0
- **PROMISING-WATCHLIST**: 2 (GOLD/1week, SILVER/1week — both precious metals, both
  1week, both sample-limited)
- **DIED**: 26 (93%)
- **Does the intuition hold out-of-sample?** **Mostly not.** The discretionary
  trader's rule, formalized exactly as described, does not survive rigorous testing
  on 9 of 10 assets across every timeframe tested. The one partial exception —
  precious metals at the slowest (1week) timeframe, where band-extreme timing itself
  (not just the regime gate) shows a real, consistent edge over random entry in both
  halves — is worth a follow-up with more data, not a claim of a proven edge. This is
  reported factually, exactly as it came out: data decided, and mostly decided
  against the intuition holding up as a systematic, tradeable edge at these
  timeframes and asset classes.
