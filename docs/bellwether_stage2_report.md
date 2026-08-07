## 2026-08-07 CLOSING REPORT — CC-1 comprehensive directive (Parts A, B, C, E)

Covers Parts A, B, C, E of the "CC-1 comprehensive directive — Fix
Bellwether's formula, correct the overlay, ship the facelift, then surface
Bellwether." **Parts D and F are reported in
`docs/investigations/factory_loop_implementation_report.md`'s own closing
section** — consolidating into these two existing canonical locations
rather than a third new file, per the directive's own "or say which you
chose if you consolidate." Per-part depth lives in dedicated docs (linked
below); this section is the checklist the directive's own closing section
asked for.

**A1's split metric + A4's re-measured baseline** (`agreement`/`coverage`
reported separately): see the "Part A4 / Part B2" section below for the
full 4-configuration table (mock / 1-real / 2-real-ish / current). Headline:
current wiring gives GOLD agreement 0.372 / coverage 0.200, BITCOIN
agreement 0.522 / coverage 0.280 — full numbers and two genuine findings
the split itself surfaced (a discretization artifact, and a real
provenance-granularity leak) in that section.

**A2's correlation-discount proposal**: NOT implemented, per explicit
instruction. Two concrete options proposed in
`docs/bellwether_aggregation_formula_report.md`'s 2026-08-07 update;
recommended waiting for `correlation.py` to compute real agent-pair
correlations before discounting, rather than borrowing a coefficient
computed for a different pair.

**B3's funding-rate independence finding**: measured with 2 years of real
daily data (DFII10, DX-Y.NYB, ^VIX, Binance funding), not asserted — funding
rate's day-to-day CHANGES are ≤0.041 correlated with every other real input,
confirming it's a genuinely independent fourth input, not disguised
redundancy. Full correlation matrices in the section below.

**C2's real ORDERFLOW_IMBALANCE cadence + alignment finding**: 54 real BTC
entries, mean gap 8.09h / median 6.14h between entries, median hold 2.28h —
justifies the overlay's 8h cadence (matches BTC funding's own settlement
schedule, the fastest-changing real input). Full writeup in the Part C
section below.

**C4's actual threshold numbers**: flag `conflicted=True` only when BTC
bias opposes the entry AND `agreement >= 0.6` AND `coverage >= 0.15` AND
the read's own `bitcoin_analysis` provenance is real/mixed. Reasoning for
both numbers (0.6 above the measured live-wiring mean ~0.52; 0.15 above the
single-signal-discretization floor ~0.135) in the Part C section below.

