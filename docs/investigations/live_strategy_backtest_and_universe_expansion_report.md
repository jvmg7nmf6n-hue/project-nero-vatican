# Live-Strategy Backtest, Adam's Data Path, and Universe Expansion — Session Report

**Branch:** `feature/eve-engine-v1`, continuing directly from
`docs/investigations/eve_engine_v1_report.md`'s own "Follow-up session"
section (positive control, silent-fallback fix, budget-ledger 401/403/429
fix). **Not pushed, not merged.** Phase 4 (a real, paid Eve session) was
**not run** — every item below is either $0 (pure code, real market data
fetches, or statistical computation against already-fetched data) or
explicitly report-only, per this session's own instruction.

## Item 1 — Backtesting the existing live strategies

### 1a. Which (asset, timeframe) pairs the live strategies actually use

Every strategy in `nero_core/execution/live_scheduler.py`'s `SINGLE_ASSET_CONFIGS`,
`DONCHIAN_FOREX_CONFIGS`, plus the three bespoke-fetch strategies
(`COINTEGRATION_PAIRS`, `GOLD_SILVER_RATIO_MR`, `PEAD`) and the two
no-backtest-exists strategies (`NEWS_SENTIMENT`, `ORDERFLOW_IMBALANCE`):

| Strategy | Asset(s) | Timeframe | In `APPROVED_RESEARCH_UNIVERSE`? | In `APPROVED_EVALUATION_UNIVERSE`? |
|---|---|---|---|---|
| BREAKOUT_MOMENTUM (gold-calibrated) | GOLD | 1week | No | No |
| TREND_PULLBACK | BNB | 12h | No | No |
| BREAKOUT_MOMENTUM (silver-calibrated) | SILVER | 24h | No | No |
| TREND_PULLBACK (silver-calibrated) | SILVER | 24h | No | No |
| VOLATILITY_SQUEEZE ×3 (ma100/150/200, silver-calibrated) | SILVER | 24h | No | No |
| RANGE_MEAN_REVERSION | GOLD | 1week | No | No |
| RANGE_MEAN_REVERSION | SILVER | 1week | No | No |
| RANGE_MEAN_REVERSION (long-only) | **BTC** | **24h** | No | **Yes (added this session)** |
| RANGE_MEAN_REVERSION (confirmation) | **BTC** | **24h** | No | **Yes (added this session)** |
| DONCHIAN_TREND (bracket) | GOLD | 1week | No | No |
| DONCHIAN_TREND (bracket) | EUR/USD, GBP/USD | 1week | No | No |
| DONCHIAN_TREND (bracket) | USD/JPY | 1week | No | No |
| COINTEGRATION_PAIRS | BTC-ETH | 12h | No | No (investigated, not added — see 1d) |
| GOLD_SILVER_RATIO_MR | GOLD-SILVER | 24h (1day) | No | No |
| PEAD ×2 configs ×7 tickers | AAPL/MSFT/GOOGL/TSLA/AMZN/NVDA/META | 1day, event-driven | No | No |
| NEWS_SENTIMENT (no backtest — forward-test only) | GOLD, BTC | daily cadence, no candle timeframe | No | No |
| ORDERFLOW_IMBALANCE (no backtest exists — see its own module docstring) | BTC, ETH | 1h snapshot | No | No |

**Zero live strategies run on BTC/4h** — the only pair in
`APPROVED_RESEARCH_UNIVERSE` before this session, and still the only 4h
pair any live strategy could have matched. More strikingly: **zero live
strategies run at 4h at all**, on any asset (see item 1e below).

