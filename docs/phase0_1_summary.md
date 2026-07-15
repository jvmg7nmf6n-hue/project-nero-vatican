# Phase 0/1 Summary — Project Vatican (NERO-2)

Scope was Steps 1–7 of `CLAUDE.md`, exactly as specified: analyze the original NERO
codebase, scaffold the repo, port quant intelligence + schema, build the Truth Ledger,
build the Strategy Registry with Mean Reversion as proof of concept, build a Council
Engine skeleton, and run the test suite. Nothing beyond that scope was touched.

## Test suite: passing

```
python -m unittest discover -s tests -v
Ran 78 tests in 1.5s
OK
```

All 78 tests pass. No skipped, no xfail, no placeholder assertions (`assertTrue(True)` etc.)
— every test in the suite exercises real code against a real assertion. This is reported
honestly: if it had failed, this document would say so rather than declaring the phase done.

## What got built

| Area | File(s) | Status |
|---|---|---|
| Codebase analysis | `docs/nero_analysis.md` | Done — full module inventory, port recommendations, secrets check of the original repo |
| Repo scaffold | folder tree, `.gitignore`, `requirements.txt`, `README.md`, `.env.example` | Done — matches `CLAUDE.md`'s spec exactly |
| Git repo | — | Initialized, 5 commits (one per step), `.gitignore` verified live against real secret-pattern files |
| Schema | `nero_core/schema.py` | Ported unchanged from original — 8 Pydantic models + `AssetSymbol` enum |
| Quant intelligence | `nero_core/quant/quant_intelligence.py` | Ported unchanged (~1,000 lines) — correlation, beta, Kalman dynamic beta, Engle-Granger cointegration, Granger causality, GARCH(1,1)/EWMA volatility, Sharpe/Sortino/drawdown, quant consensus scoring |
| Truth Ledger | `nero_core/truth_ledger/models.py` | New (not a straight port) — SQLite schema, CRUD, duplicate-prevention via `UNIQUE` constraint, `TRUE_POSITIVE`/`FALSE_POSITIVE`/`TRUE_NEGATIVE`/`FALSE_NEGATIVE`/`INCONCLUSIVE` truth-labeling |
| Strategy Registry | `nero_core/strategies/registry.py` | New — append-only `(strategy_id, version) → immutable parameters`; re-registering an existing version is rejected even with identical parameters |
| Mean Reversion strategy | `nero_core/strategies/mean_reversion.py` | Ported real decision logic (RSI/Bollinger/MA200/ATR rules, fixed-fractional position sizing, stop/target/time exits) from the original agent; registered into the Strategy Registry as the first variant |
| Council Engine | `nero_core/council/engine.py` | New skeleton — combines quant consensus + Mean Reversion signal into the specified JSON verdict shape |
| Tests | `tests/*.py` (7 files, 78 tests) | Real tests throughout — see per-module breakdown below |

Total: 21 Python files, ~1,834 lines under `nero_core/`.

## What's stubbed / fake / deliberately not built

Being explicit here is the point — this system's value proposition depends on not
overstating what exists.

