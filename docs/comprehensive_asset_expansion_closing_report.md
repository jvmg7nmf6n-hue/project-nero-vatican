# Comprehensive Asset Expansion Batch — Closing Consolidated Report
## Stocks + Forex + Crypto Hypotheses

Ten tasks, each committed separately: H2-BUILD, A1, A2, A3, B1, B2, B3, C1, C2, C3.
This report ties them together. Full detail lives in each task's own doc (linked
inline below).

---

## 1. STOCKS (Part A)

**Task A1 (`docs/stock_data_calibration_audit.md`)**: yfinance, 120/120 configs
(30 symbols x 4 timeframes) ADEQUATE, 0 unresolved. 1h capped at ~730 days (a Yahoo
plan limit). No native 4h — resampled market-hours-aware from 1h (a 6.5h RTH session
yields exactly one complete 4h bar + a dropped ~2.5h remainder). **Permanent
survivorship-bias caveat**: yfinance only serves currently-listed tickers, so this
27-stock universe cannot see any delisted/bankrupt/acquired company — SPY/QQQ/IWM are
the bias-free reference set.

**Task A2 (`docs/stock_task_a2_full_sweep.md`)**: 937 of 939 configs with a verdict.
**764 DIED (81.5%), 173 PROMISING-WATCHLIST (18.5%), 0 SURVIVED.** 2 configs
(AAPL/1week/BREAKOUT_MOMENTUM, AAPL/1day/BOS_CONTINUATION) cleared every statistical
bar pre-grid-shift and were classified SURVIVED by `classify_verdict` — both demoted
to PROMISING-WATCHLIST because grid-shift cannot run on native daily/weekly stock
data. Zero of 56 qualifying configs actually receive a grid-shift test (55 are
1day/1week; the one intraday config is native 1h, not a resampled timeframe like 4h).

**Task A3 (`docs/stock_task_a3_vol_clustering.md`)**: vol-clustering multiplier on the
top 3 (INTU/1day/MEAN_REVERSION v1, NVDA/1week/BREAKOUT_MOMENTUM, AAPL/1week/
BREAKOUT_MOMENTUM). R-multiple/win-rate exactly invariant (as everywhere). MaxDD
direction genuinely mixed (INTU improved, NVDA/AAPL worsened) — the first config in
this whole batch where drawdown didn't uniformly worsen.

**Summary**: 0 survivors. Sweet-spot timeframe **1day/1week** (91% of promising
configs). Best-performing family: **DONCHIAN_TREND** (16/30 configs promising, 53%
hit rate — the highest of any family in this entire batch). Top near-survivors: the 2
AAPL configs blocked purely by grid-shift inapplicability.

---

## 2. FOREX (Part B)

**Task B1 (`docs/forex_data_calibration_audit.md`)**: Twelve Data (already
integrated), 40/40 configs ADEQUATE, 0 unresolved — a materially better outcome than
metals (whose spot symbols 404 on this plan). All 4 timeframes native for every
pair, no resampling needed anywhere. 1h/4h depth is capped by a 5000-row
per-request limit (~219 days / ~3.2 years), not a true history shortage.

**Task B2 (`docs/forex_task_b2_full_sweep.md`)**: 318 of 318 configs, 0 fetch
failures. **294 DIED (92.5%), 24 PROMISING-WATCHLIST (7.5%), 0 SURVIVED.** Only 2
configs clear the adequate-both-halves bar (EUR/JPY/1week/BREAKOUT_MOMENTUM,
EUR/JPY/1day/BOS_CONTINUATION), both at 1day/1week where grid-shift doesn't apply
(Friday-close/Sunday-open gap precedent) — zero grid-shift tests run, no forex
SURVIVED.

**Task B3 (`docs/forex_task_b3_vol_clustering.md`)**: vol-clustering on both
qualifying configs. Same R/win-rate invariance. MaxDD worsened for both (-2.98pp,
-1.38pp) — the worst drawdown cost of any asset class tested.