Two BTC strategies (both `RANGE_MEAN_REVERSION` variants, BTC/24h) had
never been backtested against more than 200 candles until this session,
because more than 200 candles didn't exist as an export until this
session. Per the user's explicit direction, a new, separate
`APPROVED_EVALUATION_UNIVERSE` was created for evaluating these
already-live, human-chosen strategies — distinct from
`APPROVED_RESEARCH_UNIVERSE` (Eve/Adam's hypothesis-search space) since
evaluating a fixed, pre-existing strategy is not itself a hypothesis
search and doesn't carry the same multiple-comparisons risk. The two
universes are disjoint by construction (asserted at import time in
`nero_core/asset_universe.py`) and are never available to Eve's or Adam's
scoring paths for each other's pairs — enforced with
`DataSourceRefusedError` and tested directly
(`tests/test_asset_universe.py::EvaluationUniverseNeverScorableTest`).

### 1b/1c. BTC/24h backtest results

**Export:** 1800 daily candles, 2021-08-29 to 2026-08-02 (**4.93 years**,
Binance) — deliberately NOT a naive "2 years" window: at daily resolution
that would leave only ~220 out-of-sample candles, reproducing the exact
too-thin-a-window problem this whole investigation started by fixing for
BTC/4h. Written to `docs/research_data/evaluation_candles/BTC_24h.json`
(structurally separate directory from the search-universe exports).

**Random baseline computed first** (K=200, pure code, $0, before scoring
anything real): **0/200 SURVIVED, 0/200 PROMISING-WATCHLIST**, 64 DIED,
136 SKIPPED (mostly `TOO_SLOW` — daily candles trigger far less often than
4h ones). Chance-survival rate: **below ~1.5%** (95% upper bound, rule of
three on 0 events in 200 trials).

**Both live variants**, run through `tools.backtest_train_test_split.
split_chronological` + `tools.backtest_statistics.bootstrap_mean_r_ci` +
`classify_verdict` (the same statistical apparatus Adam/Eve hypotheses
use) applied to trades from these strategies' **own real entry/exit/sizing
logic** (`tools.backtest_compare.run_backtest` — `rule_dsl`/`auto_tester.
test_hypothesis` cannot express `RANGE_MEAN_REVERSION`'s ADX regime gate,
SMA20 reversion target, or direction-aware sizing at all, so that harness
was never a structural fit here):

| Variant | IS trades | IS ExpR | verdict_is | OOS trades | OOS ExpR | verdict_oos | combined | observed freq. |
|---|---|---|---|---|---|---|---|---|
| long-only (v1.1.0) | 10 | −0.28R | DIED | 5 | +0.74R | INSUFFICIENT_SAMPLE | DIED | ~3.05/yr → **TOO_SLOW** (~118 months to 30 trades) |
| confirmation (v1.3.0) | 9 | −0.10R | DIED | 7 | +0.43R | INSUFFICIENT_SAMPLE | DIED | ~3.25/yr → **TOO_SLOW** (~111 months to 30 trades) |

`verdict_is`/`verdict_oos` mirror `nero_core.eve.scoring._map_half_verdict`'s
own self-compared-half derivation exactly, applied here for methodological
consistency with the rest of this project's own convention — never a
re-derivation of `classify_verdict`'s DIED/SURVIVED branch logic itself.
Frequency classification uses `frequency_gate`'s own thresholds
(`TARGET_RESOLVED_TRADES=30`, `FAST_MAX_MONTHS=6`, `VIABLE_MAX_MONTHS=12`)
applied to the **observed** combined-halves trade rate, since neither
variant has a `rule_dsl` representation `frequency_gate.
measure_entry_frequency` could run against directly — flagged as a
methodology deviation, not a silent substitution.

**Both variants would have been rejected `TOO_SLOW` by the frequency gate
before ever reaching a backtest, had either been proposed and gated the
way Adam/Eve hypotheses are.** Neither is a proven edge on this data.

Fully deterministic regression test:
`tests/test_btc_24h_evaluation_backtest.py` (fixed export file, fixed
bootstrap/random-baseline seeds — reproduces these exact numbers).

### Backtest vs. live paper-trade comparison

Both variants only started logging on **2026-07-22**, giving an **11-day**
live window (2026-07-22 to 2026-08-02, 25 total `execution_log` rows,
mostly `NO_TRADE`):

| Variant | Live trades (truth_ledger.db) | Live result |
|---|---|---|
| long-only | **0** | No trade ever opened in the live window |
| confirmation | **1** | ENTRY 2026-07-28 @ 66073.38, EXIT 2026-07-28 (next daily candle) @ 64096.14, `REVERSION_TARGET`, **+0.604R** |

**This comparison is honestly not statistically meaningful — N=0 and N=1.**
Reported per the task's own instruction ("report the comparison even if
unflattering," and an honest N=1 is exactly that kind of unflattering-but-
necessary report): there is not enough live history yet to say whether the
backtest models reality or diverges from it. The one live trade that did
occur (+0.604R) is directionally consistent with the backtest's own
out-of-sample half (positive expectancy, +0.43R for the confirmation
variant) — but a single data point proves nothing on its own, and this
report does not claim it does. A real comparison needs the live window to
grow for months, not days.