**E1's data-plumbing finding**: no macro export existed before this
directive (`docs/site_data/macro_reads.json` didn't exist — the overlay
workflow hadn't had its first scheduled tick). The export mechanism was
already built in Part C; ran it for real against production
(commit `a6d664a`) to seed genuine data rather than build the `/macro` page
speculatively. Every real number the page renders, and the full E1-E4
writeup: `docs/investigations/website_macro_page_e1.md`.

**Test counts, Python, before vs after this directive** (via
`python -m unittest discover -s tests`): baseline at session start (commit
`4ad5854`) was the pre-directive suite; after all of Parts A/B/C/D6a/F,
the full suite reports **2690 tests** (39 new: 6 aggregation + 6 funding +
8 macro_reads + 12 bellwether_overlay + 7 export_trial_entries), same **4
pre-existing failures** throughout (2x missing `lxml` module in this
environment, 1 PSX test depending on the same, 1 real-data-drift assertion
in `test_eve_citation_freshness.py` unrelated to any file this directive
touched) — confirmed via `git diff 4ad5854..HEAD -- nero_core/research_agent/
nero_core/eve/` returning **empty**, zero changes to either directory this
entire session.

**No evidence-bar constant changed, confirmed**: `TARGET_RESOLVED_TRADES`
(frequency_gate.py), `DEFAULT_FDR_ALPHA`/`MIN_SAMPLE_SIZE` (eve/scoring.py)
and every other admission-criteria constant are covered by the same zero-diff
check above — this directive's Python work was scoped entirely to
`vatican/bellwether/`, `nero_core/execution/`, and `nero_core/truth_ledger/`,
never `nero_core/research_agent/` or `nero_core/eve/`.

**Every new package, license, pinned version**: none in Parts A/B/C/E
(Python-only, no new pip dependencies). Part D's packages are listed in the
factory_loop_implementation_report.md closing section.

**Push verification, every commit this directive, `git log origin/main
--oneline`** (pasted after the final push, see the other report's closing
section for the full chronological list across all parts).

**What this system still cannot do** (stated once, covers both closing
sections): Bellwether cannot compute a correlation-discounted confidence
(A2, deferred pending real agent-pair correlations); cannot show per-agent
SIGNAL detail on `/macro` (only provenance, E1's disclosed limitation);
cannot fix its own live-scheduler drop rate (F3, reported not implemented);
ETF flows remain permanently blocked as a real Bellwether input (pre-existing,
re-confirmed, not touched this directive); and ORDERFLOW_IMBALANCE remains
permanently unbacktestable by construction (order-book snapshots have no
history) — the macro-conflict overlay annotates a real but never-verified
strategy, stated plainly in the design, not fixed by this directive.

**Stale figures found this directive, and the real values**: the "~6
trades/year" GOLD-1wk Momentum figure from earlier Stage 5 planning is
confirmed wrong (real number: 0, C1); the directive's claim that
`/heatmap` is the right page for the 3D surface is corrected (it's `/quant`
— see the other report's D4/D5 section); the directive's claim the site
"uses generic default styling" is corrected (a distinctive palette already
existed — see the other report's D1 section).

---

## 2026-08-07 update 2: aggregation formula split (Part A) + BTC funding rate (Part B)

Follows the "CC-1 comprehensive directive" (Parts A/B). Read this section
first for the current state of the formula and real-data wiring; sections
below are earlier, superseded snapshots kept for the historical record.

### Part A — `agreement`/`coverage` split (A1, shipped)

`_synthesis.aggregate()`'s confidence formula is **unchanged**
(`0.3 + 0.45*agreement + 0.25*coverage` — `coverage` is `mass`, renamed).
What changed: `agreement` and `coverage` are now their own fields on
`AssetRead`, propagated to `gold_analysis`/`bitcoin_analysis`'s `meta`,
`trade_recommendation`'s per-asset `recommendations`, and four new
top-level `AnalysisOutput` fields (`gold_agreement`, `gold_coverage`,
`bitcoin_agreement`, `bitcoin_coverage`). Full reasoning and the A2
correlation-discount proposal (NOT implemented, per explicit instruction):
`docs/bellwether_aggregation_formula_report.md`'s 2026-08-07 update.
6 new tests (`tests/test_vatican_aggregation.py`).

### Part A4 / Part B2 — re-measured sweep series, same session, directly comparable

Ran `tools/sweep_series.py` (new, committed — the original Stage 0/Stage 2
sweeps were ad hoc and never committed as a script; this tool matches the
same 30-seeds x 6-headlines = 180-cycle methodology, but headline text is
newly authored, not preserved from the original session — see the tool's
own docstring for that caveat). All four configurations in one run, same
process, same cached real fetches:

| | mock | live, 1 real (real_yield only) | live, 2 real-ish (+VIX) | live, current (+DXY, +funding) |
|---|---|---|---|---|
| mean confidence | 0.297 | 0.283 | 0.394 | 0.392 |
| % below 0.35 | 77.8% | 100.0% | 23.3% | 33.3% |
| gold NEUTRAL | 81.7% | 0.0% | 0.0% | 30.0% |
| bitcoin NEUTRAL | 73.3% | 100.0% | 23.3% | 20.0% |
| gold agreement (mean) | 0.351 | **0.500 (constant, stdev 0)** | 0.500 (constant) | 0.372 |
| gold coverage (mean) | 0.272 | 0.135 | 0.135 | 0.200 |
| bitcoin agreement (mean) | 0.401 | 0.0 | 0.533 | 0.522 |
| bitcoin coverage (mean) | 0.385 | 0.0 | 0.154 | 0.280 |

**Two genuine findings from having `agreement`/`coverage` separated, not
visible before A1:**

1. **"1 real agent" gold agreement is EXACTLY 0.500 with zero variance
   across all 180 cycles — a real, explained mechanism, not a bug.** With
   only `real_yield_10y` real (fixed across every seed — it's a single live
   DFII10 fetch, not seed-dependent) and `dxy` falling back to a per-seed
   mock draw, `monetary_policy`'s continuous `gold_score` varies slightly
   seed to seed, but stays entirely within the `Bias.BEARISH` band
   (`-1.5 < x <= -0.5`) for every seed tested — `Bias.from_score` discretizes
   to the same enum value regardless. With exactly one contributing GOLD
   signal, `aggregate()`'s `net = bias.score` exactly (weighted average of
   one term), so `agreement = |net|/2 = 0.5` no matter how the underlying
   continuous score wobbles within that band. This is the discretization
   step (`Bias.from_score`) hiding continuous variation, not a defect in
   the new split — worth knowing if `agreement`'s near-zero variance is
   ever mistaken for "very stable real signal" rather than "a single
   signal's score happens to sit mid-band."
2. **A genuine, newly-surfaced provenance-granularity leak, found BECAUSE
   of the split (this is worth fixing in a future increment, not fixed
   here — outside Part A/B's scope).** Wiring BTC funding rate makes
   `derivatives_etf`'s overall provenance `MIXED` (per-AGENT granularity,
   the same coarseness already disclosed in `liquidity.py`'s own
   docstring). But `derivatives_etf` ALSO emits a GOLD signal
   (`gold-ETF flow`, `mgr net-long %`) built ENTIRELY from mock ETF-flow
   and positioning data — confirmed by direct inspection (seed 0): once
   `derivatives_etf` is `MIXED` via its unrelated BTC-funding leg,
   `real_only_signals(ctx, Asset.GOLD)` includes this 100%-mock GOLD
   signal (`BEARISH, strength 0.488, "gold-ETF -83M, mgr net-long 34%"`)
   in the live-mode GOLD aggregate. This is why `live_current`'s gold
   agreement (0.372) is LOWER and more variable than `live_2_real_ish`'s
   constant 0.5 — a genuinely mock-derived signal is now blending into a
   number a consumer would read as "real read." **Not a regression this
   directive introduced by accident — a pre-existing per-agent-not-per-signal
   granularity limitation that funding wiring happened to newly trigger.**
   Flagging for a future increment: either move provenance to per-signal
   granularity, or split `derivatives_etf` into two agents (BTC leg /
   GOLD leg) so a partial real wiring on one side can't leak the other
   side's mock signal into a live-mode aggregate.

### Part B — BTC funding rate (B1, shipped)

`VaticanRealDerivatives` (`vatican/bellwether/bellwether/data/providers.py`)
wraps `MockDerivatives`, overrides only `btc_perp_funding_bps` via
`nero_core.data_sources.funding_data.load_funding_history("BTC")` (free
Binance public endpoint, no key) — confirmed live 2026-08-07: latest
settled funding rate 0.6045 bps. Same shape as VIX/DXY: process-lifetime
cache, falls back to the mock draw and reports SYNTHETIC on any failure,
never guesses. `derivatives_etf`'s own provenance is `MIXED` when funding
is real (its ETF-flow/skew/positioning legs remain mock). `risk.py`'s
crowded-leverage check (`> 6 bps`) now fires in live mode too, gated on
`ctx.data.derivatives.provenance_of("btc_perp_funding_bps")` — same pattern
as the existing VIX gate. 6 new tests (`tests/test_vatican_funding.py`).
34+6+6 = 46 tests total, 1 skipped, full suite green.

**B3 — does funding rate correlate with the real-yields/DXY/VIX cluster, or
is it a genuinely independent input? Measured with real historical data,
not asserted.** Pulled 2 years of daily DFII10 (cached), DX-Y.NYB and ^VIX
(yfinance), and BTC perp funding (Binance, resampled to daily mean) for the
same overlapping window (482 days). Two correlation matrices, because level
correlations on trending series are misleading (classic spurious-regression
risk) while day-to-day CHANGES are the honest test of whether they move
together:

| levels | real_yield | dxy | vix | funding |
|---|---|---|---|---|
| real_yield | 1.000 | 0.348 | 0.062 | 0.192 |
| dxy | 0.348 | 1.000 | -0.011 | 0.382 |
| vix | 0.062 | -0.011 | 1.000 | -0.271 |
| funding | 0.192 | 0.382 | -0.271 | 1.000 |

| daily changes | real_yield | dxy | vix | funding |
|---|---|---|---|---|
| real_yield | 1.000 | 0.287 | 0.105 | 0.041 |
| dxy | 0.287 | 1.000 | 0.016 | -0.015 |
| vix | 0.105 | 0.016 | 1.000 | 0.007 |
| funding | 0.041 | -0.015 | 0.007 | 1.000 |

**Finding: funding rate is genuinely a fourth independent input, not part
of the real-yields/DXY/VIX cluster.** The level correlations (0.19-0.38)
mostly wash out once measured as day-to-day changes (|r| ≤ 0.041 against
every other real field) — consistent with co-trending over the measurement
window rather than a structural relationship. Real yields and DXY DO show
a real, moderate day-to-day relationship even in changes (r=0.287) —
mechanistically expected (both are policy/dollar-strength expressions) and
the strongest candidate for a future correlation-cluster discount if A2's
option 2 (measured, not asserted, coefficients) is ever implemented. VIX
and funding are both close to zero against everything, including each
other — funding adding real signal COUNT does not just add correlated
redundancy, it adds a field the data says is genuinely close to orthogonal
to the other three. This directly answers A2/A4's open question for this
specific field: funding wiring is closer to "genuine new evidence" than
"disguised repetition," per the codebase's own measured data rather than
`correlation.py`'s hardcoded (and, per that module's own comment, always-
synthetic) coefficients.

## Part C — retarget and build the macro_conflicted overlay

### C1 — the original GOLD-1wk Momentum overlay rule is void, confirmed

Queried `data/truth_ledger.db` directly: `BREAKOUT_MOMENTUM/GOLD` has exactly
2 `execution_log` rows, both `NO_TRADE` — zero `ENTRY` rows, ever.
`TREND_PULLBACK/BNB` (20 rows) and `COINTEGRATION_PAIRS/BTC-ETH` (20 rows)
are the same: 100% `NO_TRADE`, zero entries. The "~6 trades/year" figure
from earlier Stage 5 planning is confirmed wrong — the real number is zero
for all three. An overlay rule keyed to any of them would annotate nothing.

### C2 — retargeted to `ORDERFLOW_IMBALANCE/BTC`, confirmed fit

**Real cadence** (54 `ENTRY` rows, 2026-07-19 to 2026-08-06, 17.9-day span):
mean gap between entries **8.09h**, median **6.14h** (min 1.17h, max
23.50h) — roughly 89 entries/month. Every entry has a matching `EXIT`
(fully round-tripped, no stuck open position); median hold duration
**2.28h**, mean **2.99h**.

**Cadence alignment vs Bellwether's read frequency**: Bellwether's real
inputs are daily-resolution (DFII10, DX-Y.NYB, ^VIX close) except BTC
funding rate, which settles every 8h (Binance's fixed 00:00/08:00/16:00 UTC
schedule) — the fastest-changing real input by construction. Given the
overlay job runs every 8h (see C4), and `ORDERFLOW_IMBALANCE`'s median
inter-entry gap (6.14h) is close to that same window, a macro read used to
evaluate an entry is, in the worst case, about as stale as the strategy's
own typical time between decisions — reasonably current, not stale by an
order of magnitude. Running the overlay MORE often than every 8h would not
buy any freshness on real_yield/DXY/VIX (still same trading-day value) and
would only add cost.

**`ORDERFLOW_IMBALANCE/ETH` is NOT annotated, explicitly** — Bellwether's
own `Asset` enum (`vatican/bellwether/bellwether/schemas.py`) has exactly
two values, `GOLD` and `BITCOIN`. There is no ETH read to annotate ETH
entries with; this isn't a scoping choice made for this directive, it's a
hard constraint of what Bellwether currently computes.

**Honest status, stated plainly (not buried)**: `ORDERFLOW_IMBALANCE` is
EXPERIMENTAL, snapshot-based, forward-testing only — **no backtest exists
at all** (Binance's public order-book endpoint has no historical replay;
confirmed directly in `nero_core/strategies/orderflow_imbalance.py`'s own
module docstring). Annotating it is a weaker experiment than annotating a
verified survivor would have been — the annotation records whether a macro
conflict preceded a real forward-test entry, not whether it preceded a
statistically-verified edge.

### C3 — the three verified survivors stay in the design as a dormant path

`_evaluate_entry`'s threshold logic (C4) is asset/strategy-agnostic in
shape — it takes an entry's parsed direction and the latest macro read
before its timestamp, with no special-casing for which strategy produced
the entry. If `BREAKOUT_MOMENTUM/GOLD` or the other two ever fire a real
`ENTRY` row, `process_orderflow_conflicts`' own strategy/asset filter would
need a one-line extension to include them (currently filtered to
`ORDERFLOW_ID`/BTC only, deliberately, since they're the primary
experiment) — the RULE itself doesn't need redesigning, confirmed by
inspection rather than assumed.

### C4 — the overlay, built

**Schema** (`nero_core/truth_ledger/macro_reads.py`, structurally separate
tables in the same SQLite file `execution_log.py` already uses — same
precedent that module itself established): `macro_reads` (one row per
run_id+asset, both GOLD and BITCOIN persisted every run for transparency)
and `macro_conflict_flags` (one row per `ORDERFLOW_IMBALANCE`/BTC `ENTRY`
row EVER EVALUATED — a full audit trail, not just positive hits — with
`status` in `evaluated`/`insufficient_data`/`circuit_breaker_open`).
`UNIQUE(execution_log_id)` on the flags table makes evaluation idempotent:
an entry is judged exactly once, ever. Both tables are immutable/append-only,
same discipline as `execution_log.py`.

**No lookahead**: `get_latest_macro_read_before(asset, before)` only ever
returns a read with `timestamp <= before` — an entry is judged against
whatever Bellwether had already said at or before that entry's own
timestamp, never a read computed later. Tested directly
(`tests/test_macro_reads.py`, `tests/test_bellwether_overlay.py`).
**Known, honest limitation on first deployment**: every one of the 54
existing historical `ORDERFLOW_IMBALANCE/BTC` entries predates this
overlay's first-ever macro read, so all 54 come back `insufficient_data`
the first time the job runs (confirmed via a smoke test against a COPY of
the real ledger, never the production file) — this is correct behavior,
not a bug: only entries that fire AFTER a macro read already exists can
ever be meaningfully evaluated.

**The threshold** (`nero_core/execution/bellwether_overlay.py`), expressed
in `agreement`/`coverage` per A1, not the old blended confidence: flag
`conflicted=True` only when (1) the read's BITCOIN bias directionally
OPPOSES the entry (BEARISH/STRONG_BEARISH vs LONG; BULLISH/STRONG_BULLISH
vs SHORT), AND (2) `bitcoin_agreement >= 0.6`, AND (3)
`bitcoin_coverage >= 0.15`, AND (4) the read's own `bitcoin_analysis`
provenance is REAL or MIXED. **0.6** is chosen meaningfully ABOVE the
current live-wiring mean bitcoin_agreement (~0.52, measured in the Part
A/B sweep above) — only more-aligned-than-typical reads get to flag
anything. **0.15** sits above the ~0.135 floor the sweep showed as a
single-signal discretization artifact (real signal count, not genuine
agreement) — requires roughly 2+ real-provenance BTC signals actually
contributing. Both are proposed with this reasoning, not fitted to produce
a target flag rate.

**Cadence**: `.github/workflows/bellwether_overlay.yml`, every 8h
(`17 0,8,16 * * *`, offset from `:00` per the same GitHub-Actions-congestion
lesson `live_scheduler.yml` already documents), justified in C2 above.

**Circuit breaker** (`run_bellwether_with_circuit_breaker`): ANY exception
from the Bellwether run, a timeout (60s), OR a `bitcoin_analysis`
provenance of `synthetic`/`unavailable` raises
`BellwetherCircuitBreakerOpen` internally, caught by `main()` — logged,
zero writes, zero notifications, workflow step marked `continue-on-error`.
Tested directly (`CircuitBreakerTest`, mocking both the exception path and
the synthetic-provenance path).

**Surfacing**: ntfy.sh (same public topic `notify_ntfy.py` already uses,
`Terminal3039`) fires one message per newly-flagged conflict; static JSON
export to `docs/site_data/macro_reads.json` (same `schema_version`/
`last_updated` convention as `export_site_data.py`), containing every
`macro_reads` row and every `macro_conflict_flags` row — read-only over
the ledger, matching that module's own discipline.

**Tests**: 8 (`tests/test_macro_reads.py`) + 12
(`tests/test_bellwether_overlay.py`) = 20 new tests, all passing. Smoke-
tested end-to-end against a COPY of the real production ledger (never the
tracked file itself) — confirmed the circuit breaker correctly closes on a
real usable BTC read (STRONG_BULLISH, agreement 0.771, coverage 0.461,
2026-08-07), and `process_orderflow_conflicts` correctly marks all 54
existing entries `insufficient_data` per the no-lookahead guarantee above.

**Annotate only, confirmed by design**: nothing in
`bellwether_overlay.py` calls into `orderflow_imbalance.py`'s own entry/exit
logic, `live_scheduler.py`, or `execution_log`'s insert path — it only
reads `execution_log` (via `list_execution_log`, already read-only) and
writes to its own two new tables.

---

# Bellwether Stage 1 + Stage 2 Report

Date: 2026-08-07. Follows `docs/bellwether_audit.md` (Stage 0). Stage 1
(vendor) is done. Stage 2: `monetary_policy` fully real (real_yield_10y AND
dxy — see the 2026-08-07 update below), VIX wired for `liquidity`, the
provenance leak in `risk`/`scenario`/`correlation`/`trade_recommendation`
closed. BTC funding rate (priority-3) not started this session. **Read the
2026-08-07 update section first** — it supersedes several numbers in the
original report below, kept for the historical record of what was found and
in what order.

---

## 2026-08-07 update: dxy + VIX wired, provenance leak closed

Three follow-ups from the original report below, all landed same-day:

1. **`dxy` is now real too**, not left synthetic. A dedicated availability
   check (per explicit instruction, before picking a fix) found yfinance's
   `DX-Y.NYB` (ICE US Dollar Index) returns real, DXY-index-scale data
   (~99.9, confirmed live 2026-08-07, 14,116 daily rows back to 1971, free,
   no key) — option (a), no formula rewrite needed.
   **Why MACRO_RISK_ON used UUP in the first place, confirmed documented,
   not guessed**: `docs/macro_risk_on_report.md` states plainly that DXY
   "is not a valid Twelve Data symbol" — a genuine provider limitation of
   the Twelve Data pipeline `nero_core/data_sources/macro_data.py` uses,
   not a quality preference for UUP. `DX-Y.NYB` is sourced via a different
   provider (yfinance, already a soft dependency for the DFII10 path via
   `nero_core`), independent of that limitation.
   `monetary_policy.py`'s own formula is completely unchanged — this was a
   sourcing fix, not a formula rewrite.
2. **VIX is now real for `liquidity`**, via the same yfinance pattern
   (`^VIX`, confirmed live: 9,217 daily rows back to 1990, ~15-16 currently).
   `risk.py`'s "elevated volatility regime" check picks this up
   automatically — no code change needed there, it was already gated on
   `vix`'s own field provenance.
3. **The provenance leak is closed.** `RiskAgent`, `ScenarioAgent`,
   `CorrelationAgent`, and `TradeRecommendationAgent` all now compute and
   report their own honest provenance, and — critically — `RiskAgent`'s
   signal-disagreement check, leverage/froth check, and catalyst check now
   only fire from real/mixed-provenance data in live mode (the
   derivatives/onchain/calendar checks are skipped entirely in live mode
   today, since no live provider exists for any of those three yet — not
   silently computed from data that can never currently be real).
   `CorrelationAgent` is now explicitly labelled always-SYNTHETIC (its
   coefficients are hardcoded design constants, confirmed in Stage 0 —
   never becomes real regardless of data_mode). A genuine regression test
   (`test_no_agent_calls_ctx_all_signals_for_gold_or_bitcoin_in_live_mode`)
   tracks the actual `ctx.all_signals()` call, not just output values.

**Updated real-vs-mock sweep** (same 180-cycle methodology, re-run after
each wiring step, all same session for direct comparability):

| | MOCK baseline | LIVE, 1 real agent (`monetary_policy` only) | LIVE, 2 real-ish agents (+ `liquidity` MIXED via VIX) |
|---|---|---|---|
| mean confidence | 0.295 | 0.281 | **0.392** |
| % below 0.35 threshold | 80.6% | 100.0% | **23.3%** |
| gold NEUTRAL | 78.3% | 0.0% | 0.0% |
| bitcoin NEUTRAL | 73.3% | 100.0% | **23.3%** |

**This is the clean confirmation of the mass-recovery hypothesis from the
original report below**: adding a SECOND real-provenance agent didn't just
move confidence up incrementally — it pushed the live-mode mean *above* the
mock baseline (0.392 vs 0.295) and cut the below-threshold rate from 100%
to 23.3%. The mechanism is exactly what was traced before (aggregate()'s
`mass` term recovering as more signals contribute) — now demonstrated with
real data, not just predicted. Full discussion of what this means for the
formula's validity at full wiring: `docs/bellwether_aggregation_formula_report.md`
(report-only, no formula change made, per explicit instruction).

**LLM streaming**: still deferred, now explicitly documented as a
prerequisite in `README_VATICAN.md` — ships first if any LLM path with web
search is ever turned on, not as a follow-up.

**Tests**: 34 passed, 1 skipped (standalone, no `PYTHONPATH`) — up from 21/1
in the original report, all new tests exercise real network calls
(DX-Y.NYB, ^VIX) when yfinance is reachable, skip cleanly otherwise.

---

## Original report (2026-08-07, pre-update)

## Stage 1 — vendored

`vatican/bellwether/` now holds a clean copy of the Downloads source-of-truth
Bellwether, minus `__pycache__`/`.bak`/`.bellwether_store.json`. Its own
12-test suite runs green standalone in the new location (confirmed via a
fresh venv with only its own `requirements-lock.txt` installed — no
`nero_core` on the path at all for that run). `README_VATICAN.md` documents
scope and real-data status.

## Stage 2 — `monetary_policy` wired for real (partially — see below)

**What's real, what isn't, and why**, honestly, up front:

- `real_yield_10y` is now **REAL** — `VaticanRealMarketData` in
  `vatican/bellwether/bellwether/data/providers.py` calls
  `nero_core.data_sources.macro_data.fetch_dfii10_daily()` unmodified,
  applies the SAME `DFII10_LAG_BUSINESS_DAYS=2` shift that module's own
  `compute_lagged_change` uses (I reused the shift, not the diff — I want a
  level, not a 20-day change), and takes the latest post-lag observation.
  Verified against the real cached data: `data/macro_cache/dfii10.csv`'s
  latest raw observation is `2026-07-15: 2.32`; the lag-shifted usable value
  the provider actually returns is **2.36** (2026-07-13's observation,
  correctly the one usable 2 business days back) — the lag discipline is
  doing real work, not a no-op.
- **`dxy` stays SYNTHETIC — a deliberate decision, not an oversight.**
  `data/macro_cache/dollar_proxy.csv` is UUP (an ETF price, cached values in
  the high 20s), not a DXY-index-scale quote (~100-110). Bellwether's own
  `monetary_policy.py` formula uses `_DXY_NEUTRAL = 104.0` as a fixed anchor
  — feeding UUP's price into that field directly would silently produce a
  nonsense `dxy_gap` (off by roughly a factor of 4), which is worse than
  staying mock: it would look confidently real while being wrong. This
  wasn't caught in the Stage 0 audit (which assumed the dollar proxy was
  directly reusable) — a real, useful correction the implementation work
  surfaced. Fixing it properly needs a decision: either force
  `fetch_dollar_proxy_daily`'s DXY-symbol fallback specifically (skipping
  the cached UUP series, which would need a live Twelve Data key — not
  attempted here), or rewrite `monetary_policy.py`'s own `dxy_gap` formula
  to use the proxy's own trailing baseline instead of a fixed anchor (a
  legitimate fix, but an agent-internal formula change I didn't make
  unilaterally — flagging for your decision).