**Summary**: 0 survivors. Sweet-spot timeframe **1week overwhelmingly** (19 of 24
promising configs) — the slowest timeframe tested in this whole project so far. JPY
crosses disproportionately represented (11 of 24 promising configs). No
survivorship-bias caveat applies to forex (Twelve Data pairs aren't "delisted" the
way stocks are).

---

## 3. CRYPTO (Part C)

**Task C1 — ORDERFLOW_IMBALANCE v1.0.0**: Built and wired into the live scheduler for
BTC/ETH, evaluated every 30-minute run (no candle-boundary gate). REST-polled
order-book snapshots (`data-api.binance.vision` primary, `api.binance.com` secondary)
cached to a new `orderbook_snapshots` table — a proprietary dataset accruing from this
point forward. **No backtest exists and none is possible** (order-book REST has no
historical replay) — labeled "experimental — snapshot-based, forward-testing only, no
backtest exists" everywhere (`verification_status.py`, `notify_ntfy.py`, module
docstrings). State is reconstructed from the Truth Ledger's own last-logged signal
(no candle series to replay from). **Status: LIVE**, accruing evidence starting now;
not proven, not claimed to be.

**Task C2 — Vol-clustering comparative (`docs/vol_clustering_c2_comparative.md`)**:
First-ever GOLD/1week and BNB/12h runs, combined with A3 (stocks) and B3 (forex) into
one 7-config, 3-asset-class table. **R-multiple expectancy and win-rate are provably
invariant to this multiplier everywhere** (a mathematical necessity of uniform
position-size scaling, not an empirical coincidence). MaxDD worsens in 6 of 7 configs
(not universally — INTU/stocks improved). Net dollar P&L improved in 6 of 7 configs.
**Conclusion: this multiplier is a leverage/risk-tolerance dial, not a performance
improvement, and should never be presented as an "edge enhancer."**

**Task C3 — LIQUIDATION_PREDICTOR (`docs/liquidation_predictor_data_audit.md`)**:
**BLOCKED-ON-DATA.** No free, pollable, keyless REST liquidation source exists:
Binance's public feed is discontinued, Bybit v5 has no such route, OKX was
inconclusive (DNS failure from this environment, needs re-testing from a GitHub
Actions runner), Coinalyze requires a paid-tier-style registered API key. No strategy
code was written — only the audit is committed, exactly as the task instructed for a
blocked hypothesis.

---

## 4. Aggregate findings

### Survival counts

| Asset class | Configs tested | SURVIVED | PROMISING-WATCHLIST | DIED |
|---|---|---|---|---|
| Stocks | 937 | 0 | 173 (18.5%) | 764 (81.5%) |
| Forex | 318 | 0 | 24 (7.5%) | 294 (92.5%) |
| **Combined** | **1,255** | **0** | **197 (15.7%)** | **1,058 (84.3%)** |

Crypto contributed no new sweep configs this batch (C1/C3 were builds/audits, C2 was
a targeted vol-clustering comparison, not a classify_verdict sweep) — its prior-phase
results (research phase closure, Asset Expansion Phase A) remain the crypto/metals
baseline.

### Which strategy families transferred best across asset classes?

**DONCHIAN_TREND is the standout cross-asset performer** — a majority (53%) hit rate
on stocks, a consistent 1week signal on metals (Phase A, both SILVER and PLATINUM),
and positive-both-halves results on 4 of 5 JPY-related forex pairs at 1week. It never
reaches SURVIVED anywhere (always sample-limited), but its consistency across four
distinct asset classes at the same timeframe is the single most repeatable pattern
in this project's research to date.

**FVG_REVERSION is the standout cross-asset FAILURE** — DIED on effectively all
configs across crypto (prior phase), metals (Phase A), forex (0/30 this batch), and
mostly stocks (9/90 promising, 81 DIED). A fourth consecutive asset class confirms
this family doesn't work, reinforcing rather than contradicting the existing verdict.