### 1d. COINTEGRATION_PAIRS — investigated, not built

Outcome: **UNTESTABLE by `auto_tester`, confirmed at the code level, not
just by assumption.** `nero_core/strategies/cointegration_pairs.py`'s own
module docstring states it directly: *"Unlike every other strategy in this
codebase, this one needs TWO aligned price series at once, so it does not
fit the single-asset add_indicators/evaluate_entry/size_entry/VariantSpec
shape used elsewhere — it has its own self-contained state machine and
backtest loop."* Concretely:

- `auto_tester.test_hypothesis(hypothesis, candles, now)` takes exactly
  **one** `candles` DataFrame — there is no parameter for a second asset's
  series at all.
- `rule_dsl.ALLOWED_FIELDS` (`close`, `ma20`, `ma50`, `ma200`, `zscore20`,
  `atr14`, `rsi14`, `adx14`, `bb_lower`, `bb_upper`, `ret_1`, `volume`) are
  all single-series fields computed from one asset's own OHLCV —
  `compute_indicator_frame` always **re-derives** `zscore20` from whatever
  `close` column it's given; it has no way to accept a pre-computed
  cross-asset spread/z-score, and no field-vs-field comparison spans two
  independent assets' own frames.
- The strategy's own entry/exit is a hedge-ratio spread + Engle-Granger
  cointegration gate + a two-leg `entry_side` state machine — not
  expressible as an AND of single-series `Condition`s no matter how the
  DSL were extended incrementally.

No number was forced. `APPROVED_EVALUATION_UNIVERSE` does **not** include
BTC-ETH/12h.

### 1e. The 4h-vs-deployment-timeframe mismatch (report only)

**Every live strategy runs at 1week, 1day, 24h, 12h, or a 1h snapshot.
Zero run at 4h — the timeframe `APPROVED_RESEARCH_UNIVERSE` occupies
entirely** (BTC/4h, ETH/4h, SOL/4h, PAXG/4h, per item 3 below). This means
Eve's very first real proposals, however good, will be on a timeframe
nothing in this project has ever actually deployed.

The tradeoff, stated explicitly for a human decision (not acted on here):

- **4h gives ~6× the candles** of 24h over the same wall-clock window
  (4400 4h-candles ≈ 2 years vs. 1800 24h-candles ≈ 4.9 years for a
  comparable row count) and correspondingly more trades per backtest
  window — the reason 4h was chosen first for the research universe: it's
  the timeframe where `MIN_SAMPLE_SIZE=20`-trade adequacy is realistically
  reachable within a 2-year export.
- **24h/12h match what's actually deployed** — a real edge found at 4h is
  not evidence a similar edge exists at the cadence any live strategy
  actually trades on; timeframe-specific microstructure, fee drag, and
  regime persistence all differ.
- This project's own historical audit already found the OPPOSITE problem
  at slow timeframes (`frequency_gate.py`'s own docstring: *"25 of
  Vatican's 27 live configs have an expected time-to-30-resolved-trades of
  3-25 YEARS"*) — this session's own BTC/24h finding (both live RMR
  variants ~3 trades/year, `TOO_SLOW`) is a fresh, direct confirmation of
  that exact same finding, not a new phenomenon.

**Flagged for human decision, not resolved here**: should Eve's search
universe eventually include a slower-timeframe pair matching real
deployment cadence, accepting fewer OOS trades per export? Or should any
future live deployment target faster timeframes where more evidence can
actually accumulate? Both are legitimate; this session takes no position.

## Item 2 — Adam's data path

