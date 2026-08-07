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