**COINTEGRATION_PAIRS is consistently weak but never dead** — thin, sample-limited
positive signals on BTC-ETH, Gold-Silver, Silver-Platinum (Phase A), 1 of 3 stock
pairs, and 1 of 3 forex pairs. The same character everywhere: a real but persistently
thin edge candidate, never strong enough to survive on its own.

**MEAN_REVERSION/BREAKOUT_MOMENTUM/TREND_PULLBACK** transfer moderately to stocks
(17-29 promising configs each out of 120) but weakly to forex (0-3 promising configs
each out of 40) — these crypto-native families read much better onto equities than
onto currency pairs.

### Asset-class comparison: survival rates

Stocks' PROMISING-WATCHLIST rate (18.5%) is more than double forex's (7.5%) —
entirely attributable to DONCHIAN_TREND's outsized stock hit rate and the generally
broader signal surface equities offer (larger universe, deeper history for many
names). Neither asset class produced a single final SURVIVED result.

### Vol-clustering: most effective on which asset class?

By the only metric that actually matters (risk-adjusted return): **none** — it is
mathematically incapable of improving R-multiple expectancy anywhere. By the
surface-level "dollar P&L up, drawdown cost" framing: **stocks showed the most
favorable profile** (all 3 configs' dollar P&L improved, and one of three even saw
drawdown improve slightly) versus forex (both configs' drawdown worsened, one
config's dollar P&L worsened too) and crypto (both dollar P&L improved but both
drawdowns worsened). This should be read as "which specific historical trade
sequences happened to have clustered-vol periods land favorably," not as evidence
the multiplier works better on stocks in any durable sense.

### New hypotheses: production-ready status and deployment timeline

- **H2 (vol-clustering multiplier)**: Infrastructure built, tested, and empirically
  evaluated across 3 asset classes. **Not recommended for production deployment** as
  a live position-sizing enhancement — it provides zero risk-adjusted benefit by
  mathematical necessity and usually (not always) worsens drawdown. If ever exposed
  to users, it must be labeled as a leverage/risk-tolerance control, never an "edge."
- **ORDERFLOW_IMBALANCE (C1)**: Already wired into the live scheduler, running every
  30 minutes for BTC/ETH as of this batch's commit. No deployment timeline needed —
  it is live now, forward-test-only, explicitly labeled experimental everywhere.
  Evidence will accrue in the Truth Ledger from this point forward; no claims are
  made about its quality until real trade history exists.
- **LIQUIDATION_PREDICTOR (C3)**: Not built. Blocked on data availability. No
  deployment path exists until either OKX's endpoint is confirmed reachable from a
  real GitHub Actions runner, or a Coinalyze API key is obtained (a human action, not
  something automatable from here).

---

## 5. Factual summary

- **Total configs tested (stocks + forex sweeps)**: 1,255
- **Total SURVIVED**: 0
- **Total PROMISING-WATCHLIST**: 197
- **Total DIED**: 1,058
- **Survivorship-bias caveat for stocks**: **Yes** — permanent, structural, documented
  in Task A1, and attached to every single-stock result in Task A2. Does not apply to
  forex or crypto.

Majority failure (84.3% DIED) is the expected, honestly-reported outcome consistent
with this project's stated ~1.5% historical survival rate for new strategy/asset
combinations — the data decided everything, and it decided against nearly all of it.
The batch's genuine contributions are: (1) two infrastructure builds now live in
production (ORDERFLOW_IMBALANCE forward-testing, vol-clustering harness available for
future research), (2) one hypothesis correctly identified as blocked rather than
faked (LIQUIDATION_PREDICTOR), (3) a mathematically-proven finding about
position-size-scaling multipliers that should prevent this exact kind of
sizing-only "enhancement" from ever being mistaken for a real edge in the future, and
(4) a clear, repeatable cross-asset-class signal (DONCHIAN_TREND at slow/weekly
timeframes) worth prioritizing in the next research phase.

No other research phase should start until this batch's findings are reviewed by the
user, per the task's own instruction.