- **`app.py`** is a one-line placeholder. No UI exists yet.
- **`nero_core/config.py`** is a placeholder stub — no settings loader has been ported yet (the original `settings.py` was analyzed but not ported; it's flagged safe-to-port in `docs/nero_analysis.md` for the next session).
- **Council Engine only has 2 of ~11 planned inputs wired up** (quant consensus + Mean Reversion). Every other input the full spec calls for — news sentiment, ETF flow, gold real-yield, BTC structural context, White House/policy impact, historical market memory, social intelligence, cross-asset quant drivers (correlation/beta/cointegration/Granger/Kalman beta need multi-asset data no `data_sources/` module fetches yet), and the other 4 strategy-lab variants — is **explicitly listed as "insufficient data" in every verdict's `top_blockers`**, never defaulted to a neutral-looking number or silently dropped.
- **`HIGH_QUALITY_SETUP` is structurally unreachable** in the current Council Engine — it requires corroboration from inputs that don't exist yet, and the code has no path that returns it. This is enforced by a test (`test_high_quality_setup_is_never_reachable_in_this_skeleton`), not just a comment.
- **Council Engine's `confidence` is deliberately capped low** (fraction of 2-of-11 planned inputs, e.g. ~0.09–0.18), not because the two available signals are unreliable, but because the Council as designed needs far more corroboration than exists yet. This is a structural honesty choice, documented in the module docstring.
- **No live data source is wired up.** `nero_core/data_sources/` is an empty package. Everything tested so far runs on synthetic/hand-constructed price data passed in directly — there is no Binance/Twelve Data/yfinance client in Vatican yet (the original's `market_data.py`, `historical_prices.py` were analyzed but not ported).
- **`arch` (GARCH(1,1)) is not installed** in this environment — no prebuilt wheel for this machine's Python version on Windows, and building from source needs MSVC Build Tools that aren't present. `quant_intelligence.py`'s existing EWMA fallback covers this transparently (tests confirm the fallback path works), but true GARCH(1,1) numbers are not being produced right now. This is a soft dependency, commented out in `requirements.txt` with the reason.
- **Mean Reversion has no persistence layer.** The ported strategy logic is pure functions over an explicit `MeanReversionState` object — there is no JSON/CSV state file, no live order loop, and it is not yet wired to write into the Truth Ledger. Running it against real market data end-to-end (fetch candles → evaluate → log to Truth Ledger → resolve outcome later) is next-phase work.
- **Only 1 of the original's 5 strategy-lab variants is ported** (Mean Reversion). `BREAKOUT_MOMENTUM_V1`, `MR_DEEP_VALUE_V1`, `MR_REGIME_FILTER_V1`, `MR_RELAXED_PULLBACK_V1`, `MR_TARGET_1R_V1` are not started, per explicit instruction not to port them yet.
- **No performance numbers are claimed anywhere.** Nothing in this phase runs against real market history long enough to produce a track record, so none is fabricated. The Truth Ledger exists specifically so that when trades do run, their outcomes are evidence rather than assertion.

## Known limitations

- Test coverage for the Council Engine's synthetic "confirmed signal" scenario relies on one hand-constructed price series (200-candle uptrend + 5-candle pullback) rather than a range of market regimes. It proves the wiring works, not that the Mean Reversion strategy itself is profitable — that question is exactly what the Truth Ledger is for, once real market data flows through it.
- The Council Engine's scoring formula (`global_score = quant_score + 15 bonus for confirmed MR signal`, discrete GARCH-regime→risk mapping) is a documented, transparent placeholder — it has not been validated against outcomes and should not be read as a tuned or backtested model.
- `git` was not installed on this machine at the start of this session; it was installed via `winget` with explicit user approval before any repo work began.
- Python 3.14 on this machine is new enough that some scientific-stack packages (`arch`) don't yet ship prebuilt Windows wheels — noted above, and worth revisiting with a slightly older Python or once wheels catch up.

## Proposed plan for the next phase

Per `CLAUDE.md`, this is an outline only — nothing below should be built without a
separate, explicit go-ahead.

1. **Data sources layer** (`nero_core/data_sources/`): port `market_data.py` and `historical_prices.py` from the original so quant consensus and Mean Reversion can run against real Binance/Twelve Data candles instead of hand-built test fixtures. This unblocks everything else.
2. **Wire Mean Reversion end-to-end**: connect the ported strategy logic to the Truth Ledger (each `evaluate_entry`/`evaluate_exit` call writes a `PredictionRecord`; outcomes resolve via `update_prediction_result`), replacing the original's JSON/CSV state files. This is the first real accuracy data the system will produce.
3. **Full strategy portfolio**: port the remaining 4 strategy-lab variants (`BREAKOUT_MOMENTUM_V1`, `MR_DEEP_VALUE_V1`, `MR_REGIME_FILTER_V1`, `MR_RELAXED_PULLBACK_V1`, `MR_TARGET_1R_V1`) into the Strategy Registry, each as its own explicitly versioned variant.
4. **Expand Council Engine inputs incrementally**, one at a time, each with its own honest insufficient-data fallback until it's actually wired: cross-asset quant drivers (needs `yfinance` data source), historical market memory, news sentiment, ETF flow intelligence, gold real-yield, BTC structural context, White House/policy impact, social intelligence.
5. **`nero_core/config.py`**: port the original `settings.py` layered-config pattern (env → Streamlit secrets → local JSON) now that there's a config consumer (data source API keys) to justify it.
6. **UI** (`app.py`): a minimal Streamlit view over the Council Engine's verdict + Truth Ledger history — deliberately after the data/logic layers are solid, not before.
7. **Alerts and reports**: mobile/email alerting and weekly performance reports, ported last since they depend on everything above already producing real signals worth alerting on.
8. **GitHub Actions automation** (`.github/workflows/`): scheduled runs of the Mean Reversion agent and Council Engine, mirroring the original's cron-driven `tools/` scripts, once there's something real to schedule.

The ordering above is deliberate: data sources unblock real signal generation, which
unblocks real Truth Ledger evidence, which is the only thing that should ever justify
expanding the Council Engine's confidence beyond its current honestly-low baseline.