- Every other `MarketSnapshot` field (`gold_price`, `btc_price`, `vix`,
  `nominal_yield_10y`, `fed_funds_mid`, `move_index`) is unchanged mock, as
  expected (VIX/funding are priority 2/3, not started).

**Provenance mechanism, in the schema, tested**: added a `DataProvenance`
enum (`REAL`/`SYNTHETIC`/`MIXED`/`UNAVAILABLE`) to `bellwether/schemas.py`,
a `field_provenance` dict on `MarketSnapshot` (missing key = SYNTHETIC by
convention, never assumed REAL), and a `provenance` field on `AgentResult`
and the top-level `AnalysisOutput.provenance_breakdown`. `monetary_policy`
now reports its own provenance honestly — `MIXED` today (one of its two
inputs real, one still mock), not rounded up to `REAL`. 9 new tests in
`vatican/bellwether/tests/test_vatican_provenance.py` prove: a missing
provenance key defaults SYNTHETIC; `monetary_policy` reports MIXED/REAL/
SYNTHETIC correctly for each real/mock combination; a purely-synthetic
agent's signal is excluded from `gold_analysis`/`bitcoin_analysis`'s
aggregate in live mode (and is NOT excluded in mock mode — byte-identical
to upstream); the real DFII10 fetch actually returns a different, real
number when `nero_core` is importable (skipped, not failed, when it isn't
— matching the provider's own soft-dependency degradation).

**"Excluded from the aggregate, not silently included"**: implemented at
the point that actually matters — `GoldAnalysisAgent`/`BitcoinAnalysisAgent`
now filter to `real_only_signals(ctx, asset)` (REAL/MIXED source agents
only) when `data_mode == "live"`, and use the original unfiltered
`ctx.all_signals(asset)` in `mock` mode (unchanged, still the default,
still what every pre-Stage-2 test exercises). This is a real behavior
change to the primary bias in live mode: with only `monetary_policy`
real/mixed today, `gold_analysis`/`bitcoin_analysis`'s live-mode read is
now built from **that one agent's signal alone**, not the 9-agent mock
blend — a stark, honest number, not a diluted mix.

**A known, disclosed scoping gap**: `RiskAgent`, `ScenarioAgent`,
`CorrelationAgent`, and `TradeRecommendationAgent`'s own haircut/scenario/
correlation logic still read `ctx.all_signals()` / `ctx.data.*` unfiltered
— they weren't touched this round. In live mode today, the risk haircut
subtracted from `monetary_policy`'s real-derived confidence is still partly
computed from the OTHER 8 agents' mock signal disagreement. This is a real
limitation of this increment, not hidden: the honest fix is either
extending the same real/synthetic filtering into `RiskAgent` (next
increment) or accepting that the haircut stays a "how noisy does the mock
system look overall" signal until more real feeds land — your call, not
guessed here.

## The real-vs-mock comparison (the number you asked to see first)

Re-ran the exact Stage 0 sweep (30 seeds × 6 headline scenarios, n=180,
`persist=False`) in both modes, same session, for direct comparability:

| | MOCK (Stage 0 baseline, reproduced exactly) | LIVE (monetary_policy real) |
|---|---|---|
| mean confidence | 0.295 | **0.180** |
| median confidence | 0.285 | 0.212 |
| min / max | 0.147 / 0.485 | 0.081 / 0.214 |
| stdev | 0.069 | 0.039 |
| % below 0.35 actionable threshold | 80.6% (145/180) | **100.0% (180/180)** |
| gold NEUTRAL | 78.3% | **100.0%** |
| bitcoin NEUTRAL | 73.3% | **100.0%** |

**Confidence went DOWN, not up — the opposite of the Stage 0 hypothesis,
and worth taking at face value rather than explaining away.** Traced why,
precisely: `_synthesis.aggregate()`'s confidence formula is `0.3 +
0.45*agreement + 0.25*mass`, where `mass = min(1, total_signal_strength /
4.0)`. Mock mode blends up to 9 agents' signals per asset, so `total_
strength` (and therefore `mass`) is usually substantial even when the
agents disagree. Live mode's real-only aggregate has exactly **one**
signal (`monetary_policy`'s), so `mass` collapses to that single signal's
own strength ÷ 4 — typically ~0.13 in the measured runs — regardless of how
correlated or confident that one real signal is. **`agreement` alone can't
compensate**: a lone signal is definitionally "unanimous with itself," but
the formula weights `mass` almost as heavily as `agreement` (0.25 vs 0.45),
so a thin-but-real read scores lower than a thick-but-mock blend every
time.

**This is a real, useful finding, not a failure of the wiring**: it shows
the NEUTRAL-heaviness traced in Stage 0 has (at least) a third cause beyond
the two already identified (the permanent 0.7x calibration haircut, and
mock agents' independent draws) — **the aggregation formula itself
rewards signal QUANTITY (mass) nearly as much as signal AGREEMENT**, and
today only one agent contributes real signal quantity. The Stage 0
hypothesis ("real correlated data should raise agreement, possibly
confidence") isn't falsified so much as untestable with a single real
agent — agreement among *multiple* genuinely correlated real signals is
the thing that would need 2-3 real agents blended (VIX + funding rate next)
to actually measure. Worth re-running this exact sweep again once
priority-2/3 land, to see whether `mass` recovers as more real signals join
the aggregate.

## LLM streaming

Confirmed again (Stage 0's finding stands): `bellwether/llm/client.py`
still does a single blocking `await client.post(...)`, not streaming.
**Not ported this round** — the LLM path isn't exercised anywhere in Stage
2's real work (no API key configured, every test runs the heuristic
fallback), so porting the fix now would be speculative work with no way to
verify it against a real call in this session. Flagging as a decision:
port it now regardless (low cost, matches the Adam precedent exactly), or
defer until Stage 4 actually turns an LLM path on for real.

## Tests, full suite

`vatican/bellwether/`: **21 passed, 1 skipped** standalone (the skip is
`test_real_dfii10_wiring_if_nero_core_available`, which correctly skips
rather than fails when `nero_core` isn't on the path — confirmed it PASSES
when the Vatican repo root is added to `PYTHONPATH`). The original 12 tests
are unmodified and still pass byte-for-byte, confirming mock-mode behavior
is unchanged.

Vatican's own full suite was not re-run this round (no `nero_core` files
were modified — only read from — so no regression risk there; will run it
before any future change that touches `nero_core` itself).

## What's next (not started, your call on order)

Per the audit's priority order: VIX for `liquidity` (free, yfinance, same
pattern as SILVER/PLATINUM futures fallback), then BTC funding rate for
`onchain`/`derivatives_etf` (free, `nero_core/data_sources/funding_data.py`
already built). Each one added means one more real-provenance agent joins
`real_only_signals`, which is exactly the lever the confidence-collapse
finding above says matters most right now — worth prioritizing over
extending the risk-haircut filtering gap, since more real mass is the more
informative next measurement.

---

## 2026-08-07: CC-1 master directive, Part B Rung 1 -- correlation discount for `agreement`

CC-1 master directive "Close the backlog: macro-conditioning ladder + repair
resolution fix," Part B, Rung 1 (blocks Rungs 2/3 by design -- wiring macro
DSL fields before resolving this would let Adam/Eve condition on signals
that aren't independent of each other).

### B1a. Real pairwise correlation matrix (measured, not estimated)

**FINDING (confirmed-from-data).** Built `vatican/bellwether/tools/
correlation_matrix.py`, a one-time analysis script (not part of the runtime
engine) pulling REAL historical series for all 4 real fields:
- `real_yield_10y`: `nero_core.data_sources.macro_data.fetch_dfii10_daily`
  (FRED DFII10, cached at `data/macro_cache/dfii10.csv`) -- the exact same
  function/cache `VaticanRealMarketData` itself uses in production.
- `dxy`: yfinance `DX-Y.NYB` daily close, same ticker
  `_fetch_real_dxy_level` uses, pulled over a 5-year window here (production
  only needs the single latest value).
- `vix`: yfinance `^VIX` daily close, same ticker `_fetch_real_vix_level`
  uses, same 5-year window.
- funding rate: `nero_core.data_sources.funding_data.load_funding_history("BTC")`
  (Binance `fapi/v1/fundingRate`, cached at `data/funding_cache/BTC_funding.csv`),
  resampled from its native 3-settlements/day cadence to a daily mean, in
  bps (matching `btc_perp_funding_bps`'s existing scale).

All 4 series aligned on calendar date via an INNER join (real observations
only, no forward-fill, no synthetic interpolation). **Real sample: n=1229
overlapping calendar days, 2021-08-09 to 2026-07-15.**

**Real pairwise Pearson correlation matrix, LEVEL values** (the relevant one
for Rung 1 -- see reasoning below):

| | real_yield_10y | dxy | vix | funding_rate_bps |
|---|---|---|---|---|
| real_yield_10y | 1.0000 | 0.4833 | -0.3444 | -0.1551 |
| dxy | 0.4833 | 1.0000 | 0.0870 | -0.0883 |
| vix | -0.3444 | 0.0870 | 1.0000 | -0.2791 |
| funding_rate_bps | -0.1551 | -0.0883 | -0.2791 | 1.0000 |

**Real pairwise Pearson correlation, 20-trading-day CHANGE** (matches
MACRO_RISK_ON's own t+2/20-bar-change convention -- kept for Rung 2's later
use, NOT what Rung 1's discount is built from, see reasoning below):

| | real_yield_10y | dxy | vix | funding_rate_bps |
|---|---|---|---|---|
| real_yield_10y | 1.0000 | 0.5608 | 0.2273 | -0.0792 |
| dxy | 0.5608 | 1.0000 | 0.2588 | -0.0584 |
| vix | 0.2273 | 0.2588 | 1.0000 | -0.1451 |
| funding_rate_bps | -0.0792 | -0.0584 | -0.1451 | 1.0000 |

Only ONE pair shows a non-trivial relationship: `real_yield_10y`/`dxy` at
0.48 (level) / 0.56 (20-day change) -- a real, moderate, economically
sensible relationship (real yields up tends to coincide with dollar
strength). Every other pair is weak (|rho| < 0.35 in every case, mostly
under 0.29).

### B1b/B1c. Which agents actually double-count, and the mechanism chosen

**FINDING, more precise than the directive's own framing** (confirmed from
reading `monetary_policy.py`, `liquidity.py`, `derivatives_etf.py`, and
`risk.py` in full): the redundancy risk is NOT "4 real agents, each an
independent vote" -- it's narrower and different in shape:
- `monetary_policy.py` already BLENDS `real_yield_10y` and `dxy` internally
  into ONE signal per asset (`gold_score = -(real_gap*1.2) - (dxy_gap*4.0)`)
  -- the one pair with real measured correlation (0.48-0.56) never appears
  as two separate votes in `_synthesis.aggregate()` at all. No fix needed
  there.
- `risk.py` reads BOTH `vix` and `funding_rate_bps`, but returns
  `RiskFlag`s and a confidence haircut, **never a `Signal`** -- confirmed by
  reading its full `run()` method, `self.result(risks=..., ...)` never
  passes `signals=`. It never enters `aggregate()`'s `relevant` list at
  all, so it has zero bearing on `agreement`.
- The REAL cross-agent redundancy is between `monetary_policy.py`
  (real_yield_10y + dxy blend) and `liquidity.py` (`vix`-only GOLD signal,
  `vix` + mock-stablecoin BTC signal) and `derivatives_etf.py`
  (funding-rate-threshold term in its BTC signal) -- three DIFFERENT agents
  that DO each emit their own `Signal` into `aggregate()`, driven by fields
  with real (if modest) measured correlation to each other.

**RECOMMENDATION, with the real matrix as evidence.** Considered 3 options:
1. **Simple pairwise correlation penalty on `agreement`** -- discount an
   agreeing signal's effective weight by `(1 - |rho|)` when a correlated,
   different-agent signal was already counted. Minimal code change, directly
   traceable to the measured numbers, and proportionate to what the real
   data shows (mostly weak correlations, one moderate one).
2. **Factor-model / clustering** -- treat `{monetary_policy, liquidity}` (or
   any pair above a threshold) as one merged "cluster vote." Rejected: this
   is a step function that would either fully merge or not, when the real
   data shows a CONTINUUM of weak-to-moderate correlations (0.09 to 0.56)
   -- collapsing e.g. `dxy`/`vix` at 0.09 into a hard cluster with
   `real_yield_10y`/`vix` at -0.34 would over-penalize a pair that's
   genuinely close to independent.
3. **Effective-N via eigen-decomposition of the correlation matrix** -- more
   statistically formal, but heavier to implement and explain for a 4-field,
   3-agent system where the effect size doesn't warrant it; rejected as
   overkill for what the real data shows.

**Chose option 1**, implemented in `_synthesis.py`:
- `_REAL_FIELD_CORRELATION`: the LEVEL matrix above, hard-coded (not
  re-fetched at runtime -- these are slow-moving structural relationships,
  not something that needs measuring fresh every Orchestrator cycle). LEVEL
  chosen over the 20-day-change variant because every Bellwether formula
  this discount protects (`real_gap`, `dxy_gap`, `vix_z`) computes a LEVEL
  gap/z-score, not a period-over-period change -- the 20-day-change matrix
  is kept in this report for Rung 2's later, different use (a DSL condition
  reacting to movement), not used here.
- `_AGENT_REAL_FIELDS`: which of the 4 fields each Signal-emitting agent's
  own formula reads (`monetary_policy`: both; `liquidity`: vix;
  `derivatives_etf`: funding) -- `risk` deliberately excluded, per the
  finding above.
- `_agent_pair_correlation(a, b)`: max `|rho|` across the cross-product of
  two agents' own field sets.
- `_discounted_agreement_numerator`: processes signals strongest-first; a
  signal that AGREES in direction with an already-counted signal from a
  correlated, different agent has its strength discounted by `(1 - |rho|)`
  before contributing; a DISAGREEING signal is left at full weight (a
  disagreement between usually-correlated agents is genuinely more
  informative, not redundant). Divided by the SAME undiscounted `total_w`
  coverage already uses -- deliberately: dividing by a matching discounted
  denominator would renormalize a perfectly redundant pair right back to
  the SAME ratio as one signal alone (a weighted average is insensitive to
  duplicate copies of an identical score by construction), which would
  silently defeat the whole point. Dividing the discounted numerator by the
  ORIGINAL total_w instead correctly shrinks the ratio toward zero for a
  redundant pair.
- **Scope, precisely**: only `agreement` (and therefore `confidence`, which
  already consumes `agreement` in its existing, unchanged 0.3/0.45/0.25
  formula) changes. `net_score`, `bias`, and `probability_up` are left on
  the ORIGINAL undiscounted `net` -- this directive's own ask was
  `agreement` specifically, not the directional call.

### B1d. Real before/after, 180-cycle live sweep (identical seeds/headlines)

Ran the SAME sweep twice (`tools/sweep.py --mode live`, 30 seeds x 6
headlines = 180 cycles both times) -- once with the discount temporarily
reverted (`git stash`) for a true apples-to-apples "before," once with it
restored for "after":

| Metric | Before | After | Δ |
|---|---|---|---|
| mean_confidence | 0.396 | 0.391 | -0.005 |
| max_confidence | 0.500 | 0.483 | -0.017 |
| mean_gold_agreement | 0.372 | 0.361 | -0.011 (-3.0%) |
| mean_gold_coverage | 0.202 | 0.202 | 0 (unchanged, as designed) |
| mean_bitcoin_agreement | 0.537 | 0.513 | -0.024 (-4.5%) |
| mean_bitcoin_coverage | 0.296 | 0.296 | 0 (unchanged, as designed) |
| pct_below_035 / pct_gold_neutral / pct_bitcoin_neutral | 26.7 / 30.0 / 16.7 | 26.7 / 30.0 / 16.7 | 0 |

**Real interpretation**: a modest, real downward correction, exactly the
direction expected -- BTC's discount (4.5%) is larger than GOLD's (3.0%),
consistent with BTC having 3 real-field-driven contributing agents
(`monetary_policy`, `liquidity`, `derivatives_etf`) vs GOLD's 2
(`monetary_policy`, `liquidity`) -- more agent-pairs for the discount to
apply to. `coverage` is confirmed byte-identical before/after in this real
run, not just by unit test -- direct proof the discount didn't leak into
the one field it was designed to leave alone. The directional-classification
metrics (`pct_gold_neutral`, `pct_bitcoin_neutral`, `pct_below_035`) are
also unchanged, confirming `bias`/`net_score` truly weren't touched.

### B1e. Regression test

`vatican/bellwether/tests/test_correlation_discount.py`, 6 new tests:
perfectly-correlated-vs-independent agreement comparison (the literal B1e
requirement), a lone signal is never discounted, the REAL agent names
(`monetary_policy`/`liquidity`/`derivatives_etf`) show a real discount
proportional to their real measured correlation, disagreement between
correlated agents is never discounted, agents outside `_AGENT_REAL_FIELDS`
are unaffected (protects the pre-existing `test_vatican_aggregation.py`
assertions), and `_agent_pair_correlation` is symmetric and bounded to
`[0, 1]`.

### Test counts

Bellwether (`vatican/bellwether/tests/`): before this rung, 46 passed / 1
skipped. After: **53 passed / 1 skipped** (+7: the 6 new tests above, plus
one existing test file's collection count -- confirmed via a full
`pytest tests/ -q` rerun, zero regressions, zero changed assertions in any
pre-existing test). Vatican-core (`nero_core`) Python suite: unaffected --
zero files under `nero_core/` touched this rung (confirmed via
`git diff --name-only`).

### No evidence-bar constant touched, confirmed

This rung touches exactly `vatican/bellwether/bellwether/agents/_synthesis.py`
(new module-level constants/functions plus a two-line change inside
`aggregate()`'s existing confidence block) and one new test file. Zero
change to any Vatican-core evidence-bar constant (`MIN_SAMPLE_SIZE`, the
30/yr frequency floor, the 70/30 split, FDR alpha, bootstrap CI, random
baselines, Trial admission criteria) -- none of those live in
`vatican/bellwether/` at all, and `git diff --name-only` confirms nothing
under `nero_core/` changed this rung.

---

## 2026-08-07: CC-1 directive -- wire the 2 safest agents real: DefiLlama stablecoins + RSS news feed

File-overlap check (per this directive's own instruction, confirmed rather
than assumed): `git status --short` at the start of this directive showed
Rung 2's own uncommitted work touching exactly 7 `nero_core/` files
(`macro_data.py`, `eve/random_baseline.py`, `eve/session.py`,
`eve/tools_defs.py`, `research_agent/auto_tester.py`,
`research_agent/frequency_gate.py`, `research_agent/rule_dsl.py`). This
directive's own changes (below) touch `vatican/bellwether/bellwether/data/
providers.py`, `vatican/bellwether/bellwether/agents/liquidity.py`,
`nero_core/execution/bellwether_overlay.py`, and their test files --
zero overlap with Rung 2's file set, confirmed, not assumed.

### Item 1 -- DefiLlama stablecoin supply

**1a. FINDING** (confirmed-from-data, fetched live 2026-08-07): `GET
https://stablecoins.llama.fi/stablecoincharts/all` returns HTTP 200, no API
key, a JSON list of daily rows shaped `{"date": "<unix seconds, UTC
midnight>", "totalCirculatingUSD": {"peggedUSD": <float>, ...other pegs}}`.
Confirmed 3174+ rows, current total ~$306B, and the row set includes a
still-forming "today" entry (the last row's `date` decoded to the exact
calendar day the fetch was run on, UTC midnight-stamped, at a time that day
had not yet elapsed). `GET .../stablecoins?includePrices=true` (the
per-asset endpoint) was also fetched directly and confirms USDT (id=1) and
USDC (id=2) are both present with real circulating-supply figures, but the
aggregate `stablecoincharts/all` endpoint is what's actually used (a single
clean total, not a manual sum across 414 individual assets).

