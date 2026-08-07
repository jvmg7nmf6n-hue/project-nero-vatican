# Bellwether Engine

A multi-agent macro intelligence core that produces **explainable directional
bias** for Gold (XAUUSD) and Bitcoin (BTCUSD) from macroeconomics, monetary
policy, geopolitics, liquidity, on-chain analytics and derivatives positioning.

It is the reasoning brain described in the *Institutional AI Macro Intelligence
Platform* spec — implemented as 15 coordinated agents that keep **facts,
expectations and predictions** separate, attach a **deliberate counter-case** to
every read, and **learn from their own accuracy** over time.

> It outputs a directional *bias for research*, never a guaranteed outcome or a
> sized order.

---

## Quickstart

```bash
pip install -r requirements.txt

# Run one analysis cycle (fully offline, mock data + heuristics)
python run.py "Fed signals rate cut amid cooling inflation; Record Bitcoin spot ETF inflows"

# Or serve the API
uvicorn bellwether.api:app --reload
```

No API key is required to run. Set one to switch on live Claude reasoning:

```bash
export BELLWETHER_ANTHROPIC_API_KEY=sk-ant-...
```

With Docker:

```bash
docker compose up --build
```

---

## What it produces

A single JSON document matching the spec exactly:

```json
{
  "timestamp": "...",
  "headline": "Fed signals rate cut amid cooling inflation",
  "category": "MONETARY_POLICY",
  "country": "USA",
  "importance_score": 0.69,
  "surprise_score": 0.0,
  "gold_bias": "BULLISH",
  "bitcoin_bias": "NEUTRAL",
  "confidence": 0.51,
  "probability_up_gold": 0.84,
  "probability_up_bitcoin": 0.52,
  "historical_matches": [ ... ],
  "assumptions": [ ... ],
  "risks": [ ... ],
  "alternative_scenarios": [ ... ],
  "reasoning": "GOLD — ... BITCOIN — ..."
}
```

---

## The 15 modules

| # | Module | Agent | Drives |
|---|--------|-------|--------|
| 1 | News Intelligence | `news_intelligence` | classifies events → per-asset signals |
| 2 | Economic Calendar & Surprise | `economic_calendar` | actual-vs-consensus surprise + catalyst rail |
| 3 | Geopolitical | `geopolitical` | tension → safe-haven mapping |
| 4 | Monetary Policy | `monetary_policy` | real yields + DXY (gold's core driver) |
| 5 | Liquidity | `liquidity` | VIX / MOVE / stablecoins (BTC's core driver) |
| 6 | Gold Analysis | `gold_analysis` | weighted synthesis + counter-case |
| 7 | Bitcoin Analysis | `bitcoin_analysis` | weighted synthesis + counter-case |
| 8 | On-chain | `onchain` | netflows, LTH supply, MVRV-Z |
| 9 | ETF / Derivatives | `derivatives_etf` | flows, funding, skew, positioning |
| 10 | Correlation | `correlation` | cross-asset regime context |
| 11 | Historical Analog | `historical_analog` | nearest-neighbour over labelled regimes |
| 12 | Scenario | `scenario` | probability-weighted base / bull / bear |
| 13 | Risk | `risk` | conflict / leverage / catalyst → confidence haircut |
| 14 | Trade Recommendation | `trade_recommendation` | final explainable bias |
| 15 | Learning | `learning` | rolling accuracy + Brier → calibration |

Every agent degrades gracefully: if the LLM is unavailable it falls back to a
deterministic heuristic, so the whole system always runs.

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | liveness + mode flags |
| POST | `/analyze` | run a full cycle over optional events |
| GET | `/analysis/latest` | last computed output |
| POST | `/feedback` | record a realized outcome (trains the learning loop) |
| GET | `/stats` | rolling accuracy / Brier calibration |

The learning loop closes like this: `/analyze` persists each prediction → later
you report what actually happened via `/feedback` → `/stats` reflects the new
accuracy → the next `/analyze` automatically scales its confidence by that track
record.

---

## Going live

Mock providers live behind interfaces in `bellwether/data/providers.py`. To use
real feeds, subclass `MarketDataProvider`, `CalendarProvider`, `OnChainProvider`,
`DerivativesProvider`, `EtfFlowProvider` and register them in `build_data_hub`
under `data_mode="live"`. Nothing in the agents changes.

See `ARCHITECTURE.md` for the design and the production roadmap (Postgres ERD,
Celery scheduling, WebSockets, CI/CD) that sits on top of this core.

---

## Tests

```bash
python -m pytest -q
```
