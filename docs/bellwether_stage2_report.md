# Bellwether Stage 1 + Stage 2 Report

Date: 2026-08-07. Follows `docs/bellwether_audit.md` (Stage 0). Stage 1
(vendor) and Stage 2 priority-1 (`monetary_policy` real wiring) are done;
priorities 2/3 (VIX, funding rate) are not started this session.

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
