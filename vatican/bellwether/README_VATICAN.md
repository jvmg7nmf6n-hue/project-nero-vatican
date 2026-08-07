# Bellwether, vendored into Vatican

This directory is an upstream copy of the Bellwether Engine (source of truth:
`C:\Users\HP\Downloads\bellwether-engine\bellwether-engine`), vendored
unmodified per `docs/bellwether_audit.md` (Stage 0's audit — read that first
for the full picture; this file is a pointer, not a restatement).

## What this is

A 15-agent macro intelligence core that produces an explainable directional
bias for Gold and Bitcoin from monetary policy, liquidity, geopolitics,
on-chain, derivatives/ETF flow, and calendar signals. In Vatican, its role is
**not** a standalone signal source — it's a source of macro *state* that
Adam/Eve (`nero_core/research_agent/`, `nero_core/eve/`) can eventually
condition price-action hypotheses on, tested by the same statistical harness
as everything else. See the audit doc for why.

## Real-data status (as of Stage 2's provenance-leak-fix + dxy wiring,
2026-08-07 — re-verify before trusting an exact count, this changes fast)

- **`monetary_policy` is fully REAL** — both `real_yield_10y` and `dxy`.
  `real_yield_10y` reuses `nero_core/data_sources/macro_data.py` unmodified
  (FRED DFII10, t+2 lag). `dxy` does **NOT** reuse that module's own
  dollar-proxy pipeline — DXY isn't a valid Twelve Data symbol at all
  (confirmed in `docs/macro_risk_on_report.md`, which is *why* MACRO_RISK_ON
  itself falls back to UUP), so `dxy` is sourced directly via yfinance's
  `DX-Y.NYB` (ICE US Dollar Index — confirmed live, free, no key, real
  DXY-index-scale values ~90-110, history back to 1971). See
  `bellwether/data/providers.py::VaticanRealMarketData`'s own docstring for
  the full reasoning — this was a genuine unit-mismatch bug caught before
  shipping (UUP is ~$28, not DXY-scale, and would have silently miscalibrated
  `monetary_policy.py`'s `_DXY_NEUTRAL = 104.0` anchor by ~4x).
- **VIX (`liquidity`)**: free and buildable (same yfinance pattern), not yet
  wired.
- **BTC funding rate (`onchain`/`derivatives_etf`)**: free, already has a
  real Vatican source (`nero_core/data_sources/funding_data.py`), not yet
  wired.
- **ETF flows**: confirmed blocked (see `docs/etf_flow_audit.md`, already in
  this repo) — no ETF-flow signal will ever be real here without a paid
  source decision.
- **On-chain netflow/MVRV/LTH, stablecoin supply, derivatives skew/OI/
  positioning, calendar surprise**: unresearched, not confirmed blocked.
- Everything else runs on `bellwether/data/providers.py`'s original mock
  implementations (`random.uniform`, seeded) until/unless a later stage
  wires a real provider for it.

**Provenance is enforced end-to-end, not just at the source.** A
`DataProvenance` enum (`REAL`/`SYNTHETIC`/`MIXED`/`UNAVAILABLE`) lives in
`bellwether/schemas.py`. Every one of the 15 agents reports its own honest
provenance — including `risk`, `scenario`, `correlation`, and
`trade_recommendation`, which (for one increment) read the unfiltered
mock-inclusive signal set even after `gold_analysis`/`bitcoin_analysis` were
already fixed; that gap is now closed (see
`docs/bellwether_stage2_report.md`'s "close the provenance leak" section) —
a purely-synthetic agent's contribution is excluded from every live-mode
composite, all the way to the final `trade_recommendation`, with a
regression test (`tests/test_vatican_provenance.py::
test_no_agent_calls_ctx_all_signals_for_gold_or_bitcoin_in_live_mode`) that
tracks the actual call, not just the output shape.

## What this is NOT doing (as of Stage 1 — vendoring only)

- **No trade-log writes.** Bellwether's own `PredictionStore`
  (`bellwether/store/memory.py`) is separate from Vatican's Truth Ledger
  (`nero_core/truth_ledger/`) and stays that way — no cross-write.
- **No position sizing or order execution.** Bellwether outputs a bias with
  assumptions/risks, never a sized trade. It does not touch live execution
  of Vatican's verified survivors, per the master command's own ground rule.
- **No synthetic value reaches a `CandidateSpec`.** A macro field is only
  eligible for Adam/Eve hypothesis conditioning once its underlying provider
  is confirmed `real` — enforced in the schema, with a test (Stage 2).
- **No agent-internal changes in Stage 1.** Stage 1's own vendored copy was
  a black box; Stage 2 has since made deliberate, documented agent-internal
  changes (provenance fields, live/mock signal filtering) — see
  `docs/bellwether_stage2_report.md` for what changed and why.
- **Cross-import with `nero_core/` is a SOFT dependency, not a hard one.**
  `VaticanRealMarketData` imports `nero_core.data_sources.macro_data` and
  `yfinance` INSIDE its fetch functions (never at module load time), so this
  subpackage stays importable — and its own test suite stays green — even
  when neither is on the path (e.g. a standalone Bellwether checkout outside
  Vatican). Every real fetch degrades to the identical mock draw on any
  failure, never a guessed substitute. This is looser than
  `nero_core/eve/`'s own hard isolation rule (which forbids the import
  entirely, with one documented exception) — deliberately so, since
  Bellwether's whole point in this repo is consuming Vatican's real data,
  unlike Eve/research_agent's mutual isolation.
- **LLM streaming fix is a PREREQUISITE, not yet needed.** Confirmed (Stage
  0 and again in Stage 2): `bellwether/llm/client.py` still does a single
  blocking `await client.post(...)`, not streaming — the same shape that
  caused Adam's `ReadTimeout` failures before this repo's own streaming fix
  landed. Not ported yet because no agent currently passes `web_search=True`
  (confirmed by grep — `news_intelligence.py` explicitly passes `False`,
  every other call site omits the param), so there's no long-idle call for
  it to protect against today. **If any LLM path with web search is ever
  switched on (Stage 4+), the streaming fix ships FIRST, in the same change
  that turns web search on — not as a follow-up.**

## Running it standalone

```bash
pip install -r requirements-lock.txt   # exact versions verified against
                                        # Vatican's own environment, no
                                        # conflicts (see the file's header)
python -m pytest -q                    # 30 passed, 1-2 skipped depending on
                                        # whether nero_core/yfinance are on
                                        # the path (both degrade gracefully)
python run.py "Fed signals rate cut amid cooling inflation"   # data_mode
                                        # defaults to "mock"; set
                                        # BELLWETHER_DATA_MODE=live for the
                                        # real monetary_policy path
```

`requirements.txt` (unmodified from upstream) is kept alongside as the
vendored package's own declared version ranges — install `requirements-lock.txt`
for the exact, verified set. Neither file lists `nero_core`/`yfinance` —
both are soft dependencies for the real-data path only (see above); install
Vatican's own `requirements.txt` alongside this one if you want the real
`monetary_policy` path to actually activate rather than degrade to mock.
