# Ranging-Regime Research Batch — R1: REGIME_TRANSITION

**Question: does trading the regime CHANGE itself (a mature range ending) work?**

New strategy `nero_core/strategies/regime_transition.py` (regime-transition-v1.0.0),
reusing RANGE_MEAN_REVERSION's `adx()` directly (no new ADX implementation). State
machine: RANGING while ADX(14) < 25; a "mature range" once that holds for >= 10
consecutive closed candles; a TRANSITION signal fires when ADX crosses >= 25 AND the
same candle's close clears the FROZEN boundary (high/low of the mature-range candles
only — the transition candle itself is excluded from that computation, no
self-reference). Executed at the NEXT candle's open. Stop: nearer of the frozen
range's midpoint or 2.5x ATR(14) (a ceiling), floored at 0.75x ATR(14). Target: 2x
the frozen range height from the breakout close. Exit also on ADX falling back below
20 (failed transition) or a timeframe-aware holding cap.

30 new unit tests (`tests/test_regime_transition.py`): streak/maturity detection,
no-self-reference boundary freezing, stop ceiling/floor selection (with aggregate
stop-type tracking), target math, failed-transition exit, short accounting, and
registration discipline. All pass.

## Random-entry baseline design

R1's mechanism has two independent parts: (a) a mature range ENDING (the ADX-cross
condition alone), and (b) the ending candle's close actually clearing the frozen
boundary (the directional trigger). `tools/regime_transition_sweep.py`'s baseline
isolates (b)'s value: `mature_range_candidates` finds every candle where (a) fires
regardless of the boundary check — a strict superset of the real strategy's actual
entries — then fires a random-direction entry at a random subset of that pool
(matched to the real trade count), through the identical stop/target/exit mechanics.
This asks the same question RANGE_MEAN_REVERSION's own baseline asked (is the entry
TRIGGER adding value beyond the regime condition alone), adapted to R1's transition
mechanism.

## Full sweep: BTC/ETH (4h/12h/1d), GOLD/SILVER (1d/1week), EURUSD/USDJPY (4h/1d)

| Config | Verdict | Train N/ExpR | Test N/ExpR |
|---|---|---|---|
| BTC / 4h | DIED | 20/+0.694 | 11*/-0.117 |
| BTC / 12h | DIED | 8*/+0.458 | 6*/-0.382 |
| BTC / 1d | DIED | 5*/+0.791 | 0*/0.000 |
| ETH / 4h | **PROMISING-WATCHLIST** | 25/+0.359 | 13*/+0.257 |
| ETH / 12h | DIED | 3*/-0.726 | 4*/-0.375 |
| ETH / 1d | **PROMISING-WATCHLIST** | 8*/+1.330 | 2*/+1.002 |
| GOLD / 1d | DIED | 10*/-0.197 | 5*/+0.279 |
| GOLD / 1week | DIED | 5*/+0.814 | 0*/0.000 |
| SILVER / 1d | DIED | 21/+0.201 | 9*/-0.185 |
| SILVER / 1week | DIED | 2*/+3.137 | 0*/0.000 |
| EURUSD / 4h | DIED | 4*/-0.431 | 4*/-0.494 |
| EURUSD / 1d | **PROMISING-WATCHLIST** | 5*/+0.108 | 2*/+0.231 |
| USDJPY / 4h | DIED | 11*/-0.735 | 0*/0.000 |
| USDJPY / 1d | DIED | 11*/+0.249 | 5*/-0.259 |

**3 of 14 configs PROMISING-WATCHLIST (ETH/4h, ETH/1d, EURUSD/1d). 11 DIED. 0
SURVIVED.** Every PROMISING-WATCHLIST config carries a LOW SAMPLE flag on at least
one half (2-13 trades against the 20-trade bar) — genuinely thin, consistent with
this whole batch's mechanism being rare by construction (a 10-candle mature range
followed by a qualifying transition is a low-frequency event on any timeframe).

## Grid-shift

**0 of 14 configs meet the qualifying bar** (both halves >= 20 trades AND positive
both halves) — the precondition this task's own rule sets for grid-shift
verification. ETH/4h comes closest (train N=25 clears the bar, test N=13 does not).
Per the corrected understanding from this session's own RMR Stage 3 (resampling 1h
BTC/ETH data to 4h/12h at different offsets genuinely IS grid-shift testable —
crypto's continuous trading produces identical bin counts at every offset, unlike
"native 4h also exists" implying nothing about resampling-offset sensitivity), ETH/4h
WOULD have been a real candidate for offset-sensitivity testing had it cleared the
sample bar. It didn't, so grid-shift was not run on any config — nothing to test,
not something skipped.

## Mechanistic notes (factual, not spun)

- **TIME is the single most common exit reason across almost every config**
  (e.g. BTC/4h train: TIME=8 of 20, 40%) — most transition trades neither hit their
  stop nor their target before the holding cap expires. The 2x-range-height target
  is frequently too far given how rare and often short-lived these transitions are.
- **The 0.75x ATR floor never once bound the stop across all 14 configs, both
  halves** (`atr_floor: 0` in every single stop-type count printed) — in real market
  data, the midpoint/ceiling nearer-of comparison never produced a distance smaller
  than 0.75x ATR. The floor rule is not doing observable work here, though it remains
  a documented, defensible safety rail rather than a proven-unnecessary one (14
  configs is not exhaustive).
- **GOLD data was rate-limited (HTTP 429) on the first sweep pass**; both configs
  were re-fetched successfully on a lower-frequency retry and are included above —
  not fabricated, not silently dropped.

## Verdict: does regime-transition trading work?

**Not established.** 3 of 14 configs are directionally promising but every one is
sample-limited (well under the 20-trade adequacy bar on at least one half) and none
reached grid-shift eligibility. The mechanism is real (the state machine correctly
detects mature ranges, freezes boundaries without self-reference, and executes with
documented stop/target logic — all verified by 30 passing unit tests), but the
live-market signal is, on this data, indistinguishable from noise at the sample
sizes available. **Nothing from R1 is promoted or wired anywhere.**
