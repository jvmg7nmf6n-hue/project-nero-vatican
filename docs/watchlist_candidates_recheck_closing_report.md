# Watchlist Candidates Recheck — Closing Report

Branch: `feature/watchlist-candidates-recheck`. Not merged to `main`.

## Premise correction

The task brief named 5 candidates that don't exist anywhere in this repo. The
real story it was describing is the **RMR Variant Research Cycle**
(mid-July 2026, a separate and unrelated body of work from the
philosophy-hypotheses exploration). Full detail:
`docs/watchlist_candidates_recheck_task1_scope.md`.

## Task 1: total combinations scanned

**6 distinct (variant, asset, timeframe) combinations** were run across
Stages 1 and 3 of the RMR cycle to produce the 3 real PROMISING-WATCHLIST
candidates rechecked below:

| Config | Asset/TF | Original verdict |
|---|---|---|
| RMR_LONG_ONLY_EURUSD_4H | EUR/USD/4h | DIED |
| RMR_ADX_FALLING_ETH_4H | ETH/4h | DIED |
| RMR_LONG_ONLY_BTC_1D | BTC/1d | PROMISING-WATCHLIST |
| RMR_CONFIRMATION_BTC_1D | BTC/1d | PROMISING-WATCHLIST |
| RMR_LONG_ONLY_CONFIRMATION_BTC_1D | BTC/1d | PROMISING-WATCHLIST |
| v1.1.0-long-only on ETH/4h (Refinement 2) | ETH/4h | DIED |

3 of 6 DIED, 3 of 6 (all BTC/1d) PROMISING-WATCHLIST, 0 of 6 SURVIVED.

## Task 2: out-of-sample window

**Direction used: forward (more recent), not backward.** BTC/1d's original
runs already fetched FULL available history (`fetch_timeframe_candles` →
Binance native, 2017-08-17 onward) — there is no earlier untouched window;
the entire back-history was already consumed by the original 70/30
chronological split. The only genuinely untouched data is whatever has
accrued since the original run.

**Cutoff: 2026-07-19T00:00:00Z**, derived from the original commit timestamps
(Stage 1: `dd24839`, 2026-07-20 04:26:29 +0500 = 2026-07-19 23:26:29 UTC;
Stage 3: `373a8fb`, 2026-07-20 04:39:16 +0500 = 2026-07-19 23:39:16 UTC — both
before that day's Binance daily candle closes at 23:59:59 UTC, so 2026-07-18
was the last complete candle either run could have seen).

**Result as of this recheck (2026-08-01): only 13 candles exist after the
cutoff** (2026-07-19 through 2026-07-31). Per this branch's own no-warmup-
leakage rule (candles before the cutoff are never used, not even for
indicator warmup — see `tools/watchlist_candidates_recheck.py`'s own
docstring), a 13-candle window cannot produce a single indicator-warmed row
for this strategy family (`sma20`/Bollinger needs 20 trailing candles,
`adx14`'s double-smoothing needs ~28) — confirmed empirically, not assumed:
0 trades in both the (9-candle) train and (4-candle) test half, for all 3
candidates.

**This is exactly the scenario Task 2 anticipated**: *"If no genuinely
untouched data exists for a given pair..., flag as UNTESTABLE for lack of
fresh data rather than quietly rerunning on the same window."* All 3
candidates are reported UNTESTABLE, not DIED and not re-run against
overlapping data.

## Task 3: per-candidate classification (harness-native, no manual override)

| Candidate | Train N | Test N | Win rate | Expectancy R | Profit factor | CI (train/test) | Verdict |
|---|---|---|---|---|---|---|---|
| RMR_LONG_ONLY_BTC_1D | 0 | 0 | — | — | — | — | **UNTESTABLE** |
| RMR_CONFIRMATION_BTC_1D | 0 | 0 | — | — | — | — | **UNTESTABLE** |
| RMR_LONG_ONLY_CONFIRMATION_BTC_1D | 0 | 0 | — | — | — | — | **UNTESTABLE** |

Every "—" is a genuine absence, not a rounding of a real number to nothing:
`classify_verdict`, `bootstrap_mean_r_ci`, and the random-entry baseline were
never called for any of the 3 (see `recheck_candidate`'s own gate) because
there is no trade data to feed them. The alternative — letting
`classify_verdict` run anyway on two zero-trade halves — would have printed
**DIED** (its own logic reads `expectancy_r=0.0` as "not > 0"), which would
misrepresent "no evidence exists yet" as "tested and it lost." UNTESTABLE is
the harness's own honest answer to a question it wasn't given enough data to
answer, not a manual override of what it *did* compute.

Grid-shift: not attempted, per Task 1's disclosure — BTC/1d is native daily
data in this pipeline (not resampled from hourly), an already-settled
structural fact inherited from the original research, not a gap this recheck
was asked to close.

## Did it hold up, weaken, or reverse?

**None of the above — it's genuinely untested, which is a different and more
honest answer than any of the three.** The original Stage 4 verdict already
said the right thing about this exact scenario: *"the three BTC/1d configs
are reasonable candidates to re-test once more BTC daily history accrues... a
'keep watching with more data' recommendation, not a 'wire it now' one."*
Twelve days later, that's still accurate almost to the letter — daily data
accrues at exactly one candle per day, and 13 fresh candles is nowhere near
enough for even a single one of these low-frequency (historically ~3-4
trades/year at most) strategies to generate a fresh signal, let alone enough
for bootstrap CI or a random-entry baseline comparison to mean anything.

**No promotion recommendation changes as a result of this recheck.** Stage
4's original conclusion — nothing merits live wiring yet, all three remain
sample-limited "keep watching" candidates — stands unmodified. This tool
(`tools/watchlist_candidates_recheck.py`) is built to be re-run later, as more
BTC/1d history accrues, without modification — at that point it will either
produce a genuine classify_verdict outcome or continue reporting UNTESTABLE
with an updated (larger) out-of-sample candle count, honestly reflecting
whatever has actually accumulated.

## Test suite

Full suite: 1844 tests, all passing (11 new for this branch: out-of-sample
window selection never overlaps the original window, classification path
proven to reuse the literal original function objects, and the UNTESTABLE
gate proven both for zero out-of-sample candles and for a too-thin window).

## Zero auto-wiring

This branch touches only `tools/watchlist_candidates_recheck.py` and its
tests/docs. No changes to `nero_core.execution.live_scheduler`,
`nero_core.strategies.registry`, or any live scheduler config. Results are
written only to `docs/watchlist_candidates_recheck_results.json` — never to
any shared production ledger.
