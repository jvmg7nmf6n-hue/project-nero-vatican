# NERO (original) Codebase Analysis

Source studied (read-only): `C:\Users\HP\Documents\Codex\2026-07-06\tu`
No writes were made to that path. This document is the required Step 1 output before scaffolding Vatican.

## Summary

NERO is a single Streamlit app (`app.py`, ~1,431 lines, 17 tabs) backed by a `nero_app/core/` package of ~37 modules (~8,400 lines), a `tools/` directory of 12 CLI entry points wired to GitHub Actions cron workflows, and a `tests/` directory with 20 test files. It combines: a three-agent macro/technical verdict pipeline, a quant analytics library, a mean-reversion paper trader, a 5-variant strategy lab, a prediction ledger with forward-outcome evaluation, an ETF-flow and gold real-yield macro layer, a White House/policy event-study system, and email/ntfy alerting.

## Module Inventory

### `nero_app/core/` (pipeline + intelligence)

| Module | Purpose |
|---|---|
| `agents.py` | Three-stage pipeline: `BrainAgent` (historical macro matching), `MarketAssessmentAgent` (technicals), `VerdictAgent` (weighted composite verdict + confidence/risk). |
| `orchestrator.py` | `NeroOrchestrator.run()` chains Brain → MarketAssessment → Verdict into one `NeroResult`. |
| `schema.py` | Pydantic models: `MacroEvent`, `AnalysisRequest`, `HistoricalMatch`, `BrainOutput`, `AssessmentOutput`, `VerdictOutput`, `NeroResult`, `BacktestResult`, `AssetSymbol` (str Enum). |
| `quant_intelligence.py` | Quant library — see detail below. |
| `consensus_engine.py` | Combines verdict, technicals, trade plan, news, market memory, White House impact into a 0–100 "trade quality" score + decision class. |
| `mean_reversion_agent.py` | Full mean-reversion paper-trading state machine — see detail below. |
| `strategy_lab_agent.py` | Runs 5 parameterized mean-reversion/breakout variants in parallel as separate paper-trading experiments. |
| `strategy_research_lab.py` | Reads paper-trade/rejection logs, proposes versioned strategy candidate changes for human-approved testing (no auto-promotion). |
| `strategy_performance_auditor.py` | Aggregates mean-reversion + prediction-log results into a 0–100 audit score/grade, flags insufficient sample size. |
| `prediction_log.py` / `prediction_lab.py` | CSV-backed prediction ledger; appends predictions and evaluates them against actual forward price outcomes. |
| `demo_trader.py` | Paper-trade ledger (CSV): activates, closes, and scores trades against live prices. |
| `trade_desk.py` | Builds intraday trade plan (entry, stop, TP1/TP2, R:R) from technicals + macro + sentiment + risk. |
| `trade_opportunity_scanner.py` | Aggregates quant/sentiment/ETF-flow/technical signals into TRADE_ALLOWED / WAIT / BLOCKED_BY_RISK / DATA_INSUFFICIENT with an explanation trail. |
| `trade_readiness.py` | Final conservative layer producing one readiness label. |
| `trade_path.py` | Converts a NO_TRADE/WAIT state into plain-language "what needs to improve" guidance. |
| `technical_analysis.py` | RSI, MACD, MA alignment, ATR, fair-value-gap, liquidity sweep, break-of-structure, regime detection, composite confluence score. |
| `market_data.py` | Multi-exchange OHLCV client (Binance/Coinbase/Kraken/Twelve Data) with live/fallback status. |
| `market_scanner.py` | Scans candles for large moves/breakouts/RSI extremes/volume spikes → scanner alerts. |
| `historical_prices.py` | Fetches daily OHLCV from Binance/Twelve Data, writes CSVs. |
| `historical_market_memory.py` | Matches current macro tags against a historical events CSV to score regime similarity. |
| `data_loader.py` | Loads macro event CSV + generates synthetic OHLCV for local/demo use. |
| `knowledge_store.py` | Local TF-IDF/cosine-similarity search over macro events for `BrainAgent`. |
| `backtester.py` | Event-driven backtest: forward return N days after each historical macro match, win-rate/avg return. |
| `ai_sentiment.py` | Headline sentiment scoring via Gemini API with a deterministic keyword fallback. |
| `news_feed.py` | Pulls/tags RSS headlines (Reuters, CNBC, Yahoo, CoinDesk, MarketWatch) with static fallback. |
| `social_intelligence.py` | Tracks a social-caller watchlist + call ledger, computes per-source reliability/win-rate. |
| `etf_flow_intelligence.py` | Proxy score (0–100) for spot BTC ETF demand from volume z-score/correlation/5-day return — explicitly labeled proxy, not real flow data. |
| `gold_real_yield.py` | Macro pressure on gold from real yield (official input or yfinance proxy fallback). |
| `btc_structural_models.py` | BTC supply-side context (halving era, stock-to-flow, miner cost floor) — explanatory, non-predictive. |
| `white_house_dataset_builder.py` | Builds enriched event-study dataset joining WH events with BTC/Gold forward returns (1/7/30-day). |
| `white_house_impact.py` | Keyword-tag classifier scoring a text's historical WH policy impact on BTC/Gold. |
| `white_house_sources.py` | Fetches/lists official WH/government source URLs. |
| `verdict_modifiers.py` | Adjusts verdict direction/confidence/risk using WH policy-impact scoring (BTC/GOLD only). |
| `mobile_alerts.py` | Formats trade alerts, sends via SMTP email or ntfy push. |
| `nero_chat.py` | Deterministic rule-based Q&A over current dashboard state (Urdu/English mix). |
| `settings.py` | Layered settings loader: env vars → Streamlit secrets → `local_settings.json`. Clean; no hardcoded values. |