Adam's `nero_core.research_agent.pipeline.default_candles_provider` read
**only** the 200-row site display export — the same data source already
proven meaningless for backtesting (ma200 NaN everywhere but the last row,
0/200 random baseline hypotheses ever reaching `MIN_SAMPLE_SIZE`
out-of-sample trades). It now applies the **identical** refuse-don't-degrade
discipline Eve already had:

- Raises `DataSourceRefusedError` (Adam's own, independently defined — not
  imported from Eve, so the two remain fully independent systems with no
  cross-import) for any pair outside `APPROVED_RESEARCH_UNIVERSE`, or an
  `APPROVED_EVALUATION_UNIVERSE` pair, or one whose research export file is
  missing.
- Tags successful reads with `.attrs["data_source"]`/`.attrs["row_count"]`,
  matching Eve's own convention.
- `run_pipeline`'s per-hypothesis loop catches the refusal into a new,
  distinct counter, `data_source_refused` (on `PipelineRunResult`) —
  separate from `no_candles_available` (no export exists at all for this
  pair) and never crashes the run.

**What this required, and isolation impact:** `APPROVED_RESEARCH_UNIVERSE`/
`APPROVED_EVALUATION_UNIVERSE` were moved out of `nero_core/eve/pipeline.py`
into a new shared module, `nero_core/asset_universe.py` (re-exported from
Eve's own module under their original names for backward compatibility),
imported by **both** `nero_core/eve/pipeline.py` and `nero_core/
research_agent/pipeline.py`. This is a new cross-cutting dependency for
both systems on one shared, neutral module — **not** a dependency of either
system on the other. Confirmed directly: Adam's own isolation test
(`test_research_agent_no_auto_wire.py`) only forbids `live_scheduler`/
`default_registry` references, which this change doesn't touch; Eve's own
isolation test (`test_eve_no_auto_wire.py`, including the static
research_agent-import-boundary check) still passes unchanged — importing
`nero_core.asset_universe` is not importing `nero_core.research_agent`.
Both isolation suites pass (`184` and `315` tests respectively, both `OK`).

**Adam has not been run** with this change — report only, per this
session's explicit instruction. Adam has never scored a hypothesis in this
project's history at all (every real run either made zero LLM calls
deliberately, or hit 401 Unauthorized on all 3 calls — see the prior
session's own closing report).

## Item 3 — Asset universe expansion (pre-registered)

Declared **before** any of ETH/SOL/PAXG's own results existed, binding in
both directions (every declared asset gets run regardless of earlier
results; no asset gets added later just because earlier ones came up
empty):

**Included:** BTCUSDT, ETHUSDT, SOLUSDT, PAXGUSDT — all Binance, all
liquid, all with multi-year history.

**Excluded, with reasons, decided at the same time:**
- **NEAR** — shorter Binance listing history, thinner liquidity.
- **DOGE** — meme/news-driven price regime; any backtest edge found would
  be regime-specific by nature (a viral news cycle, not a persistent
  structural inefficiency), so it wouldn't generalize the way a
  structural edge should.

For each of ETH, SOL, PAXG: a 4400-candle 4h research export (2024-07-30
to 2026-08-02, 2.01 years — identical pipeline to BTC/4h's own export) was
built, and its own K=200 random-hypothesis baseline was computed **before**
adding the pair to `APPROVED_RESEARCH_UNIVERSE`. BTC/4h's own baseline was
also re-run this session with the identical methodology (its original run,
prior session, was never saved to disk — only reported in prose), so all
four pairs now have a consistent, comparable, reproducible on-disk record:

| Asset/TF | SURVIVED | PROMISING-WATCHLIST | DIED | SKIPPED | Chance-survival ceiling |
|---|---|---|---|---|---|
| BTC/4h | 0/200 | 0/200 | 69 | 131 | below ~1.5% (rule of three, 0/200) |
| ETH/4h | 0/200 | **3/200** | 63 | 134 | below ~1.5% (rule of three, 0/200) |
| SOL/4h | 0/200 | 0/200 | 70 | 130 | below ~1.5% (rule of three, 0/200) |
| PAXG/4h | 0/200 | **8/200** | 63 | 129 | below ~1.5% (rule of three, 0/200) |

**Every asset stays below the ~1.5% SURVIVED ceiling — but the
PROMISING-WATCHLIST rate (thin/marginal false signals under pure chance)
ranges from 0% (SOL) to 4% (PAXG), a real, measured 8x spread.** This is
the standing rule's own premise, directly confirmed, not merely asserted:
**a baseline does not transfer between assets**, even when none of them
ever reach SURVIVED. PAXG (a gold-pegged token, structurally different
volatility/regime character from the other three) shows the highest noise
floor — worth remembering if Eve or Adam ever propose something
PAXG-specific that looks marginally positive: PAXG's own baseline says
that happens by chance alone roughly 8x more often than on SOL.

Note on methodology consistency: BTC/4h's re-run and the three new assets'
runs all use the single **combined-verdict** method (`auto_tester.
test_hypothesis`'s own `result.verdict`, matching this session's BTC/24h
evaluation-universe methodology). The **original** BTC/4h finding from the
prior session (`docs/investigations/eve_engine_v1_report.md`) used Eve's
own `scoring.py` **IS/OOS-split** method and reported 0/200 SURVIVED
out-of-sample with 17/200 `PROMISING_WATCHLIST` **in-sample** (all 17 died
out-of-sample) — a different, stricter split. Both are real, both are
recorded (`docs/investigations/btc_4h_random_baseline_result.json` states
this explicitly), and they are not expected to agree exactly since they
measure different things.

`APPROVED_RESEARCH_UNIVERSE` now reads
`{("BTC","4h"), ("ETH","4h"), ("SOL","4h"), ("PAXG","4h")}` — verified by a
new test asserting the exact set (not just membership), plus a new test
asserting every pair in the universe has both its own export and its own
baseline result file on disk (the standing rule, checked mechanically, not
just documented).

### Joint multiplicity across the full 4-asset family

Using the task's own working ceiling — **~40 hypotheses per asset**
reaching a real, sufficiently-sampled backtest (this figure's origin: the
original BTC/4h random-baseline investigation found 40 of 200 random
hypotheses reached a computed out-of-sample p-value at all, i.e. had
`>= MIN_SAMPLE_SIZE` OOS trades — see commit `a0771c4`) — a full Eve
deployment across all four research-universe assets implies a family of
roughly **4 × 40 = 160 hypotheses**.

- **Uncorrected**, at a naive p < 0.05 significance threshold across 160
  tests, the **expected number of false positives under the global null is
  160 × 0.05 = 8** — this is exactly why a correction is required once the
  universe expands past one asset, not an abstract concern.
- **Per-asset FDR (wrong, per this session's own instruction)**: running
  Benjamini-Hochberg separately within each ~40-hypothesis asset family
  controls each family's own false discovery rate at 5% individually — but
  the chance that **at least one** of the four independent per-asset
  procedures yields a false discovery compounds: illustratively,
  `1 − (1 − 0.05)⁴ ≈ 18.5%`, well above any single asset's own nominal 5%.
- **Joint FDR across the full 160-hypothesis family (correct, as
  instructed)**: Benjamini-Hochberg run **once**, over all scored
  hypotheses from all four assets pooled together, keeps the family-wise
  false discovery rate at 5% for the whole 160-hypothesis family. The
  **joint bar** a single, otherwise-isolated top result would need to
  clear is the rank-1 BH threshold: `p ≤ (1/160) × 0.05 ≈ 0.0003125` (~1 in
  3200) — a Bonferroni-strength requirement for one standout hit with
  nothing else nearby it, **far** stricter than either a raw p < 0.05 or a
  per-asset-only correction would demand.

This is a **pre-registered constraint on interpretation**, not a new code
change — `nero_core.eve.scoring.apply_fdr_correction` already implements
Benjamini-Hochberg correctly (proven in Phase 3's own tests); the
requirement here is **procedural**: any future real cross-asset Eve
scoring pass must call it **once** over the pooled family across all
proposed hypotheses from all assets that session touched, never once per
asset. Flagged for explicit confirmation before Phase 4: `nero_core.eve.
pipeline.run_pipeline` currently calls `apply_fdr_correction` once per
session already (not per asset) — confirmed by reading `pipeline.py`
directly — so **this requirement is already satisfied by the existing
code**, provided a single session is the unit that's ever pooled. If a
future analysis pools multiple SESSIONS together across assets, that
pooling would need to be done explicitly at read time, since each
session's own `apply_fdr_correction` call only sees that session's own
hypotheses.

## Item 4 — Phase 4 readiness check (report only)

### Ready, verified this session

1. **Kill switch.** `EVE_ENABLED` defaults `False`; confirmed `False` in
   the current local environment (checked directly, not assumed); zero
   references to `EVE_ENABLED` anywhere in `.github/workflows/*.yml` — no
   automated cron can trigger Eve even if the env var were flipped,
   without also adding a workflow step (a second, independent gate).
2. **Session/month budget enforcement.** `pre_call_check` enforces both
   `MONTH_CEILING_USD = $20` (a hardcoded code constant, deliberately
   **not** env-configurable — can't be silently raised by a stray env var)
   and `EVE_SESSION_BUDGET_USD` (env-configurable, defaults `$1.50`)
   before **every single call**, using a worst-case **projected** bound,
   never an average — Phase 1's own 18 tests plus this session's new
   released-reservation tests all pass.
3. **The 401/403/429 ledger fix** (this session): a rejected-before-token-
   processing call now releases its reservation (counted as exactly $0)
   instead of permanently phantom-counting spend at its projected value.
   Every other failure mode (5xx, network timeout) still conservatively
   counts the reservation, correctly — the true outcome is genuinely
   unknown in those cases, unlike a confirmed-$0 auth/rate-limit rejection.
4. **Session-done signal.** Explicit `end_session` client tool, tested
   directly (`test_eve_session_termination.py`).
5. **Iteration cap.** `MAX_TURNS = 40`, a crash-guard (not a capability
   limit — the session budget is expected to bind first in practice),
   tested directly.
6. **Approved universe.** `{BTC, ETH, SOL, PAXG} × 4h`, each with its own
   export and its own K=200 baseline (0/200 SURVIVED, every asset), and
   structurally disjoint from the evaluation-only universe — enforced with
   `DataSourceRefusedError`, tested.
7. **Isolation**, proven three independent ways in the original Phase 0-3
   report (static live_scheduler/registry reference check, static
   research_agent import-boundary check, dynamic full-stub-run leaves the
   strategy registry unchanged, runtime write-path allowlist over every
   `os.replace`/`open`/`Path.write_text` call during a full stubbed
   session) — none of this session's changes touch those write paths;
   `test_eve_no_auto_wire.py` and `test_eve_write_path_isolation.py` both
   still pass unchanged.
8. **Positive control.** The harness can say `SURVIVED`, not just `DIED`
   (this session, a hard gate, passed on the first constructed pattern —
   no threshold was touched to force it).
9. **Silent-fallback trap closed** for both Eve's and Adam's scoring paths.

### Outstanding, flagged (none block the code itself; several are process items for whoever authorizes Phase 4)

- **No preflight API-key validation in Eve**, unlike Adam's own
  `validate_api_key`/`ApiKeyRejectedError` (added after Adam's own 401
  incident, commit `4189f6b`). Eve's first turn will still make **one**
  real API call before a bad key is caught — correctly released at $0 by
  this session's own fix, just not caught *before* spending that one
  round-trip. Not a financial risk (already closed); an optional
  parity/efficiency improvement, not implemented this session (report
  only).
- **`.env.example` lists none of `ANTHROPIC_API_KEY`, `EVE_ENABLED`, or
  `EVE_SESSION_BUDGET_USD`.** A human configuring Phase 4 from that file
  alone wouldn't discover any of the three exist (this is a pre-existing
  gap — `ANTHROPIC_API_KEY` is also absent for Adam's own use, not new to
  Eve). Cheap to fix; not done here since item 4 is report-only.
- **No GitHub Actions workflow references `EVE_ENABLED` anywhere** — good
  for safety (nothing can auto-trigger a paid run by accident) but means
  the very first real session must be started manually
  (`python -m nero_core.eve.pipeline`). Worth being a deliberate, explicit
  choice by whoever authorizes Phase 4, not a surprise discovered after.
- **An `ANTHROPIC_API_KEY` is present in the local environment** (its
  presence was confirmed directly; its value was never read or printed,
  per CLAUDE.md's own hard rule). Given Adam's own documented incident
  (commit `4189f6b`: the equivalent key in that session turned out to be
  the Claude Code harness's own session credential or a stale
  pre-rotation value, not a fresh key for direct Messages API use), a
  human should independently confirm this specific key is genuine and
  freshly rotated for direct API use before authorizing Phase 4 — presence
  alone does not imply correctness.
- **Cost ceiling, stated precisely for the record:** worst-case financial
  exposure for the entire first calendar month of Phase 4, regardless of
  how many sessions run or how badly `EVE_SESSION_BUDGET_USD` is
  misconfigured, is **$20**, hard-capped, enforced before every single
  call. This is the number a human approving Phase 4 is actually
  approving.
- **The pre-registered kill criterion** (N=5 real sessions, FDR-corrected
  OOS survival rate vs. the random baseline) is defined but has never been
  evaluated — 0 of 5 have run. Not a gap; a reminder of what "done" looks
  like once Phase 4 starts.
- **The 4h-vs-deployment-timeframe mismatch** (item 1e above): Eve's
  entire research universe is 4h; zero live strategies deploy at 4h.
  Flagged for a human decision, not resolved here.

## Full test suite

**Before this session's four items:** 2240 tests (per the prior session's
own closing report), 0 failures, 0 errors.

**After (this session):** **2257 tests, 0 failures, 0 errors** (`Ran 2257
tests in 756.565s` / `OK`) — net +17 this session. Confirmed by a full
`python -m unittest discover -s tests -p "test_*.py"` run after every item
landed; the only non-dot output during the run (mocked `OSError("disk
full")`, a corrupted-ledger-file recovery message, statsmodels
`FutureWarning`s, "unparseable pubDate" notices) are all pre-existing,
intentional test scenarios already documented in the prior session's own
closing report — none originate from this session's changes.

## Untracked-file accounting

Reconfirmed unchanged from session start (`git status` before any work
this session matches `git status` now, for every pre-existing entry):

| Path | Verdict |
|---|---|
| `check_news.py`, `check_news2.py`, `check_ns.py`, `check_pead*.py`, `check_results.py`, `daily_check.bat` | Pre-existing scratch scripts at repo root — leave alone |
| `data/backups/`, `data/funding_cache/`, `data/macro_cache/` | Pre-existing data directories — leave alone |
| `tests/fixtures/frozen_candles/backward_compat_baseline_after.json`, `.../baseline_before_run.log.err` | Pre-existing fixture/log artifacts (Adam's own Task 3 backward-compat regression fixture, commit `50d3b09`) — leave alone |

## Commit list (independently revertable)

1. `e25ac8b` — Add PAXG (PAXGUSDT) to BINANCE_SYMBOLS
2. `9dfe5ab` — Point Adam at the research export; add a shared, disjoint
   universe split (item 2)
3. `f96d1d8` — Backtest the two live BTC RANGE_MEAN_REVERSION variants
   (item 1)
4. `77a51e0` — Expand APPROVED_RESEARCH_UNIVERSE to the pre-registered
   4-asset family (item 3)

(Item 4 is report-only — this document itself, no code change.)

## Status

Not pushed, not merged. `EVE_ENABLED` still never set to a truthy value
anywhere in committed code. Zero real Anthropic API calls made from Eve —
every number in this report is either $0 real market-data fetches (item 1
and item 3's exports) or pure-code statistical computation against data
already on disk (every random baseline, every backtest). Phase 4 remains
unauthorized and unexecuted. Awaiting human review, including explicit
confirmation on: the 4h-vs-deployment-timeframe question (item 1e), the
`.env.example`/preflight-validation gaps (item 4), and whether BTC-ETH/12h
is worth a dedicated pairs-strategy harness in a future session (item 1d).
