# Architecture

## Design goals

1. **Explainability over signals.** The output is a decomposed, reasoned bias —
   net score, drivers, counter-case, scenarios — not a black-box number. Public
   news is priced in fast; the edge is structured framing and stress-testing.
2. **Separation of facts / expectations / predictions.** Every `AgentResult`
   carries these in distinct fields so a reader always knows what is observed vs.
   priced-in vs. inferred.
3. **Graceful degradation.** Each agent has an LLM path and a deterministic
   heuristic path. With no API key and no network, the full pipeline still runs.
4. **Swappable data.** Feeds sit behind interfaces; mock and live providers are
   interchangeable without touching agent logic.
5. **A real learning loop.** Predictions are persisted and scored; confidence is
   calibrated by the model's own track record.

## Data flow

```
events + market snapshot
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage A  (concurrent producers)                              │
│   news · calendar · geopolitical · monetary · liquidity ·    │
│   onchain · derivatives · correlation · historical · learning│
│   → emit Signals (per asset, biased, weighted) + facts       │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage B  gold_analysis · bitcoin_analysis                    │
│   → confidence-weighted aggregate + counter-case             │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage C  scenario  ·  risk                                   │
│   scenario → probability-weighted forward paths              │
│   risk → flags + a confidence haircut                        │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage D  trade_recommendation                                │
│   net read − risk haircut × learning calibration → bias      │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
              AnalysisOutput (spec JSON)  →  PredictionStore
```

Agents communicate only through the shared `AnalysisContext`: a stage reads the
results accumulated by earlier stages. This makes every module independently
testable and the orchestrator trivial.

## Key mechanics

- **Bias scale.** Five ordinal levels map to a −2..+2 score. A signal's
  `weighted_score = bias.score × strength`. Per-asset aggregation is a
  confidence-weighted mean, squashed through a logistic into `probability_up`.
- **Confidence.** Rises with signal *mass* (how much evidence) and *agreement*
  (how aligned). The risk engine then subtracts a haircut; the learning engine
  multiplies by a calibration factor derived from rolling accuracy.
- **Counter-case.** Built into the gold/bitcoin agents, not bolted on — the
  strongest opposing drivers are always surfaced to fight confirmation bias.
- **Learning.** `PredictionStore` records each call; `/feedback` supplies the
  realized return; directional accuracy and a Brier score feed the next cycle.

## Production roadmap (on top of this core)

This repo is the reasoning engine. The remaining platform deliverables from the
spec layer cleanly around it:

- **Persistence / ERD.** Replace the JSON `PredictionStore` with Postgres
  (`events`, `signals`, `analyses`, `predictions`, `outcomes`). The store
  interface is the only seam that changes.
- **Scheduling / ingestion.** Celery beat + workers to poll news and data feeds
  continuously; push events into `Orchestrator.analyze`.
- **Caching / broker.** Redis for the signal cache and Celery broker.
- **Streaming.** WebSocket endpoint to push fresh analyses to the dashboard.
- **Live providers.** Implement the five provider interfaces against real
  vendors (market data, macro calendar, on-chain, derivatives, ETF flows).
- **CI/CD.** Lint + `pytest` on PR; build and push the image; deploy.
- **Frontend.** Wire the existing Bellwether React dashboard to `/analyze`,
  `/analysis/latest` and `/stats`.

## Layout

```
bellwether/
  config.py          settings (env-driven)
  schemas.py         typed contracts + spec output
  llm/client.py      async Anthropic wrapper (+ web search), heuristic fallback
  data/providers.py  feed interfaces + deterministic mock implementations
  agents/            15 modules, each a BaseAgent
  orchestrator.py    staged multi-agent coordinator + output composition
  store/memory.py    prediction store / learning persistence
  api/main.py        FastAPI surface
```
