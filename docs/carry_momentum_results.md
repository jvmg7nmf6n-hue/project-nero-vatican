# CARRY_MOMENTUM v1.0.0 — Results

See `docs/carry_momentum_data_audit.md` for the data audit (cleared; 3 daily +
5 monthly-substituted FRED series, all 7 forex pairs). Strategy:
`nero_core/strategies/carry_momentum.py`. 28 passing unit tests
(`tests/test_carry_momentum.py`). Sweep tool: `tools/carry_momentum_sweep.py`.

## Full results, both timeframes

| Timeframe | Verdict | Train N/ExpR/CI | Test N/ExpR/CI | Edge over random (train/test) |
|---|---|---|---|---|
| 1d | **DIED** | 653/-0.126/[-0.211,-0.041] | 277/-0.090/[-0.226,0.047] | -0.027 / -0.041 |
| 1week | **DIED** | 120/-0.111/[-0.304,0.090] | 116/-0.101/[-0.101,0.115] | -0.043 / +0.007 |

**Both timeframes negative on both halves.** 1d's train-half CI is entirely
negative (`[-0.211, -0.041]`, does not cross zero) — this is a confidently
negative result, not merely an unproven one. 1d clears the 20-trade adequacy bar
by a wide margin on both halves (N=653/277); 1week is adequately sampled too
(N=120/116).

## Mechanistic read

- **Edge over random is negative in 3 of 4 half-configs** — ranking by
  |rate differential| and picking the top 3 candidates performs WORSE than (or
  statistically indistinguishable from, in the one +0.007 case) picking
  randomly among momentum-passing candidates. The ranking step this strategy is
  built around does not appear to add value.
- **STOP dominates the exit mix everywhere** (1d train: 311 of 653 exits;
  1week train: 61 of 120) — roughly half of all positions get stopped out,
  consistent with a momentum filter that isn't actually confirming the carry is
  durable.
- **This is a well-sampled, confidently negative result**, not a thin one —
  unlike Hypothesis 1's PROMISING-WATCHLIST classification, CARRY_MOMENTUM
  reaches adequate sample size on both timeframes and still shows a negative
  CI on 1d's train half. There is no "wait for more data" argument here the way
  there is for a thin sample.

## Grid-shift

Not run — 1d DIED (grid-shift only applies to configs that would otherwise
qualify), and 1week is NOT_APPLICABLE regardless (native Twelve Data 1week
forex, not resampled from finer data in this sweep — same convention as every
other forex config in this project).

## Verdict

**0 SURVIVED. 0 PROMISING-WATCHLIST. 2 of 2 DIED.** Unlike Hypothesis 1, this is
not a "thin but positive, worth watching" case — both timeframes show a
consistently negative expectancy with an adequate sample and (on 1d) a CI that
doesn't even cross zero. The mechanism as specified (rank-and-select top-3 by
rate differential among momentum-passing candidates) does not show a tradeable
edge on this data. Nothing from this hypothesis is recommended for the
promotion list.
