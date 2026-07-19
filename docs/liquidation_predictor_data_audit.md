# Comprehensive Asset Expansion, Part C: Crypto, Task C3 — LIQUIDATION_PREDICTOR
## STEP 1 Data Audit (mandatory, before any strategy code)

Tool: `tools/liquidation_predictor_data_audit.py`. Every check below is a real, live
HTTP call made directly from this environment — nothing here is inferred from memory
or vendor documentation alone. Full raw output in
`docs/liquidation_predictor_audit_raw_output.txt`.

## Conclusion: BLOCKED-ON-DATA

**No free, pollable, keyless REST liquidation-data source verified.** Per the task's
own instruction, LIQUIDATION_PREDICTOR v1.0.0 is **not built** — this audit is the
only artifact committed for this hypothesis. No strategy code, no proxy-faked
liquidation signal.

## 1. Liquidation-data sources checked

| Source | Endpoint | Result |
|---|---|---|
| Binance futures | `fapi.binance.com/fapi/v1/allForceOrders` | **Discontinued.** `400 {"code":400,"msg":"The endpoint has been out of maintenance"}` — Binance's historical public liquidation feed is no longer served. Confirmed directly, not assumed from stale documentation. |
| Bybit v5 | `/v5/market/liquidation`, `/v5/market/recent-liq`, `/v5/market/liq-records`, `/v5/market/all-liquidation` | **No such route.** All four plausible paths return `404`. A reachability sanity check against `/v5/market/recent-trade` (an ordinary, unrelated trades endpoint) returns `200` with real data, confirming the 404s are genuine "route doesn't exist" responses, not a network/geo block masquerading as one. Bybit's v5 public REST API simply does not expose historical liquidations — that data is only available (if at all) via the private authenticated `execution` endpoint or the `liquidation` WebSocket topic, neither of which fits "free, pollable REST." |
| OKX | `/api/v5/public/liquidation-orders` | **Inconclusive from this environment.** DNS resolution for `www.okx.com` failed outright (`NameResolutionError`) — this could reflect a real block on this network, or simply a transient/local DNS issue, and is reported honestly as unresolved rather than claimed as "OKX is blocked." A GitHub Actions runner should re-test this endpoint directly before ruling OKX out permanently; OKX's own documentation does describe this as a genuine public endpoint. |
| Coinalyze | `/v1/liquidation-history` | **Endpoint exists, but requires a registered API key.** Returns `401 {"message":"Invalid/Missing API key"}` — a real, documented route (not a 404), confirming Coinalyze does offer liquidation history, but not as a fully keyless free source. A free-tier API key might be obtainable via registration, but that requires a human to sign up and hold the credential — out of scope for this audit to obtain on its own, and inconsistent with "free, pollable" meaning "no signup gate" the way this task's other sources (Binance, Twelve Data, yfinance) all are. |

## 2. Existing funding pipeline (fapi.binance.com) — reachable, unaffected

`nero_core.data_sources.funding_data`'s existing endpoint,
`fapi.binance.com/fapi/v1/fundingRate`, returns `200` with real, current funding-rate
data. The funding leg of LIQUIDATION_PREDICTOR's design (condition 2:
`funding_rate < -0.001`) was never itself blocked — the existing pipeline is healthy
and needs no Bybit fallback. This is moot only because condition 1 (the liquidation
spike) has no free source at all, and the task's own design requires BOTH conditions.

## 3. Whale-transfer sources — confirmed NOT free, as instructed to verify rather than assume

- **Glassnode** `transfers_volume_large_sum`: `401 Authorization Required` — even on
  the metric this task suspected might be free-tier-accessible, authentication is
  required. Confirmed directly, exactly matching the task's own instruction not to
  assume Glassnode's free tier provides this.
- **Whale Alert** `api.whale-alert.io/v1/transactions`: `401`, requires an `api_key`
  parameter on every request — no keyless free path.

No free whale-transfer source was found. This is moot for v1 regardless, since
whale-flow was only ever an optional third condition contingent on condition 1
(liquidation spike) verifying first, which it did not.

## What this means for the batch

LIQUIDATION_PREDICTOR joins the same category ETF Flow occupied in an earlier phase
of this project: a real, well-motivated hypothesis that cannot be built honestly on
currently-available free infrastructure. The correct move is exactly what happened
here — stop at the audit, document why, and not proxy-fake a signal from adjacent
data (e.g. inferring "probable liquidations" from raw price/volume spikes) that would
silently misrepresent what the strategy is actually reacting to.

**If this is revisited later**: the two most promising paths are (a) re-testing OKX's
`/api/v5/public/liquidation-orders` from an environment without this network's DNS
issue (a GitHub Actions runner would be the natural next test), or (b) registering a
free Coinalyze API key (a human action, not something this audit can do
autonomously) and re-running this same audit tool against it.