### `tools/` (CLI entry points, driven by `.github/workflows/*.yml` cron jobs)

`nero_fetch_historical_prices.py`, `nero_github_monitor.py`, `nero_historical_memory.py`, `nero_mean_reversion_agent.py`, `nero_prediction_lab.py`, `nero_social_call_ledger.py`, `nero_strategy_lab_agent.py`, `nero_strategy_lab_weekly_report.py`, `nero_weekly_report.py`, `nero_white_house_dataset.py`, `nero_white_house_impact.py`, `nero_white_house_sources.py` — each is a thin CLI wrapper around one core module, mostly for scheduled automation + ntfy/email reporting.

### `app.py`

Single Streamlit page wiring nearly every core module into 17 tabs (Verdict, Trade Desk, Accountability, Mean Reversion, Strategy Audit, Research Lab, TEST Lab, Market Memory, Quant Intel, Trade Path, NERO Chat, Social Intel, Market Structure, News, Knowledge Store, Backtest, Prediction Log).

### Detail: `quant_intelligence.py`

All of the following are genuinely implemented, not stubs:
- **Correlation**: `rolling_correlation`
- **Beta**: `rolling_beta` (rolling OLS-style) and `kalman_dynamic_beta` / `build_kalman_beta_report` (real recursive Kalman filter)
- **Cointegration**: `engle_granger_cointegration` / `build_cointegration_report` (Engle-Granger ADF via `statsmodels`, degrades gracefully if unavailable)
- **Granger causality**: `granger_causality_pvalues` / `build_granger_causality_report` (`statsmodels.tsa.stattools.grangercausalitytests`)
- **GARCH**: `build_garch_volatility_report` (GARCH(1,1) via the `arch` package, EWMA fallback if not installed)
- Also: z-score, realized volatility, Sharpe/Sortino, max drawdown, information coefficient, lead-lag cross-correlation, cross-asset driver report, composite quant-consensus score.

### Detail: `mean_reversion_agent.py`

Per-asset state machine on closed 1h candles (Binance klines, market-data-client fallback). Each run: checks feed staleness → evaluates exit conditions (stop/target/max-holding-hours) on any open trade → evaluates entry (RSI < 35, close below lower Bollinger Band, close above MA200 uptrend filter, MA20 target above entry), logging every rejection reason → opens a long position sized by fixed 1% equity risk with ATR-based stop and a frozen MA20 target if a daily loss guard (-3R) hasn't tripped. State persists per-asset to JSON; all evaluations/trades/heartbeats append to CSV logs. Long-only, paper-trading only — never places real orders.

## Port Recommendation

**Safe to port largely as-is** (self-contained, no lookahead bias observed, clean interfaces):
- `schema.py` (Pydantic discipline is exactly what Vatican wants — port directly)
- `quant_intelligence.py` (pure functions over price series; only closed-candle inputs)
- `settings.py` (already environment/secrets-layered correctly)
- `technical_analysis.py`, `historical_prices.py`, `market_data.py` (well-isolated I/O + math)
- `mean_reversion_agent.py` (well-structured state machine; needs to move from ad-hoc JSON/CSV state to the new Truth Ledger + Strategy Registry, but the trading logic itself is sound)

**Needs restructuring before porting:**
- `consensus_engine.py`, `trade_opportunity_scanner.py`, `trade_readiness.py`, `verdict_modifiers.py` — logic is sound but currently scattered across four separate "decision layers" with overlapping responsibility; Vatican's Council Engine (Step 6) should consolidate this into one auditable scoring path rather than copy the fragmentation.
- `prediction_log.py`, `demo_trader.py`, `strategy_performance_auditor.py` — currently flat-CSV-backed; Vatican's Truth Ledger (SQLite, Step 4) replaces this storage layer, so port the *evaluation logic*, not the CSV I/O.
- `strategy_lab_agent.py`, `strategy_research_lab.py` — currently allow parameter changes without a formal versioning gate; Vatican's Strategy Registry (Step 5) must enforce immutable versions, so this needs a real interface change, not a lift-and-shift.
- `app.py` — 17-tab monolith; not part of Phase 0/1 scope at all.

**Out of scope for Phase 0/1 (future phases per CLAUDE.md):**
`etf_flow_intelligence.py`, `gold_real_yield.py`, `btc_structural_models.py`, `white_house_*.py`, `social_intelligence.py`, `news_feed.py`, `ai_sentiment.py`, `nero_chat.py`, `mobile_alerts.py`, and all of `tools/` + `.github/workflows/`.

## Secrets Check

Confirmed clean:
- `.gitignore` already excludes `.streamlit/secrets.toml`, `.env`, `.env.*`, `nero_app/data/local_settings.json`, and `nero_app/data/prediction_log.csv`.
- `.env.example` and `.streamlit/secrets.example.toml` contain only placeholder keys (blank values), never real credentials.
- `settings.py` loads credentials exclusively from env vars / Streamlit secrets / `local_settings.json` at runtime — no hardcoded keys in source.
- Grepped all `.py` files for hardcoded API-key/password patterns; the only two hits (`tests/test_historical_prices.py`, `tests/test_nero_core.py`) are mock values (`api_key="key"`, `api_key="test"`) passed to patched HTTP calls in unit tests, not real secrets.
- Did **not** open `.streamlit/secrets.toml`, `.env`, or `nero_app/data/local_settings.json` per the hard rule — their existence was confirmed via directory listing only, contents were never read.

No secrets were found in anything read. Nothing in this document reproduces a secret name's value.
