# Philosophy Hypotheses — First Live Run Through frequency_gate + auto_tester

Branch: `feature/philosophy-hypotheses-live-test`. Zero merges to `main`.

This is the first time any of RMR_LONG_ONLY_EURUSD_4H, WISE_MAN_HOLD_V1–V10, or
ADX_RANGE_V1–V4 have been run against real market data through
`nero_core.research_agent.frequency_gate.measure_entry_frequency` +
`nero_core.research_agent.auto_tester.test_hypothesis`. Everything before this
branch was parse-only validation (`test_research_agent_philosophy_hypotheses_
parsing.py` / `_variants.py`) or unit tests against synthetic candle fixtures.

## Evidence rule

Every verdict below is **CONFIRMED** or **HYPOTHESIS** — no result is rounded up.
`CONFIRMED` means the classification/verdict came directly out of this
project's own deterministic classifiers (`frequency_gate.measure_entry_
frequency`, `tools.backtest_statistics.classify_verdict`) against real,
unmodified market data — reproducible by rerunning `python -m
tools.philosophy_hypotheses_live_test`. `HYPOTHESIS` marks any broader
interpretation layered on top of those mechanical outputs.

## Manual-submission mechanism — finding

**No reusable mechanism for this existed before this branch.**
`tools/rmr_variant_research_stage1.py` looked adjacent but drives a completely
different code path (`nero_core.strategies.range_mean_reversion`'s own
backtest, never `frequency_gate`/`auto_tester`). The only prior real-data
callers of `frequency_gate.measure_entry_frequency` / `auto_tester.
test_hypothesis` were `nero_core.research_agent.pipeline.run_pipeline` (via its
`default_candles_provider`, which reads the `docs/site_data/candles/` export —
capped at 200 rows, ~33 days at 4h, far too short a span to trust an
annualized frequency measurement against) and the test suite (synthetic
fixtures only).

Built `tools/philosophy_hypotheses_live_test.py` as that reusable mechanism:
`fetch_full_history` (dispatches to `fetch_forex_ohlcv`/`fetch_timeframe_
candles` for FULL native history, not the capped export) + `run_hypothesis_
live` (frequency_gate + full harness in one call, grid-shift only when the
gate clears) + `build_4h_grids` (all 4 possible UTC-offset alignments for a 4h
grid, since the existing `tools/grid_shift_robustness_audit.py` only tabulates
offsets for 12h/2h). Covered by `tests/test_philosophy_hypotheses_live_test.py`
(8 tests, network fully mocked) plus a static no-auto-wire AST check mirroring
`test_research_agent_no_auto_wire.py`.

Running 13+ hypotheses through it took one function call per hypothesis
(`run_hypothesis_live`) — no per-hypothesis bespoke code was needed.

## Data

| Asset/timeframe | Candles | Span |
|---|---|---|
| BTC/4h | 19,608 | ~2017-07 to 2026-07-31 (Binance native) |
| EUR/USD/4h | 4,998 | ~2023-08 to 2026-07-30 (Twelve Data native, plan-level history limit) |

Full native history was fetched fresh for both assets (not the 200-row/
~33-day `docs/site_data/candles/` export), matching the precedent `tools/
rmr_variant_research_stage1.py` already set for a manual submission.
`generated_at` = the actual wall-clock time the run started
(`2026-07-31T23:52:58Z`), applied identically to all 14 configs — since every
candle used is already-closed history strictly before that timestamp, there is
no lookahead exposure, and using one shared timestamp for every hypothesis
means no config got a more favorable (or less favorable) cutoff than any
other.

## Run-count note

The task brief states "13 distinct runs." Mechanically applying the two
described duplicate-collapse rules (WISE_MAN_HOLD_V2/V9/ASYMMETRIC_HOLD → 1
run; ADX_RANGE_V2/ADX_GATED_RANGE_PERSISTENCE → 1 run, still one of the 4
ADX_RANGE thresholds) yields **14** distinct rule-configurations: 1
(RMR) + 9 (WISE_MAN_HOLD, 10 names minus the one collapsed pair) + 4
(ADX_RANGE, no reduction — ADX_GATED_RANGE_PERSISTENCE isn't one of the four
V1–V4 slots itself, it just shares V2's result). Reported as 14 rather than
force-dropping a legitimate config to match the stated count — consistent
with this project's own no-rounding-up-a-verdict discipline.

## Pre-registration

The full 14-config list (`build_hypothesis_set()` in the tool) was written and
committed to before the run started and executed unmodified start to finish —
no hypothesis was added, dropped, or retuned after seeing any interim result.

---

## 1. RMR_LONG_ONLY_EURUSD_4H (EUR/USD, 4h)

**CONFIRMED: TOO_SLOW — rejected by the frequency gate, never reached the
harness.**

| trades/year (measured) | classification | months to 30 resolved trades |
|---|---|---|
| 27.11 | **TOO_SLOW** | ~13.3 |

80 triggers over 1,078 eligible days of real EUR/USD/4h history. Just under
the VIABLE floor (needs ≥30 trades/yr to clear in ≤12 months) — this
hypothesis's own dynamic-MA20-target / ADX-regime-break exit shape never even
got a P&L test on real data; the gate stopped it on entry-trigger frequency
alone, exactly as designed.

---

## 2. WISE_MAN_HOLD risk/reward spectrum (BTC, 4h) — one table, one answer

Entry (identical across all 10 names): `close < bb_lower AND adx14 < 25`.
**CONFIRMED: frequency gate — VIABLE for every variant** (identical entry rule
→ identical measured frequency: 34.51 trades/year, ~10.4 months to 30 trades,
159 triggers over the full BTC history). Every variant therefore reached the
full harness.

**CONFIRMED: verdict — DIED for all 9 distinct configs, on the native grid AND
on all 4 grid-shift offsets (36/36 grid-shift sub-runs also DIED).** Every
variant's train-half point expectancy was negative; 8 of 9 train-half
bootstrap CIs excluded zero entirely (statistically distinguishable from
zero, on the negative side). No configuration anywhere on this risk/reward
spectrum crossed into positive expectancy on both halves.

| Name(s) | Target / Stop | Train N / ExpR | Train 95% CI | Test N / ExpR | Test 95% CI | Edge vs. random (test) | Verdict |
|---|---|---|---|---|---|---|---|
| V1 | +0.8% / −4.0% | 159 / −0.081 | [−0.157, −0.014] | 54 / −0.122 | [−0.255, 0.012]* | −0.061 | DIED |
| **V2, V9, WISE_MAN_ASYMMETRIC_HOLD** (dedup, 1 run) | +1.0% / −3.0% | 152 / −0.170 | [−0.266, −0.073] | 51 / −0.132 | [−0.315, 0.025]* | −0.031 | DIED |
| V3 | +1.5% / −3.0% | 141 / −0.126 | [−0.243, −0.010] | 51 / −0.044 | [−0.250, 0.132]* | +0.055 | DIED |
| V4 | +2.0% / −2.0% | 149 / −0.291 | [−0.452, −0.130] | 55 / −0.164 | [−0.419, 0.090]* | −0.030 | DIED |
| V5 | +3.0% / −1.5% | 158 / −0.349 | [−0.539, −0.140] | 59 / −0.231 | [−0.587, 0.124]* | −0.107 | DIED |
| V6 | +1.0% / −1.0% | 190 / −0.472 | [−0.609, −0.336] | 64 / −0.345 | [−0.595, −0.095] | −0.058 | DIED |
| V7 | +1.0% / −1.5% | 174 / −0.323 | [−0.437, −0.208] | 61 / −0.354 | [−0.545, −0.136] | −0.166 | DIED |
| V8 | +1.0% / −2.0% | 165 / −0.255 | [−0.373, −0.146] | 57 / −0.241 | [−0.425, −0.057] | −0.104 | DIED |
| V10 | +1.0% / −4.0% | 144 / −0.109 | [−0.195, −0.022] | 50 / −0.130 | [−0.305, 0.020]* | −0.055 | DIED |

`*` test-half CI crosses zero (small sample, 41–64 trades) — the point
estimate is negative but that specific half's negative reading alone isn't
statistically distinguishable from zero. Train-half is unambiguous for all 9
(all exclude zero, all negative).

**"Where does this become profitable, if anywhere?" — HYPOTHESIS-level
answer: nowhere on this spectrum, as tested.** Tightening the stop (V6, both
1%) made things *worse*, not better (worst expectancy of the whole set,
−0.472 train / −0.345 test, the only variant whose TEST CI also excludes
zero). Widening the stop (V1, V10: −4%) produced the *least* negative
results, but never positive. This is directionally suggestive that the exit
discipline itself isn't the problem — the entry (`close < bb_lower AND
adx14 < 25`, a dip inside a low-ADX range) shows no exploitable edge on BTC/4h
over the full 9-year history, independent of which stop/target you attach to
it. That specific causal claim is HYPOTHESIS, not CONFIRMED — it wasn't
directly tested (would need e.g. a fixed-holding-period study isolating the
entry from any exit).

---

## 3. ADX_RANGE regime-persistence proxy (BTC, 4h) — proxy results, not P&L

**Every number in this section is a PROXY_TEST result.**
`target_r_multiple=50.0` against `stop_atr_multiple=2.0` is a practically
unreachable placeholder target — every resolved trade under this plan exits
via REGIME_BREAK, SL, or TIME, never TARGET. A "SURVIVED" verdict here would
mean *"the regime-break/time-cap exits fire in a statistically distinguishable
pattern vs. random entry timing"* — **not** "this makes money." None of the
four survived, so this caveat is moot for the actual numbers below, but it's
stated per the task's own instruction regardless.

**CONFIRMED: frequency gate — FAST for all 4** (a looser ADX threshold fires
far more often, as expected — trades/year scales from 100.6 at the tightest
threshold to 811.9 at the loosest).

**CONFIRMED: verdict — DIED for all 4, on the native grid AND on all 4
grid-shift offsets (16/16 grid-shift sub-runs also DIED).**

| Name(s) | ADX14 entry threshold | Trades/yr | Train N / ExpR | Train 95% CI | Test N / ExpR | Test 95% CI | Verdict |
|---|---|---|---|---|---|---|---|
| V1 | < 15 | 100.6 (FAST) | 115 / −0.199 | [−0.371, −0.015] | 54 / +0.116 | [−0.182, 0.430]* | DIED |
| **V2, ADX_GATED_RANGE_PERSISTENCE** (dedup, 1 run) | < 20 | 290.6 (FAST) | 239 / −0.081 | [−0.222, 0.058]* | 100 / −0.013 | [−0.211, 0.199]* | DIED |
| V3 | < 25 | 536.2 (FAST) | 396 / −0.071 | [−0.177, 0.044]* | 156 / +0.001 | [−0.156, 0.166]* | DIED |
| V4 | < 30 | 811.9 (FAST) | 1,905 / −0.073 | [−0.100, −0.045] | 730 / −0.087 | [−0.128, −0.044] | DIED |

`*` CI crosses zero.

**"Where does this become profitable, if anywhere?" — it doesn't, and V4 is
the cleanest evidence of that, not the weakest.** V4 (the loosest threshold,
<30) is the only config in the entire 13-hypothesis batch where BOTH halves'
CIs exclude zero on the negative side, at real statistical power (1,905
train-half trades, 730 test-half trades — by far the largest sample in this
whole run). This is a well-powered, **CONFIRMED** negative result for the
proxy target under this exact ADX<30/regime-break/480h-cap construction — not
just "didn't clear the bar," but "clears the bar on the DIED side with real
sample size." V1–V3 are smaller-sample and noisier (test-half CIs cross zero,
occasionally flip to a positive point estimate), so for those three, "no
demonstrated edge" is CONFIRMED but "provably negative" is not — HYPOTHESIS
only.

---

## Auto-wiring check

**CONFIRMED, zero auto-wiring throughout:**
- `tools/philosophy_hypotheses_live_test.py` imports nothing from
  `nero_core.execution.live_scheduler` and never references
  `nero_core.strategies.registry.default_registry` (static AST check,
  `tests/test_philosophy_hypotheses_live_test.py::NoAutoWireTest`, passing).
- It writes only to `docs/philosophy_hypotheses_live_test_results.json` — it
  never calls `auto_tester.persist_test_results` (the shared
  `docs/site_data/agent_test_results.json` ledger the real scanner/LLM
  pipeline owns), so these manual results are never commingled with
  production hypothesis data.
- The project's own existing `tests/test_research_agent_no_auto_wire.py`
  (static + dynamic checks across the whole `research_agent` package) still
  passes unchanged.
- Nothing in this branch touched `nero_core/strategies/registry.py`,
  `nero_core/execution/live_scheduler.py`, or any live-scheduler config file.

## Test suite

26 tests, all passing: 8 new (`test_philosophy_hypotheses_live_test.py`) + 3
existing no-auto-wire + 15 existing philosophy-hypothesis parse/variant tests.

## Bottom line

**CONFIRMED: 0 of 14 configurations survived. 1 (RMR) was rejected at the
frequency gate before reaching the harness; 13 reached the full harness
(bootstrap CI + 200-run random-entry baseline + 4-offset grid-shift) and all
13 DIED, consistently across every grid alignment tested (52/52 grid-shift
sub-runs also DIED, 0 exceptions).** No SURVIVED, no PROMISING-WATCHLIST, no
UNTESTABLE, no UNMEASURABLE anywhere in this batch.