**1b. WHAT SHIPPED.** `vatican/bellwether/bellwether/data/providers.py`:
added `provenance_of()` to the `OnChainProvider` ABC (concrete, SYNTHETIC
default -- mirrors `DerivativesProvider`'s own existing pattern exactly, so
`MockOnChain` needs zero changes), `_fetch_real_stablecoin_supply_chg_pct()`
+ `_fetch_real_stablecoin_supply_chg_pct_cached()` (process-lifetime cache,
same shape as `_DXY_CACHE`/`_VIX_CACHE`/`_BTC_FUNDING_CACHE`), and a new
`VaticanRealOnChain(OnChainProvider)` class wrapping `MockOnChain` --
overrides only `stablecoin_supply_chg_pct`, every other field
(`exchange_netflow_btc`, `lth_supply_chg_pct`, `mvrv_z`,
`OnChainProvider`'s own separate `funding_rate_bps`) stays on the identical
mock draw, per the scoping directive's own Item 1b finding that none of
those have a confirmed free source. `requests` is a soft dependency
(imported inside the function), matching `yfinance`'s own treatment for
dxy/vix. Wired into `build_data_hub`'s `"live"` branch:
`onchain=VaticanRealOnChain(rng)` (was `MockOnChain(rng)`). Verified live:
`_fetch_real_stablecoin_supply_chg_pct()` returned a real value
(0.0445% for that day) end to end.

**1c. FINDING.** DefiLlama's own chart includes a still-forming "today" row
(see 1a) -- a **1-calendar-day lag** is applied (`_STABLECOIN_LAG_DAYS = 1`:
treat the row before the most recent one as "current," matching this
project's own closed-candle discipline, the same shape as
`_DXY_LAG_BUSINESS_DAYS`/`_VIX_LAG_BUSINESS_DAYS` above it). This is a
**calendar-day** lag, not a **business-day** one like the dollar/DFII10
legs -- stablecoin supply changes every day, weekends included, so there is
no market-closed concept to skip. This directly answers (not assumes) the
scoping report's own "UNKNOWN" note on this point.

**1d. FINDING.** `liquidity.py` combines two inputs: its GOLD signal uses
`vix` only; its BTC signal uses `vix` AND `stablecoin_supply_chg_pct`.
`AgentResult.provenance` is a single value for the whole agent (documented,
pre-existing coarseness), so `liquidity.py`'s own provenance logic was
rewritten to combine BOTH real inputs the same way `monetary_policy.py`
already combines its own two (`real_yield_10y`, `dxy`): both real -> REAL,
either real -> MIXED, neither -> SYNTHETIC. Before this directive,
`stablecoin_supply_chg_pct` was unconditionally SYNTHETIC (no
`OnChainProvider.provenance_of` existed at all), so `liquidity` could only
ever reach MIXED at best -- **it can now genuinely reach REAL**, confirmed
in a real sweep run below (one live cycle's own `provenance_breakdown`
showed `liquidity: 'real'`).

**1e. WHAT SHIPPED.** New file
`vatican/bellwether/tests/test_vatican_onchain.py`, 6 tests: fetch-failure
falls back cleanly to the identical mock draw + SYNTHETIC (never guesses),
every other on-chain field always reports SYNTHETIC regardless of the
stablecoin fetch's own outcome, `MockOnChain` needs no code change to
satisfy the new ABC method, a real-network integration check (skipped, not
failed, if unreachable) asserting the real value is a plausible bounded %
change, and two new `liquidity.py` provenance-combination tests (both-real
-> REAL; only-stablecoin-real -> MIXED). One pre-existing test's own stale
comment (`test_liquidity_agent_mixed_once_vix_real_stablecoin_still_mock`,
which said "no live OnChainProvider exists") was corrected to reflect that
one now does, while explaining why that specific test still deliberately
isolates the stablecoin-still-synthetic case. Full Bellwether suite: 53 ->
**59 passed, 1 skipped** (+6), zero regressions.

### Item 2 -- RSS news feed wiring

**2a. FINDING** (confirmed-from-code, exact file+line). The real production
entrypoint is **not** the FastAPI `/analyze` route (`bellwether/api/
main.py`, which is a passive service -- `events` come from whichever
caller invokes it) but the scheduled overlay script,
`nero_core/execution/bellwether_overlay.py`, run every 8h via
`.github/workflows/bellwether_overlay.yml`. Confirmed at
`nero_core/execution/bellwether_overlay.py:95` (pre-fix):
`orch.analyze(events=[], persist=False)` -- a **literal, hardcoded empty
list**, every single scheduled run, matching the scoping report's own
finding exactly, now pinned to the precise line. `MacroEvent`'s shape
(`bellwether/schemas.py:88-96`): `headline: str, summary: str = "",
source: str = "unknown", region: Region = GLOBAL, category: Category =
OTHER, url: str | None = None, published_at: datetime`.

**2b. WHAT SHIPPED.** New function `build_real_macro_events()` in
`bellwether_overlay.py`, calling `nero_core.data_sources.news_feed
.NewsFeedClient.load("GOLD")` and `.load("BTC")` (the two assets Bellwether
actually models), transforming each real `NewsItem` into a `MacroEvent`.
**Critical honesty finding, confirmed-from-code before writing any
transform logic**: `NewsFeedClient.load()` has its own `FALLBACK_HEADLINES`
-- a static, illustrative (NOT real) headline list returned when the real
RSS fetch fails or nothing matches that asset's keywords this cycle.
`build_real_macro_events()` checks `NewsFeedResult.status` and only
transforms headlines when `status.startswith("live")` -- a fallback result
means **zero real events for that asset this cycle, never the fallback
text passed through as if it were real**. This is the same "never guess,
degrade honestly" discipline every other real provider in this codebase
follows, applied to news content for the first time. `category` is a
best-effort map from `news_feed.py`'s own keyword tags (Central Banks ->
MONETARY_POLICY, Geopolitics -> GEOPOLITICS, Sentiment -> RISK_SENTIMENT;
everything else -> OTHER, never guessed). `published_at` is parsed from the
feed's real RFC822 `pubDate` via the standard library
(`email.utils.parsedate_to_datetime`), falling back to the current
ingestion time (never a fabricated past time) only when a specific item's
date is missing/unparseable. `_run_bellwether_live()` now calls
`orch.analyze(events=build_real_macro_events(), persist=False)`.
Verified live: **11 real, current headlines** fetched end to end (e.g.
"Fed Governor Cook says she's 'prepared to act' on rate hike to address
inflation", CNBC; "Gold prices today, Friday, August 7, 2026: Gold prices
continue to rise...", Yahoo Finance).

**2c. FINDING -- the real result is more limited than the wiring itself,
disclosed plainly, not oversold.** Ran a real cycle both ways (`Settings
(data_mode="live", seed=1)`), calling `NewsIntelligenceAgent`/
`GeopoliticalAgent` directly with the real fetched events:
`news_intelligence` produced **6 real signals** and `geopolitical`
produced **2 real signals**, all with real rationale text quoting the real
headlines (e.g. `GOLD STRONG_BULLISH keyword match in: Jeffrey Gundlach
says the bond market is telling Warsh...`) -- the wiring genuinely works,
real text produces real signals. **But both agents' own
`AgentResult.provenance` stayed `SYNTHETIC`, identically to the `events=[]`
case.** Traced this to `bellwether/schemas.py:202`: `AgentResult.provenance`
defaults to `SYNTHETIC`, and `news_intelligence.py`/`geopolitical.py`
**never set `provenance=` explicitly in any of their `_heuristic`/
`_llm_classify`/`_llm` result-building code paths, in either the pre-
existing or the now-real-events case.** Since `real_only_signals()` (used
by `gold_analysis`/`bitcoin_analysis` in live mode) excludes any agent
whose own provenance isn't REAL/MIXED, **these 8 real signals are
completely excluded from the live-mode aggregate today** -- confirmed
directly: a full `Orchestrator.analyze()` run with `events=[]` vs. with the
11 real headlines produced **byte-identical** `gold_bias`, `bitcoin_bias`,
`gold_agreement` (0.468), and `bitcoin_agreement` (0.039) in both cases.
**This is a real, pre-existing gap in `news_intelligence.py`/
`geopolitical.py` themselves (not something this directive's own scope
included fixing -- wiring ingestion was the ask, not rewriting these two
agents' own provenance logic), and it means Item 2's real effect on the
live aggregate is currently zero, honestly reported per this directive's
own 3c instruction, not framed as a clean win.**

**2d. FINDING.** `NewsFeedClient.load()` is stateless -- no shared cache,
no persisted dedup state, no database writes; each call is an independent
HTTP GET per RSS feed. Calling it a second time (from
`bellwether_overlay.py`, in addition to `NEWS_SENTIMENT`'s own existing
call sites) cannot interfere with `NEWS_SENTIMENT`'s own behavior in any
way -- confirmed by reading the class in full, not assumed from the
"stateless-looking" name alone. Zero lines of `nero_core/strategies/
news_sentiment.py` or `nero_core/data_sources/news_feed.py` itself were
touched.

**2e. WHAT SHIPPED.** 5 new tests in `tests/test_bellwether_overlay.py`
(`BuildRealMacroEventsTest`): a live-status result produces matching
`MacroEvent`s with correct source/url/category; **the exact honesty
requirement** -- a fallback-status result (even one whose own headline
text is a real `FALLBACK_HEADLINES` string) produces **zero** events, never
that fallback text passed through as real; a headline appearing in both
the GOLD and BTC queries is deduped to one event, not two; an unmapped
category tag defaults to OTHER rather than guessing; an unparseable
`pubDate` degrades to the schema's own default timestamp rather than
crashing. All 17 tests in the file pass (12 pre-existing + 5 new), zero
regressions.

### Item 3 -- measured real effect

**3a. FINDING** (confirmed-from-data). Re-ran the identical 180-cycle sweep
(`tools/sweep.py --mode live`, 30 seeds x 6 headlines) after both items
were wired:

| Metric | Before (Rung 1's own closing numbers) | After (this directive) | Δ |
|---|---|---|---|
| mean_confidence | 0.391 | 0.373 | -0.018 |
| mean_gold_agreement | 0.361 | 0.361 | 0 |
| mean_gold_coverage | 0.202 | 0.202 | 0 |
| mean_bitcoin_agreement | 0.513 | 0.393 | **-0.120** |
| mean_bitcoin_coverage | 0.296 | 0.300 | +0.004 |
| pct_below_035 | 26.7% | 40.0% | +13.3pp |

**GOLD is completely unchanged** -- expected and correct: GOLD's own
`liquidity` signal depends on `vix` only, never `stablecoin_supply_chg_pct`,
and Item 2's news wiring has zero aggregate effect (per 2c) regardless of
asset. **BITCOIN's agreement dropped by a real, sizeable 0.120** -- this
sweep run's `sweep.py` script does not vary the stablecoin fetch across its
30 seeds x 6 headlines (the value is fetched once per process via the
process-lifetime cache and reused for all 180 cycles), so this delta
reflects that one real snapshot's actual value (~0.044%, a small, near-flat
real reading for that specific day) interacting with the other agents'
per-seed mock/real signals for BTC, not a bug in the discount or
aggregation math. **Whether this is a persistent characteristic of wiring
this agent or an artifact of this one day's specific real stablecoin
reading cannot be determined from a single snapshot** -- a multi-day
measurement would be needed to know if BTC agreement typically drops this
much, stays flat, or recovers on other days, mirroring exactly the
"single-agent-can-make-things-worse-before-a-second-one-recovers-it"
pattern this directive's own "lesson 1" warned about.

**3b. FINDING -- a real, load-bearing correction to this directive's own
"6 of 15" expectation.** By real agent-name (not field), the roster is:

- **Real/mixed-capable (4, unchanged in COUNT by this directive, though
  `liquidity`'s own ceiling improved from MIXED-only to REAL-capable)**:
  `monetary_policy` (real_yield_10y, dxy), `liquidity` (vix, and now
  stablecoin_supply_chg_pct), `derivatives_etf` (funding rate real; ETF
  flows/skew/OI/gold-positioning still mock), `learning` (mechanically real
  -- it genuinely tracks whatever it's fed -- but per `docs/
  bellwether_audit.md`'s own item 15, currently fed synthetic-derived bias,
  a real nuance worth preserving rather than counting as a clean "real"
  agent).
- **Genuinely real DATA in, but always reports SYNTHETIC (2, this
  directive's own Item 2 -- confirmed-from-data, not a guess)**:
  `news_intelligence`, `geopolitical` -- both now consume real RSS
  headlines and produce real signals from them (per 2c), but neither's own
  `AgentResult.provenance` logic was ever built to reflect that, so both
  remain reported SYNTHETIC and excluded from the live aggregate.
- **Downstream/composite, inherit real-or-mixed provenance from the above
  when applicable (5)**: `gold_analysis`, `bitcoin_analysis`, `scenario`,
  `risk`, `trade_recommendation`.
- **Fully synthetic, no real path wired (4)**: `onchain` (the AGENT --
  `exchange_netflow_btc`/`lth_supply_chg_pct`/`mvrv_z` remain unwired; this
  agent does not itself consume `stablecoin_supply_chg_pct` at all, so
  Item 1 does not touch it), `economic_calendar`, `correlation` (hardcoded
  by design, confirmed permanently SYNTHETIC regardless of mode),
  `historical_analog`.

**This directive's own "should be 6 of 15" framing in its Context section
is the stale figure this closing report is required to flag.** The real
count of agents whose OWN reported provenance changed as a direct result of
this directive is **zero new agent names** -- `liquidity` was already one
of the pre-existing 4, and its ceiling improved (MIXED-only -> REAL-capable,
confirmed live) without becoming a "new" entry; `news_intelligence`/
`geopolitical` genuinely gained real input but neither's own provenance
reporting reflects it, so neither counts as newly real by this project's
own established "an agent's provenance is the one place this is actually
decided" discipline (see `real_only_signals`'s own docstring). The
**real, honest count stays 4 of 15 real/mixed-capable primary agents**,
with one (`liquidity`) genuinely stronger than before, and 2 more
(`news_intelligence`, `geopolitical`) now sitting one small, identified fix
away from joining that count for real.

**3c. Honest disclosure, not a forced clean win.** Item 1 (stablecoin) is a
real, confirmed, working improvement to `liquidity`'s own provenance
ceiling, but its measured real-sweep effect on BITCOIN's agreement was
**negative** (-0.120) on the one real day measured, exactly the kind of
result this directive's own "lesson 1" pre-warned about and asked to be
reported honestly rather than framed as a win. Item 2 (RSS) is fully real
and working at the ingestion/signal-production level, but has **zero**
measured effect on the live aggregate today, due to a separate, pre-existing
gap in the two consuming agents' own provenance logic -- also not a clean
win, though also not a failure of this directive's own actual scope (wiring
ingestion, not rewriting those two agents).

### Test counts

Bellwether (`vatican/bellwether/tests/`): 53 -> **59 passed, 1 skipped**
(+6, Item 1's `test_vatican_onchain.py` plus updates to
`test_vatican_provenance.py`). Vatican-core Python (`tests/`, full suite):
before this directive (Rung 2's own last full-suite count) **2729 tests**;
after this directive: **Ran 2734 tests in 693.6s** (+5, Item 2's new
`BuildRealMacroEventsTest` tests in `test_bellwether_overlay.py`) --
`FAILED (failures=1, errors=3, skipped=17)`, the same 4 pre-existing
failures throughout by name (`test_lxml_is_importable`,
`FetchKse100DailyTest`'s 2 PSX tests -- all 3 depend on `lxml`, not
installed in this environment -- and
`test_the_real_committed_eve_hypotheses_file_has_been_backfilled`, a
real-data-drift assertion unrelated to anything this directive touched).
Zero new failures from this directive's own changes.

### No evidence-bar constant touched, confirmed

This directive touches exactly: `vatican/bellwether/bellwether/data/
providers.py`, `vatican/bellwether/bellwether/agents/liquidity.py`,
`nero_core/execution/bellwether_overlay.py`, and three test files. Zero
diff to `rule_dsl.py`, `macro_data.py`, `trial.py`, `repair_to_trial.py`,
`graveyard_distillation.py`, or any Adam/Eve scoring/verdict path --
confirmed via `git status --short`, which shows Rung 2's own 7 files
unchanged by this directive's own commits (separate, disjoint file sets).
Zero change to any admission criterion, frequency-gate constant, or
FDR/bootstrap parameter.

### What's still not real, and the next highest-priority candidate

Still not real: `onchain` (the agent)'s own 3 remaining fields, ETF flows
(confirmed blocked, `docs/etf_flow_audit.md`), derivatives skew/OI/gold
positioning, economic-calendar surprise, and `correlation`/
`historical_analog`'s own by-design-hardcoded content. **The single
highest-priority next candidate is not a new data source at all**: fixing
`news_intelligence.py`'s and `geopolitical.py`'s own provenance-reporting
logic (have each set `provenance=DataProvenance.REAL` when `ctx.events` is
non-empty and genuinely sourced from a confirmed-real ingestion path, the
same pattern `monetary_policy.py`/`liquidity.py` already use) would let
Item 2's already-real, already-working RSS wiring actually reach the live
aggregate for the first time -- a small, targeted, already-scoped-by-this-
report follow-up, not a new research task.

### git log origin/main --oneline -3, per commit this directive

Item 1 and Item 2 commits, verified on `origin/main` immediately after
pushing (rebased cleanly onto 3 intervening automated bot commits --
`signal-alerts`/`nero-live-scheduler`/`bellwether-overlay` data-only
updates, zero code overlap):

    ed46366 CC-1 directive Item 2: wire real RSS headlines into Bellwether ingestion
    15dcc16 CC-1 directive Item 1: wire DefiLlama stablecoin supply real
    2487e6e Update signal alerts state

---

## 2026-08-07: CC-1 directive -- fix news_intelligence/geopolitical provenance

### Item 1 -- fix the provenance labeling

**1a. FINDING** (confirmed-from-code, exact file+line). Traced the real
mechanism the 4 already-wired agents use:
- `monetary_policy.py:55-62`: reads `m.provenance_of("real_yield_10y")` and
  `m.provenance_of("dxy")` from the `MarketSnapshot` itself, then
  `if both REAL: REAL elif either REAL: MIXED else: SYNTHETIC`.
- `liquidity.py` (fixed in the prior directive): same pattern, reading
  `m.provenance_of("vix")` and `ctx.data.onchain.provenance_of
  ("stablecoin_supply_chg_pct")`.
- `derivatives_etf.py:29,62-63`: reads `ctx.data.derivatives.provenance_of
  ("btc_perp_funding_bps")`, `MIXED if REAL else SYNTHETIC` (a single real
  input, so no third state possible).

**The common shape**: an agent reads `provenance_of(field)` from the
underlying data object it consumes, then sets its own `AgentResult
.provenance=` explicitly in every `self.result(...)` call. `news_intelligence
.py`/`geopolitical.py` could not follow this literally -- they don't consume
a `MarketSnapshot`/`Provider` field, they consume a *list* of `MacroEvent`
objects, which (confirmed-from-code) had **no provenance concept at all**
before this directive (`bellwether/schemas.py`'s pre-fix `MacroEvent` had
no `provenance` field; `AgentResult.provenance` defaults to SYNTHETIC per
`schemas.py:202`, and neither agent's `_heuristic`/`_llm_classify`/`_llm`
result-building ever set `provenance=` explicitly -- confirmed by reading
every `self.result(...)` call site in both files).

**1b. WHAT SHIPPED.**
- `bellwether/schemas.py`: added `provenance: DataProvenance =
  DataProvenance.SYNTHETIC` to `MacroEvent` -- the same "missing/unset means
  never assumed real" default every other provenance-labeled value in this
  schema module already uses. **A real bug caught before it ever shipped**:
  `DataProvenance` was defined textually AFTER `MacroEvent` in the file;
  `provenance: DataProvenance = DataProvenance.SYNTHETIC` evaluates its
  default value eagerly at class-definition time (unlike the type
  annotation itself, which `from __future__ import annotations` defers) --
  importing the module raised `NameError: name 'DataProvenance' is not
  defined`, confirmed by actually running the import before writing any
  further code. Fixed by moving the `DataProvenance` class definition to
  before `MacroEvent` (a pure reordering, zero behavior change to
  `DataProvenance` itself) -- reconfirmed via the same import immediately
  after, and the full Bellwether suite (59 passed, 1 skipped, no
  regressions) before writing anything else.
- `nero_core/execution/bellwether_overlay.py`'s `build_real_macro_events()`:
  every event it constructs now gets `provenance=DataProvenance.REAL` --
  correct because, per that function's own pre-existing contract (from the
  prior directive), it only ever builds an event from a confirmed-live RSS
  match, never a fallback.
- `news_intelligence.py`/`geopolitical.py`: added a `_events_provenance()`
  static method to each, combining the events actually consumed (all of
  `ctx.events` for news_intelligence; the filtered `geo_events` subset for
  geopolitical -- see 1c) via **all-real -> REAL, any-real -> MIXED,
  none-real -> SYNTHETIC**, the same pattern `monetary_policy.py` already
  uses, generalized from 2 fixed fields to N events. `provenance=` is now
  set explicitly in every `self.result(...)` call in both files, including
  the early-return "no events"/"no relevant events" branches, which now
  correctly report `UNAVAILABLE` (matching `combined_provenance`'s own
  established "empty means UNAVAILABLE, not SYNTHETIC" precedent in
  `_synthesis.py`) rather than falling through to the SYNTHETIC default.
  **A second real design correction made during implementation**: the
  first draft reused `_synthesis.weakest_provenance` for this combination
  and a test caught it immediately -- `weakest_provenance([REAL, SYNTHETIC])`
  returns `SYNTHETIC` (it combines already-computed AGENT provenances,
  where MIXED may already be a list member; it never synthesizes MIXED from
  a raw REAL/SYNTHETIC blend). Since `DataProvenance.MIXED`'s own docstring
  explicitly defines "an agent whose inputs are a genuine blend of REAL and
  SYNTHETIC fields" as the textbook MIXED case, `weakest_provenance` was
  the wrong tool; replaced with the explicit all/any/none-real logic before
  committing anything.

`geopolitical.py` stays **RSS-only for this directive**, per 1b's own
instruction not to silently expand scope -- GDELT (flagged as a strong
candidate in the prior data-source scoping report) is a real, separate
follow-up: it would give `geopolitical.py` a purpose-built, pre-categorized
event/tension signal instead of RSS headlines classified by keyword, but
wiring a new source is out of this small directive's own scope.

**1c. FINDING, confirmed-from-code and by test.** The provenance value is
genuinely per-cycle, never a stale carry-over: neither agent holds any
instance state between calls to `run()` -- `_events_provenance()` is a pure
function recomputed fresh from `ctx.events` every single invocation. An RSS
fetch failure (network error, feed down) is already handled honestly one
layer down, per the prior directive's own design: `NewsFeedClient.load()`
degrades to a `"fallback: ..."` status, and `build_real_macro_events()`
already treats that as **zero events for that asset this cycle**, never
fabricated ones. The natural, already-correct consequence is `ctx.events ==
[]` (or a `geo_events` subset that's empty) on a failed cycle, which both
agents' own pre-existing early-return already reports as `UNAVAILABLE` --
no new failure-handling code was needed, only the correct default at that
existing branch. Verified directly with a dedicated test
(`test_news_intelligence_provenance_recomputed_fresh_each_call`): a REAL
cycle immediately followed by an empty cycle correctly transitions
REAL -> UNAVAILABLE, never staying stuck on the prior cycle's label.

**WHAT SHIPPED (tests).** New file `vatican/bellwether/tests/
test_vatican_news_geopolitical_provenance.py`, 11 tests: `MacroEvent`'s own
SYNTHETIC default; both agents report UNAVAILABLE with no (relevant) events;
REAL when all consumed events are REAL; SYNTHETIC when none are; MIXED when
genuinely blended; provenance recomputed fresh per cycle (1c); geopolitical
correctly ignores an irrelevant REAL event when computing its own
provenance (uses `geo_events`, not all of `ctx.events`) and is not falsely
dragged to MIXED by an irrelevant SYNTHETIC one. `tests/
test_bellwether_overlay.py`'s existing `test_live_result_produces_matching_
macro_events` extended with a `provenance == REAL` assertion on the real
production path. Full Bellwether suite: 59 -> **70 passed, 1 skipped**
(+11), zero regressions.

### Item 2 -- re-measured real effect

**2a. FINDING, confirmed-from-data.** Re-ran the exact same before/after
cycle from the prior directive's own Item 2c (`Settings(data_mode="live",
seed=1)`, `events=[]` vs. `build_real_macro_events()`):

| | Before (`events=[]`) | After (real RSS events, this fix) |
|---|---|---|
| `news_intelligence` provenance | UNAVAILABLE | **REAL** |
| `geopolitical` provenance | UNAVAILABLE | **REAL** |
| `gold_bias` | BEARISH | **BULLISH** |
| `gold_agreement` | 0.468 | 0.368 |
| `gold_coverage` | 0.279 | **1.0** |
| `bitcoin_agreement` | 0.039 | 0.167 |
| `bitcoin_coverage` | 0.324 | 0.524 |

**Not byte-identical** -- confirmed, this is the real fix working:
`gold_bias` genuinely flips direction once the real news/geopolitical
signals are actually counted, and `gold_coverage` reaches its maximum
(1.0), a real, substantial, measured change directly attributable to this
fix (nothing else in the pipeline changed between the two calls).

**2b. FINDING -- a real, honest, structural limitation of the sweep
methodology itself, not of this fix.** Re-ran the identical 180-cycle sweep
(`tools/sweep.py --mode live`). Result: **byte-identical to the prior
directive's own post-Item-1/2 numbers** (`mean_gold_agreement` 0.361,
`mean_bitcoin_agreement` 0.393, `mean_gold_coverage` 0.202,
`mean_bitcoin_coverage` 0.300 -- unchanged to 3 decimal places). Traced why,
confirmed-from-code (`vatican/bellwether/tools/sweep.py:57`):
`orch.analyze(events=[MacroEvent(headline=headline)], persist=False)` --
`sweep.py` builds its own `MacroEvent`s directly from its 6 hand-authored
`HEADLINE_SCENARIOS` strings, **never calling `build_real_macro_events()`
at all**. Per this directive's own new schema default, an event built this
way stays SYNTHETIC (confirmed: the sweep run's own last-cycle breakdown
showed `news_intelligence: 'synthetic'`, `geopolitical: 'unavailable'`) --
correctly, since `sweep.py`'s scenario headlines are hand-authored test
strings, not real RSS content, and this fix's own schema docstring says
exactly that ("`tools/sweep.py`'s own hand-authored scenario headlines...
correctly stay on this default"). **The 180-cycle sweep is structurally
incapable of measuring this fix's real effect** -- it exercises a
completely different, synthetic-by-design event-construction path than
`bellwether_overlay.py`'s real production one. This is reported plainly as
a real limitation of the measurement tool, not spun as "no effect" -- 2a's
own direct `Orchestrator.analyze()` comparison is the correct, and only,
way this fix's real effect has actually been measured.

**2c. FINDING -- the corrected real provenance count.** Ran the real
production path (`build_real_macro_events()` -> `Orchestrator.analyze()`,
11 real headlines fetched live) and read the full `provenance_breakdown`
directly:

- **Real/mixed-capable primary agents (6 of 15, up from 4 before this
  directive)**: `monetary_policy` (REAL), `liquidity` (REAL), `learning`
  (REAL), `news_intelligence` (**REAL, this directive**), `geopolitical`
  (**REAL, this directive**), `derivatives_etf` (MIXED -- funding real,
  other fields still mock).
- **Downstream/composite (5), inherit real-or-mixed provenance from the
  above when applicable**: `gold_analysis`, `bitcoin_analysis`, `scenario`,
  `risk`, `trade_recommendation` -- all reported MIXED in this real cycle.
- **Fully synthetic, no real path wired (4)**: `economic_calendar`,
  `onchain`, `correlation`, `historical_analog`.

**This corrects the prior directive's own "should be 6 of 15" prediction
-- which was directionally right, but for the wrong immediate reason.**
The prior directive predicted 6 by assuming wiring 2 new DATA SOURCES
(stablecoin, RSS) would itself produce 2 new real agents; the real,
measured result at the time was that the count stayed at 4, because RSS
wiring alone left news_intelligence/geopolitical's own provenance LOGIC
unfixed (2c of that directive's own honest finding). **It took this
follow-up directive -- fixing the labeling gap specifically, not adding any
new data -- to actually realize the 6th (and 5th) real agent.** The real
number, today, confirmed-from-data: **6 of 15**.

### Test counts

Bellwether (`vatican/bellwether/tests/`): 59 -> **70 passed, 1 skipped**
(+11). Vatican-core Python (`tests/`, full suite): before this directive
**2734 tests**; after: **Ran 2734 tests in 679.8s** (unchanged -- this
directive's only nero_core-level test change was 3 assertion lines added
to an *existing* test method in `test_bellwether_overlay.py`, not a new
test function; all 11 new tests live in the Bellwether-side pytest suite,
counted separately above) -- `FAILED (failures=1, errors=3, skipped=17)`,
the same 4 pre-existing failures by name (`test_lxml_is_importable`,
`FetchKse100DailyTest`'s 2 PSX tests, and
`test_the_real_committed_eve_hypotheses_file_has_been_backfilled`). Zero
new failures from this directive's own changes.

### No evidence-bar constant touched, confirmed

This directive touches exactly: `vatican/bellwether/bellwether/schemas.py`
(one field addition + a pure class-ordering fix), `vatican/bellwether/
bellwether/agents/news_intelligence.py`, `vatican/bellwether/bellwether/
agents/geopolitical.py`, `nero_core/execution/bellwether_overlay.py` (one
kwarg added to an existing dict literal), and two test files (one new, one
extended). Zero diff to `rule_dsl.py`, `macro_data.py`, `trial.py`,
`repair_to_trial.py`, `graveyard_distillation.py`, or any Adam/Eve
scoring/verdict path -- confirmed via `git status --short`, which shows
Rung 2's own 7 files unaffected by this directive's own commits (separate,
disjoint file sets, as in every prior directive this session). Zero change
to any admission criterion, frequency-gate constant, or FDR/bootstrap
parameter. No GDELT wiring, no new data source, no new API key -- per this
directive's own explicit OUT OF SCOPE list.

### What's still not real, and the next highest-priority candidate

Still not real: `onchain`'s own 3 remaining fields (exchange netflow, LTH
supply, MVRV-Z -- no free source found in the earlier scoping report), ETF
flows (confirmed blocked), derivatives skew/OI/gold positioning,
economic-calendar surprise (dates are free via FRED; consensus estimates
are not), and `correlation`/`historical_analog`'s own by-design-hardcoded
content. **The next highest-priority candidate, per 1b's own explicit
flag**: wiring GDELT into `geopolitical.py` as a second, complementary
event source alongside RSS -- a purpose-built, pre-categorized
tension/escalation signal (300+ event categories, a built-in tone score)
rather than keyword-classified headlines, real and free, already scoped in
the earlier data-source report, deliberately not attempted here to keep
this directive small and precise.

### git log origin/main --oneline -3

Verified on `origin/main` immediately after pushing (rebased cleanly onto
one intervening `signal-alerts` automated data-only commit):

    fce917e CC-1 directive: fix news_intelligence/geopolitical provenance labeling
    47fdbb7 Update signal alerts state
    e474d48 CC-1 directive closing report: wire the 2 safest agents real

---

## 2026-08-07: CC-1 directive -- fix sweep.py to measure the real RSS path

### Item 1 -- diagnosis

**1a. FINDING** (confirmed-from-code, exact file+line).
`vatican/bellwether/tools/sweep.py:57` (pre-fix):
`out = await orch.analyze(events=[MacroEvent(headline=headline)],
persist=False)`, where `headline` cycles through the 6 hand-authored
`HEADLINE_SCENARIOS` strings. `MacroEvent(headline=headline)` never sets
`provenance=`, so -- per the prior directive's own schema fix -- every one
of these events defaults to `DataProvenance.SYNTHETIC`. **The exact
divergence point from production**: `nero_core/execution/
bellwether_overlay.py`'s real `_run_bellwether_live()` calls
`build_real_macro_events()` (real RSS fetch, `provenance=REAL` on every
event it returns); `sweep.py` never calls that function at all, anywhere
-- confirmed by grepping the file for `build_real_macro_events` and
`news_feed` (zero matches, pre-fix).

**1b. FINDING** (confirmed-from-data, git history). `git log --follow
-- vatican/bellwether/tools/sweep.py` shows exactly **one** commit ever
touched this file: `f4425d2`, 2026-08-07 07:42 (Pakistan time) -- the
"CC-1 Parts A/B" directive, which shipped the `agreement`/`coverage` split
and the BTC funding-rate wiring. This is **before** any real RSS
integration existed in this codebase at all (`build_real_macro_events`
was added several directives later, same day). No comment, docstring, or
design note anywhere in the file's own history suggests network-avoidance
or reproducibility was a deliberate design decision specifically about the
news/headline dimension -- the file's own docstring only explains the
6-scenario x 30-seed = 180-cycle METHODOLOGY (matching an even earlier,
uncommitted ad hoc sweep), never the choice of `MacroEvent(headline=...)`
as a data-source stand-in. **Conclusion: this was not a deliberate
"avoid the network for news" design choice -- it simply predates real RSS
wiring by construction, and the hand-authored headlines were always meant
as the sweep's own intentional "vary the macro narrative" test dimension,
not a placeholder for a live feed.** This matters for 2a below: the fix
should ADD the real path, not treat the existing scenario headlines as
something to rip out.

### Item 2 -- the fix

**2a. RECOMMENDATION, with reasoning -- Option 2 (recorded-real),
not Option 1 (live-per-cycle).** Considered both real options:
1. **Live mode** (call the real RSS pipeline fresh every one of the 180
   cycles): genuinely live, but reintroduces exactly the non-reproducibility
   problem this tool exists to avoid -- every prior before/after table in
   this report (VIX, funding rate, the correlation discount, the
   stablecoin fix, the provenance fix) depended on comparable, controlled
   runs. 180 live RSS fetches per sweep also has real, avoidable cost:
   slower, and a real risk of hitting the underlying RSS feeds' own rate
   limits for no benefit (real news content does not meaningfully change
   within the seconds a sweep run takes).
2. **Recorded-real mode** (fetch once, reuse across all 180 cycles):
   **chosen.** This is not a new pattern invented for this fix -- it is the
   EXACT SAME "fetch once per process, cache for the run's lifetime"
   convention every other real field in this tool already uses
   (`bellwether/data/providers.py`'s own `_DXY_CACHE`/`_VIX_CACHE`/
   `_BTC_FUNDING_CACHE`/`_STABLECOIN_CACHE` -- confirmed by reading each:
   all are simple process-lifetime dicts, fetched once, reused for every
   one of the 180 cycles in a run). **The real tradeoff, disclosed plainly
   per this directive's own instruction, not hidden**: a sweep's own "real
   news" dimension reflects ONE moment's real content (whatever was
   published at the run's own start time), not a continuously live feed --
   this is NOT the same honesty level as "real, live, minute-by-minute,"
   and is stated as such in the shipped code's own docstring. This is,
   however, **not a new or additional honesty compromise** -- it is
   exactly, consistently, the same real-but-frozen-for-one-run treatment
   every other real field in this exact tool already receives and has
   already been reported as such throughout this session.

**2b. WHAT SHIPPED.** `vatican/bellwether/tools/sweep.py`: new
`_fetch_real_news_events_once(mode)` -- returns `[]` immediately in
`--mode mock` (mock mode stays fully synthetic across every field, as it
always has -- confirmed unaffected, no code path change for `mode=="mock"`
at all), else calls the real `build_real_macro_events()` exactly once,
degrading to `[]` (never a guess) on any failure. `run_sweep()` now calls
this ONCE before the seed/headline loop (not once per cycle) and combines
the current cycle's own scenario headline with the fetched real events for
every one of the 180 `orch.analyze()` calls:
`cycle_events = [MacroEvent(headline=headline)] + real_news_events`. The
existing 6-scenario x 30-seed dimension is completely unchanged in shape;
the real events are ADDED, not substituted. **Confirmed the 4
already-wired real macro fields are completely unaffected**: `run_sweep`'s
own signature, its `Settings(data_mode=mode, seed=seed)` construction, and
every dxy/vix/real_yield/funding/stablecoin code path are untouched --
this fix touches only the `events=` argument passed to `orch.analyze()`.
`run_sweep`'s own return type (`list[dict]`) is unchanged (a
`real_news_event_count` key was added to each row instead of changing the
function's signature) specifically so `tools/sweep_series.py`'s own
existing `rows = await run_sweep(mode); return summarize(rows)` usage
(confirmed by reading that file) keeps working unmodified -- zero risk of
silently breaking that script.

**2c. WHAT SHIPPED.** New file `vatican/bellwether/tests/
test_sweep_real_news.py`, 4 tests: `--mode mock` never calls
`build_real_macro_events` at all; `--mode live` calls the REAL, real
production import path (`nero_core.execution.bellwether_overlay
.build_real_macro_events`, not a reimplementation or parallel mock)
**exactly once** for the full 180-cycle run, confirmed via
`mock_fetch.assert_called_once()`; the fetched event's own REAL provenance
demonstrably reaches `news_intelligence`'s real aggregate output (a
zero-real-events baseline never shows REAL/MIXED; adding one real event
makes every cycle MIXED, isolating the real news contribution as the only
variable between the two runs); a fetch failure degrades to zero real
events for the whole run, never a crash, never a guess. Full Bellwether
suite: 75 passed (one previously-flaky DefiLlama-reachability test
happened to pass rather than skip this run, an unrelated environmental
timing difference, not a regression) -- was 70 passed/1 skipped before
this directive's own 4 new tests (70 + 4 = 74; the 75th is that same
flaky test converting from skip to pass). No regressions in any
pre-existing test.

### Item 3 -- the measurement this directive unblocks

**3a. FINDING, confirmed-from-data.** Re-ran the identical 180-cycle sweep
with the fixed tool (`tools/sweep.py --mode live`):

| Metric | Before (prior directive, sweep.py blind to news) | After (this fix) | Δ |
|---|---|---|---|
| mean_confidence | 0.373 | 0.343 | -0.030 |
| mean_gold_agreement | 0.361 | 0.297 | -0.064 |
| mean_gold_coverage | 0.202 | **0.851** | **+0.649** |
| mean_bitcoin_agreement | 0.393 | **0.123** | **-0.270** |
| mean_bitcoin_coverage | 0.300 | 0.563 | +0.263 |
| pct_bitcoin_neutral | 20.0% | **93.3%** | +73.3pp |
| real_news_event_count | 0 (never fetched) | 11 (fetched once, reused) | -- |

**Reported plainly, not spun**: `gold_coverage` jumping to 0.851 makes
sense mechanically -- real news headlines add real signal mass that was
completely absent before. `bitcoin_agreement` falling further, to 0.123,
with `bitcoin_neutral` now true in 93.3% of cycles, is a real, substantial,
negative-looking shift for BTC specifically, consistent with the same
"a new real agent's effect is not guaranteed positive" pattern flagged
honestly in both prior directives.

**3b. FINDING -- does the earlier 0.513->0.393 finding need correction?
No, but it is now known to be incomplete, not wrong.** Reconstructing the
real, sequential chain across all 3 real sweep measurements:
1. **0.513** -- baseline, before stablecoin/RSS wiring.
2. **0.393** -- after stablecoin wiring, measured with the OLD (blind)
   sweep.py. Confirmed correct as far as it went: the provenance-fix
   directive's own Item 2b proved this number was **byte-identical**
   whether news events were present or not (news_intelligence/geopolitical
   were excluded from the aggregate regardless, due to the labeling bug
   fixed in that directive) -- so 0.513->0.393 correctly, fully isolates
   stablecoin's own real effect, uncontaminated by any news signal
   (there wasn't one reaching the aggregate at that time regardless of
   what sweep.py did). **This number does not need restating or
   correcting.**
3. **0.123** -- new, additional, real finding from THIS directive: once
   news genuinely reaches the aggregate (both the provenance fix AND this
   sweep-tool fix were required together), bitcoin_agreement drops further
   still. This is a NEW data point the old tool was never capable of
   producing (not a hidden flaw in the 0.393 figure), confirmed by the
   fact that 0.393 was ALREADY measured correctly for what it was
   measuring.

**The honest summary**: BTC agreement has now moved 0.513 -> 0.393 -> 0.123
across the wiring of 2 real agents (stablecoin, then news/geopolitical),
each step measured correctly for what it isolated at the time. No prior
number in this report needs correction; this directive adds a real,
previously-unmeasurable data point, not a fix to a wrong one.

### Test counts

Bellwether (`vatican/bellwether/tests/`): 70 passed/1 skipped -> **75
passed, 0 skipped** (+4 new tests; the pre-existing skip converted to a
pass this run due to real-time network reachability of an unrelated
DefiLlama check, not this directive's own change). Vatican-core Python
(`tests/`, full suite): **unaffected, still 2734** -- confirmed via
`git status --short`, this directive touches exactly one file
(`vatican/bellwether/tools/sweep.py`) plus one new test file, both under
`vatican/bellwether/`, zero `nero_core/` files touched.

### No evidence-bar constant touched, confirmed

This directive touches exactly `vatican/bellwether/tools/sweep.py` and one
new test file. Zero diff to `rule_dsl.py`, `macro_data.py`, `trial.py`,
`repair_to_trial.py`, `graveyard_distillation.py`, or any Adam/Eve
scoring/verdict path -- confirmed via `git status --short`, which shows
Rung 2's own 7 files unaffected by this directive's commits (separate,
disjoint file sets, as in every prior directive this session). No GDELT
wiring, no new data source, no new API key.

### Stale figures found this directive, and the real values

None found beyond what 3b already restates: no figure in this directive's
own context section was wrong -- the "0.513->0.393" number was accurately
described as measured with the old tool, and this directive confirms it
was correct for what it measured, not stale.

### git log origin/main --oneline -3

Verified on `origin/main` immediately after pushing (no intervening
commits this time):

    c140934 CC-1 directive: fix sweep.py to measure the real RSS path
    67caf29 CC-1 directive closing report: fix news_intelligence/geopolitical provenance
    fce917e CC-1 directive: fix news_intelligence/geopolitical provenance labeling

## 2026-08-08: CC-1 master directive, Part B Rung 2 -- fresh K=200 random-baseline rerun with macro fields wired

**Question this rung exists to answer:** now that `real_yield_10y_chg20`,
`dxy_chg20`, `vix_chg20`, and `funding_rate_bps` are real fields in
`rule_dsl.py`'s `ALLOWED_FIELDS` and in `random_baseline.py`'s own
sampler (Rung 1's work), does simply having a wider field vocabulary
available inflate the PROMISING-WATCHLIST rate under **pure chance** --
before Eve or Adam ever run a real macro-conditioned session? If it
does, that inflation has to be priced into the evidence bar before
Rung 3, not discovered after.

**Method:** re-ran the identical K=200/seed=20260718 random-baseline
sweep (`auto_tester.test_hypothesis` combined-verdict scoring, same
methodology as the original baselines below) for all 5 real
`(asset, timeframe)` pairs already on file, now with the 4 macro fields
available to the sampler. "Before" = the original pre-macro baseline
already committed at `docs/investigations/<pair>_random_baseline_result.json`
(generated 2026-08-02). "After" = this rung's fresh rerun.

### FINDING, confirmed-from-data: PROMISING-WATCHLIST rate increased in all 5/5 pairs

| Pair | Before DIED/SKIPPED/P-W | Before P-W rate | After DIED/SKIPPED/P-W | After P-W rate | Δ (pp) |
|---|---|---|---|---|---|
| BTC/4h | 69 / 131 / 0 | 0.0% | 78 / 108 / 14 | 7.0% | **+7.0** |
| ETH/4h | 63 / 134 / 3 | 1.5% | 71 / 111 / 18 | 9.0% | **+7.5** |
| SOL/4h | 70 / 130 / 0 | 0.0% | 89 / 105 / 6 | 3.0% | **+3.0** |
| PAXG/4h | 63 / 129 / 8 | 4.0% | 77 / 112 / 11 | 5.5% | **+1.5** |
| BTC/24h | 64 / 136 / 0 | 0.0% | 54 / 122 / 24 | 12.0% | **+12.0** |

All figures are real, out of K=200 configs per pair (verdict_counts sum
to 200 in every file, before and after -- `SURVIVED` does not appear as
a key in any of the 10 files, before or after, i.e. 0/200 in every run).
Every "after" run reports `macro_referenced_count: 94` -- identical
across all 5 pairs, because the same fixed seed (20260718) drives the
same random field-selection draws regardless of asset; roughly 47%
(94/200) of sampled configs reference at least one of the 4 new macro
fields.

**Mean increase: +6.2 percentage points, range +1.5pp to +12.0pp,
5 out of 5 pairs increased, 0 decreased.** This is real, reproducible
noise inflation from vocabulary size alone, not from any genuine edge --
every config in this sweep is a random baseline by construction. Reported
plainly: wiring the macro fields into the DSL made the PROMISING-WATCHLIST
gate noticeably easier to clear by pure chance, in every single pair
tested.

### What this means for Rung 3

This does **not** mean the macro fields are broken or should be reverted
-- Rung 1 wired them for a real reason (see the correlation-discount work
above), and a wider vocabulary is expected to raise a baseline's freedom
to overfit noise somewhat. But the size of the effect (up to 12pp on
BTC/24h) means:
- Any real Eve/Adam macro-conditioned hypothesis in Rung 3 must be judged
  against **this rung's higher noise floor**, not the pre-macro one --
  a macro-conditioned hypothesis clearing PROMISING-WATCHLIST is now
  measurably less informative on its own than it was before Rung 1.
- Per the standing out-of-scope constraint (unchanged this rung, confirmed
  below): the evidence bar itself (30/yr threshold, 70/30 split,
  `MIN_SAMPLE_SIZE`, FDR alpha, bootstrap CI) was **not** loosened or
  tightened to compensate -- that is explicitly a Rung 3+ decision for the
  owner to make with this table in hand, not something to silently patch
  into the gate now.
- This table is the real, empirical case for treating that decision as
  load-bearing before Rung 3 runs a real session, rather than assuming
  the wider vocabulary is free.

### Files touched this rung

`nero_core/research_agent/rule_dsl.py`, `nero_core/data_sources/macro_data.py`,
`nero_core/eve/session.py`, `nero_core/eve/tools_defs.py`,
`nero_core/eve/random_baseline.py`, `nero_core/research_agent/auto_tester.py`,
`nero_core/research_agent/frequency_gate.py` -- the same 7-file set flagged
uncommitted since Rung 1, committed together as one commit this rung (see
git log below). Zero other `nero_core/` files touched.

### No evidence-bar constant touched, confirmed

`MIN_SAMPLE_SIZE`, the 30/yr threshold, the 70/30 IS/OOS split, FDR alpha,
and the bootstrap CI construction are byte-identical to before this rung
-- confirmed via `git diff` on each constant's own module; this rung adds
sampler/field-vocabulary surface area only, never touches the gate that
scores against it.

### Test counts

Run as two separate suites (this project's own established convention --
a single combined `pytest -q` from repo root incorrectly mixes the two
trees and produces false failures; see below):

- **Vatican-core (`tests/`, from repo root):** 2738 passed, 21 skipped,
  135 subtests passed, **4 failed, 1 error**.
- **Bellwether (`vatican/bellwether/tests/`, from its own directory,
  its own `pytest.ini`):** **75 passed, 0 failed.**

**All 5 non-passing items confirmed pre-existing and unrelated to this
rung**, none touch or are caused by any of this rung's 7 files:

1. `tests/test_research_agent_auto_tester.py::test_hypothesis` (ERROR) --
   pytest's default collector misidentifies the production function
   `auto_tester.test_hypothesis` (imported by name into the test module
   at module scope since commit `58bdfd82`, 2026-07-29) as a test case
   because of its `test_*` name, then fails at fixture setup since its
   real parameters aren't fixtures. **Reproduced identically with this
   rung's 7 files fully `git stash`-ed out against a clean HEAD** -- not
   a regression.
2. `tests/test_live_wiring_post_batch.py::LxmlAvailabilityTest::test_lxml_is_importable`
   (FAILED) -- `lxml` is not installed in this venv
   (`python -c "import lxml"` -> `ModuleNotFoundError`), an environment
   dependency gap, not a code issue.
3-4. `tests/test_psx_data.py` x2 (FAILED) -- same missing `lxml`
   dependency (HTML table parsing).
5. `tests/test_eve_citation_freshness.py::RealCommittedDataBackfilledTest::test_the_real_committed_eve_hypotheses_file_has_been_backfilled`
   (FAILED) -- asserts `docs/site_data/eve_hypotheses.json` has exactly
   16 records; it now has 21, real and legitimate, via commit `3cc5d37`
   ("Fix REFINEMENT tagging"), already on `main` before this rung started
   and unrelated to any Rung 2 file. The test's hardcoded expectation is
   stale against real data growth, not a bug this rung introduced.

**Discrepancy noted, not silently reconciled:** an earlier check-in this
session reported "2749 tests, 1 pre-existing unrelated failure" from a
prior full-suite run. This fresh run's real, independently-verified
count differs (2813 real passes across both suites, 5 non-passing items
instead of 1) -- most plausibly because `eve_hypotheses.json` grew to 21
records and/or the `lxml` gap opened between that earlier report and now.
Flagging this honestly rather than asserting the earlier number was
wrong or that this one silently supersedes it without explanation; either
way, none of the 5 items are new regressions from this rung's own diff,
which is the property this section exists to confirm.

### git log origin/main --oneline -3
