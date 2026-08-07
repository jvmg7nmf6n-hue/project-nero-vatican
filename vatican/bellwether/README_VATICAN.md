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

## Real-data status (per the Stage 0 audit — re-verify before trusting an
exact count, this changes as Stage 2 lands)

- **`monetary_policy`** (real_yield_10y, dxy): being wired to real data in
  Stage 2, reusing `nero_core/data_sources/macro_data.py` unmodified (FRED
  DFII10, t+2 lag; dollar proxy via Twelve Data, t+1 lag).
- **VIX (`liquidity`)** and **BTC funding rate (`onchain`/
  `derivatives_etf`)**: free and buildable (funding rate already has a real
  Vatican source, `nero_core/data_sources/funding_data.py`), not yet wired
  as of Stage 1.
- **ETF flows**: confirmed blocked (see `docs/etf_flow_audit.md`, already in
  this repo) — no ETF-flow signal will ever be real here without a paid
  source decision.
- **On-chain netflow/MVRV/LTH, stablecoin supply, derivatives skew/OI/
  positioning, calendar surprise**: unresearched, not confirmed blocked.
- Everything else runs on `bellwether/data/providers.py`'s original mock
  implementations (`random.uniform`, seeded) until/unless a later stage
  wires a real provider for it.

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
- **No agent-internal changes in Stage 1.** This vendored copy is a black
  box; its own 12-test suite runs green standalone in this location, proving
  nothing broke in the move (see `requirements-lock.txt`).
- **No cross-import with `nero_core/`.** This subpackage stays
  self-contained; any integration code (real provider wiring, schema
  provenance labels) lives in `bellwether/` itself or in a thin adapter, not
  by reaching into `nero_core` internals from inside vendored agent code —
  same isolation discipline this repo already applies to `nero_core/eve/`
  never importing from `nero_core/research_agent/` except one documented
  exception.

## Running it standalone

```bash
pip install -r requirements-lock.txt   # exact versions verified against
                                        # Vatican's own environment, no
                                        # conflicts (see the file's header)
python -m pytest -q                    # 12 passed, confirmed in this location
python run.py "Fed signals rate cut amid cooling inflation"
```

`requirements.txt` (unmodified from upstream) is kept alongside as the
vendored package's own declared version ranges — install `requirements-lock.txt`
for the exact, verified set.
