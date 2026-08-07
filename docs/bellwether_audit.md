# Bellwether Audit — Stage 0

Date: 2026-08-07. Source of truth: `C:\Users\HP\Downloads\bellwether-engine\bellwether-engine`.
The second copy (`2026-07-10\aik\...\bellwether-engine-main`) is functionally
identical — its `bellwether/` package differs only in formatting/docstrings
(verified with `diff` on every differing file). It additionally carries
`MASTER_SPEC_1.md` (the original aspirational build brief for "Bellwether X" —
useful context, not implemented), `dashboard.py`, a stray `__init__.py.bak`,
committed `__pycache__/`, and a committed `.bellwether_store.json` (8
predictions, 0 scored, all NEUTRAL — matches the master command's [VERIFY]
claim exactly). None of that affects the audit below; all findings are against
the Downloads copy.

**Correction to the master command's own [VERIFY] list**: the claim that none
of `requirements.txt`, `ARCHITECTURE.md`, `docker-compose.yml`, or
`Dockerfile` exist at the archive root is **false** for the source-of-truth
copy — all four are present and match the README's description. (They're
genuinely missing from the *second* copy, which is likely where that
observation came from.)

**The two copies differ materially — do not vendor from the second one.**
Confirmed 2026-08-07: the second copy
(`2026-07-10\aik\...\bellwether-engine-main`) is missing `requirements.txt`,
`ARCHITECTURE.md`, `docker-compose.yml`, `Dockerfile`, `.env.example`, and
`pytest.ini` outright, and additionally carries files that must never be
vendored — a stray `__init__.py.bak`, committed `__pycache__/` directories,
and a committed `.bellwether_store.json` (8 predictions, 0 scored, all
NEUTRAL — real residue from a prior run, not a fixture). Its `bellwether/`
package source is functionally identical to the Downloads copy (diffed every
differing file — formatting/docstrings only, no logic differences). Stage 1
vendors from the Downloads copy exclusively.

---

## 4.1 Does it run, and what does it emit today?

Ran clean in an isolated venv (`pip install -r requirements.txt pytest
pytest-asyncio` — nothing in `requirements.txt` conflicted with anything).

- **`python -m pytest -q`: 12 passed**, exactly matching the [VERIFY] count.
  Read all three test files (129 lines total). Verdict: **mostly structural
  shape checks**, not behavioral verification — `test_liquidity_agent`
  asserts `0 <= confidence <= 1`, `test_derivatives_agent` asserts the signal
  set covers both assets, `test_output_serialization_has_spec_fields` checks
  key presence. One real exception: `test_learning_loop_updates_accuracy`
  actually records an outcome and asserts `rolling_accuracy() == 1.0` —
  genuine behavioral coverage of the one place that matters most (the
  learning loop). Nothing tests agent-level directional correctness (e.g.
  "rising real yields should score gold bearish") — there's no test that
  would catch a sign error in any of the 15 scoring formulas.
- **`python run.py "Fed signals rate cut amid cooling inflation; Record
  Bitcoin spot ETF inflows"`**: ran, real JSON below (default seed 42, mock
  mode, no LLM key). Confidence 0.283. Only the first `;`-split headline
  actually got used as the "primary event" — `run.py` ingests both as
  separate `MacroEvent`s, but the orchestrator's headline-selection logic
  (`_primary_event`) only picked one for the top-level `headline`/`category`
  fields (both still feed signals internally).
  ```json
  {"gold_bias": "BULLISH", "bitcoin_bias": "NEUTRAL", "confidence": 0.283,
   "probability_up_gold": 0.836, "probability_up_bitcoin": 0.484, ...}
  ```
- **The NEUTRAL/low-confidence claim — measured, not assumed.** [VERIFY]
  cited 0.234/0.093 against a 0.35 actionable bar from the committed store.
  I ran 180 real cycles (30 seeds × 6 headline scenarios, `persist=False`,
  fully offline):
  - Confidence: min 0.147, max 0.485, **mean 0.295**, median 0.285.
  - **80.6% of runs (145/180) landed below the 0.35 actionable threshold.**
  - Gold NEUTRAL in 78.3% of runs, Bitcoin NEUTRAL in 73.3%.
  - **Headline content barely moves the outcome.** For seed 0, four of six
    headline scenarios produced byte-identical confidence/bias — the
    quantitative mock snapshot (drawn once per `Orchestrator`, shared across
    the run) dominates; the news/geopolitical keyword-matched signals add a
    small delta on top, not the primary driver.

  **Why, traced exactly (this is the useful part):**
  1. `learning.py`: with 0 scored predictions, `rolling_accuracy()` returns a
     hardcoded default of **0.5**, always — not a penalty, a neutral prior.
  2. `trade_recommendation.py`: `calib = 0.7 + 0.6 * (accuracy - 0.5)`. At
     accuracy 0.5, `calib = 0.7` **permanently**, until real scored history
     ever pushes accuracy away from 0.5. This is a deliberate "you haven't
     earned trust yet" haircut baked into the formula, not a bug and not
     specific to mock data.
  3. `_synthesis.aggregate()`: `confidence = 0.3 + 0.45*agreement +
     0.25*mass`, where `agreement = |net_score|/2` and `mass =
     min(1, total_strength/4)`. Both cap at 1 only when every signal for an
     asset agrees AND carries near-max strength — realistically rare because
     the 9 producer agents draw from **independent** `random.uniform()`
     calls with no engineered correlation between them, so they routinely
     partially disagree.
  4. `final_conf = round(max(0, (raw_conf - haircut) * 0.7), 3)` — even a
     strong raw read of 0.7 nets out at ~0.49 before any risk haircut, and
     the risk engine's own haircut (up to 0.5, capped) subtracts further.

  **This is a mix of two effects, not one**, and separable: (a) a
  **deliberate, permanent 30% calibration haircut** that stays until the
  system earns real scored history (works identically on real data), and (b)
  a **mock-data artifact**: because the 5 mock providers draw independently
  and uncorrelated, `agreement` and `mass` rarely climb high. Real macro data
  is NOT independent — real yields, DXY, and VIX genuinely co-move in
  regimes — so real data should raise `agreement` for at least the
  `monetary_policy`/`liquidity` pairing specifically. Whether that's enough
  to clear the bar is an empirical question Stage 2 should measure directly,
  not assume.

## 4.2 Opportunity map (15 agents)

| # | agent | inputs | current source | real-data feasibility | Vatican already has this? | new hypothesis axis unlocked | cost to wire |
|---|---|---|---|---|---|---|---|
| 1 | `news_intelligence` | event headline text | keyword heuristic (LLM path exists, unused by default) | Real (text is real input) but scoring is keyword-list heuristic, not evidence-backed | No | N/A for DSL — text classification, not a numeric field | free (already works) |
| 2 | `economic_calendar` | actual vs. consensus print + upcoming catalyst dates | `MockCalendar`: hardcoded FOMC/CPI/NFP schedule, `random.uniform` surprise | Calendar dates: free (many public econ calendars). Surprise (actual vs consensus): needs a real print-and-consensus feed — harder | No | `economic_calendar_surprise_pending` as a catalyst-proximity filter ("skip entries 48h before FOMC") | paid/hard for surprise; calendar dates alone are free but low value without surprise |
| 3 | `geopolitical` | event headline text | keyword heuristic / LLM | Real (text) | No | N/A for DSL — text, not numeric | free |
| 4 | `monetary_policy` | `real_yield_10y`, `dxy` | `random.uniform` | **Real, already built** — `nero_core/data_sources/macro_data.py` (DFII10 via FRED, t+2 lag) + dollar proxy (UUP/DXY/EURUSD via Twelve Data, t+1 lag), correct forward-fill via `merge_asof` | **Yes, exactly** | `real_yield_10y_20d_change` / `dxy_20d_change` as DSL fields → `GOLD breakout WHEN real_yield_10y declining over 20 bars` | **free, already owned** — highest-value target |
| 5 | `liquidity` | `vix`, `stablecoin_supply_chg_pct` | `random.uniform` | VIX: free via yfinance (`^VIX` ticker) — same library already used for SILVER/PLATINUM futures fallback in `market_data.py`, not yet wired for VIX. Stablecoin supply: no existing Vatican source, needs research (likely free — on-chain aggregators publish USDT/USDC supply) | Partial — VIX plausible-free-not-built, stablecoin unresearched | `vix_regime` (risk-on/risk-off filter) — `GOLD reversion WHEN vix > 25` | low (VIX) / unresearched (stablecoin) |
| 6 | `gold_analysis` | aggregates signals 1-10 for GOLD | `_synthesis.aggregate()`, heuristic; LLM only narrates text | Downstream of whichever inputs above are real | Partial (inherits from #4 today) | Not a new axis itself — a synthesis point | free (once inputs are real) |
| 7 | `bitcoin_analysis` | aggregates signals 1-10 for BTC | same as #6 | same as #6 | Partial | same as #6 | free |
| 8 | `onchain` | exchange netflow, LTH supply change, MVRV-Z, funding rate (BTC) | `random.uniform` | Funding rate: **real, already built** (`nero_core/data_sources/funding_data.py`, free Binance public endpoint, no key). Netflow/LTH/MVRV-Z: no Vatican source exists; typically Glassnode/CryptoQuant (paid) or free-tier-limited | Partial (funding rate yes, on-chain metrics no) | `btc_funding_rate` as a crowded-leverage filter | free (funding) / paid or unresearched (rest) |
| 9 | `derivatives_etf` | BTC/gold ETF flow, perp funding, 25d skew, OI change, gold mgr net-long | `random.uniform` | ETF flows: **confirmed blocked** — `docs/etf_flow_audit.md` (already in this repo) tested Farside (403), CoinGlass (paid), fund-sponsor sites (403), yfinance `get_shares_full` (empty/unusable), Twelve Data (no such endpoint). BTC perp funding: same real free source as #8. Skew/OI/gold positioning: unresearched, plausibly CME/CFTC COT (free, weekly, lagged) for gold net-long | Partial (funding yes; ETF flow explicitly blocked; rest unresearched) | `btc_perp_funding` — same axis as #8 | free (funding) / blocked (ETF) / unresearched (rest) |
| 10 | `correlation` | hardcoded stylised correlation constants (`-0.7`, `0.55`/`0.35`, `0.4`/`0.2`) | **not even mock-random — literally hardcoded numbers**, README/[VERIFY] undersold this | Real rolling correlation is computable directly from Vatican's own real candle history (BTC, GOLD, plus a VIX/yield proxy) — no new data source needed, just a rolling-correlation computation | Yes (candle data exists; just needs the computation) | Not a primitive per se — could inform a `regime_tilt` field | free, but needs code, not just a provider swap |
| 11 | `historical_analog` | hand-built 5-row regime library, nearest-neighbour on `real_yield_10y`/`dxy`/`vix` | hardcoded table, LLM only adds narrative text | The nearest-neighbour distances would use real values once #4/#5 are real; the *library* itself (5 rows) stays hand-curated/labelled by construction — this is inherently a curated-analogy tool, not something with an obvious "real data" upgrade path beyond richer library rows | No (library is a design artifact, not a feed) | Not a DSL field | free (once inputs real), but limited value-add |
| 12 | `scenario` | LLM-generated or heuristic 3-scenario spread from gold/btc bias | heuristic fixed structure; LLM can fully replace it | Not really a "data" feasibility question — LLM narrative generation | N/A | N/A for DSL | LLM cost only |
| 13 | `risk` | signal disagreement count, funding froth, MVRV froth, imminent catalyst, VIX>25 | derived from #8/#9/#2/#5 above | Inherits from those | Inherits | Could gate hypothesis eligibility (e.g. exclude entries the day of FOMC) rather than being a DSL field itself | free (once inputs real) |
| 14 | `trade_recommendation` | risk haircut + learning calibration applied to #6/#7 | pure arithmetic | N/A — no external data, this is composition logic | N/A | N/A | free |
| 15 | `learning` | own prediction store, scored history | real once outcomes are actually recorded | Mechanically already "real" — it's genuinely tracking whatever it's fed; currently fed synthetic bias — see §4.1 | No parallel exists in Vatican (Vatican's own Truth Ledger is the closer analog, separate system) | N/A for DSL | free |

**The headline number**: of 15 agents, **2 have a real, already-built, free
data path in this repo today** (`monetary_policy` via
`nero_core/data_sources/macro_data.py`; the BTC-funding-rate half of
`onchain`/`derivatives_etf` via `nero_core/data_sources/funding_data.py`).
**1 more (`liquidity`'s VIX half) is free and plausible but not yet wired**
(same yfinance path already used elsewhere in this codebase). **1 is
confirmed blocked** (ETF flows — this repo already did that legwork).
**The rest (on-chain netflow/MVRV/LTH, ETF flows, calendar surprise,
derivatives skew/OI/positioning, stablecoin supply) are either paid,
unresearched, or — for `correlation`/`historical_analog`/`scenario`/`risk`/
`trade_recommendation`/`learning`/`gold_analysis`/`bitcoin_analysis` —
downstream composition rather than independent feeds.** `news_intelligence`
and `geopolitical` are real text-in/real text-out today (the "randomness" is
only in the *keyword heuristic's scoring*, not the input) but don't produce
DSL-eligible numeric fields at all — their value is narrative, not a
condition Adam/Eve could branch on.

## 4.3 Can macro fields live in the DSL?

**Yes, and the mechanism to do it already exists in this codebase under a
different name.** Traced `nero_core/research_agent/rule_dsl.py` in full:

- `ALLOWED_FIELDS` is a flat tuple of 16 names (`close`, `ma20`, ...,
  `vol_ma20`). `evaluate_condition`/`rule_fires_at` are **field-name
  agnostic** — they just do `row.get(condition.field)` against whatever
  columns exist on the frame `compute_indicator_frame` returns. Nothing in
  the evaluation path hardcodes what each field *means*.
- `compute_indicator_frame(candles)` starts with `frame =
  candles.sort_values(...).reset_index(drop=True).copy()` — it **adds**
  columns, it doesn't reduce to a fixed known set. Any column already
  present on the input `candles` frame before this call survives untouched
  into the output.
- **`nero_core/strategies/macro_risk_on.py` already solves exactly this
  problem** for a full strategy (not the DSL, but the identical alignment
  mechanics): it consumes an "already regime-merged candle frame" produced
  by `nero_core/data_sources/macro_data.py::build_regime_frame`, which does
  the lagged-change computation on the macro series' own business-day index,
  then `merge_asof(direction="backward")`-forward-fills it onto the candle
  grid. The module's own docstring calls this "the same separation-of-
  concerns COINTEGRATION_PAIRS and LEADLAG_FOLLOW use for their own external
  inputs" — three existing precedents, not a new pattern.

**Mechanically, adding `dfii10_change_20d`/`dollar_change_20d` to the DSL is
a pre-merge, not a DSL-engine change**: call
`macro_data.align_macro_to_daily_candles` (or `build_regime_frame` directly)
on the raw candle frame *before* passing it to `compute_indicator_frame`, add
the resulting column name(s) to `ALLOWED_FIELDS`. `compute_indicator_frame`
needs no change at all — it already preserves unknown input columns.
`frequency_gate.py`, `auto_tester.py`, `scanner.py`, and
`repair_forward_tracker.py` (the four real callers of
`compute_indicator_frame`) would each need this extra pre-merge step for any
(asset, timeframe) whose hypothesis references a macro field — a
straightforward, bounded change, not an architectural one.

**Alignment**: directly reusable, not just similar — `macro_data.py`'s t+1
(dollar)/t+2 (DFII10) lag discipline and strict-forward-fill-only
`merge_asof` already handle exactly the "daily/weekly macro series onto
daily candles" case the master command asked about. One real subtlety: macro
series are the same regardless of asset (real yields don't have a BTC
version and a GOLD version), so the merge is asset-independent — the exact
same lagged-macro-series merges onto both BTC's and GOLD's candle frames
identically. No new alignment code is needed beyond what exists.

**Frequency arithmetic — real numbers, using this repo's own real
constants** (`frequency_gate.py`: `TARGET_RESOLVED_TRADES = 30`,
`FAST_MAX_MONTHS = 6.0`, `VIABLE_MAX_MONTHS = 12.0` — FAST needs a rate
≥60/yr, VIABLE needs a rate ≥30/yr; below 30/yr the base rule alone would
already be TOO_SLOW):

| base rate (fires/yr) | macro filter true-rate | combined rate | months to 30 trades | classification |
|---|---|---|---|---|
| 60 (FAST boundary) | 40% | 24/yr | 15.0 | **TOO_SLOW — rejected** |
| 100 | 40% | 40/yr | 9.0 | VIABLE (was FAST alone) |
| 200 | 40% | 80/yr | 4.5 | still FAST |
| 30 (VIABLE boundary) | any <100% | <30/yr | >12 | **TOO_SLOW — rejected outright** |
| 60 | 70% (mild regime tilt) | 42/yr | 8.6 | VIABLE |
| 60 | 90% (near-always-true field) | 54/yr | 6.7 | VIABLE, near FAST |

The arithmetic makes the shape of the problem obvious: **a macro filter that
is true a small minority of the time (10-40%) will push all but the
highest-frequency base rules straight into TOO_SLOW**, and any rule already
sitting near the VIABLE floor (30/yr) cannot survive *any* macro filter below
100% true-rate. A macro filter that is true a *majority* of the time (a mild
regime tilt, e.g. "real yields not currently rising," which by construction
is true whenever they're falling OR flat — plausibly 55-70% of history
empirically, not measured here) costs much less frequency and is far more
likely to leave a VIABLE-or-better rule intact.

**Recommendation**: prefer regime-tilt-shaped macro fields (true a majority
of the time) over narrow-gate-shaped ones (true rarely) as the first
candidates, specifically *because* the frequency gate is unforgiving, not
because narrow gates are conceptually worse. Concretely for Stage 3: don't
propose "`WHEN dfii10_20d_change < -0.3`" (an arbitrary narrow threshold,
true-rate unknown, unmeasured) — propose "`WHEN dfii10_20d_change < 0`" (a
sign flag, true roughly half of history by construction, cheap in frequency
terms) as the first cut, and only tighten thresholds later once real
true-rates are measured on real history. Also: only offer macro conditioning
to Adam/Eve for base rules that already clear the gate comfortably (say
≥100/yr unconditioned) — pooling near-boundary candidates into families, or
extending the lookback window, are real fallback options per the master
command's list but shouldn't be reached for first; they add complexity this
gate's existing philosophy ("never guess, never extend by exception") argues
against reaching for early.

**Ranked first candidates** (availability × hypothesis value × alignment
tractability):
1. `dfii10_change_20d` (sign or magnitude) — real, free, already computed by
   `macro_data.py`, directly reusable lag/alignment code, gold's single
   biggest fundamental driver per Bellwether's own `monetary_policy` agent
   design.
2. `dollar_change_20d` — same pipeline, same file, free, applies to both
   BTC and GOLD.
3. `vix_regime` (once wired — not yet a Vatican data source, but same free
   yfinance path already used for SILVER/PLATINUM) — liquidity/risk-appetite
   axis, complementary to the two real-yield-family fields above, not
   redundant with them.

## 4.4 The LLM path

- **Traced every `self.llm` call site in `bellwether/agents/`.** Only 6 of 15
  agents touch the LLM at all: `news_intelligence`, `geopolitical`,
  `gold_analysis`, `bitcoin_analysis`, `historical_analog`, `scenario`. Of
  those, only 3 can change the *numeric/directional* output —
  `news_intelligence` and `geopolitical` (LLM directly produces the signals
  when events are present) and `scenario` (LLM can fully replace the
  heuristic 3-scenario spread). `gold_analysis`/`bitcoin_analysis`/
  `historical_analog`'s LLM calls only generate narrative text — the bias/
  score/probability is computed heuristically beforehand regardless of LLM
  availability.
- **[VERIFY] confirmed on `config.py`**: `enable_web_search: True`,
  `web_search_max_uses: 5`, `llm_model: "claude-sonnet-4-6"`,
  `llm_max_tokens: 1500`, `llm_timeout_seconds: 60.0` — all exactly as
  claimed.
- **A genuine surprise, not in the [VERIFY] list**: despite
  `enable_web_search: True` in config, **grepping every `complete_json`/
  `complete` call site in `bellwether/agents/` found zero that pass
  `web_search=True`.** `news_intelligence.py` explicitly passes
  `web_search=False`; every other call site omits the parameter, which
  defaults to `False` in `LLMClient.complete_json`. **As currently wired, no
  agent ever triggers a web search, regardless of the config flag.** This
  directly changes the answer to the contamination question below.
- **Streaming vs. blocking — confirmed blocking.** `bellwether/llm/
  client.py::complete()` does a single `resp = await client.post(...)`
  inside `httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds)` —
  one shot, no streaming, matching exactly the shape that produced repeated
  `ReadTimeout` failures in Adam before this repo's own streaming fix
  landed. **If Bellwether's LLM path is ever exercised for real (Stage 4+),
  port that fix** — it already exists in this codebase (Adam's
  `hypothesis_gen.py`/`llm_client.py`, per the mock-fixture-duplication
  gotcha already on file: 6 separate test files patch that call site, so a
  streaming port needs to update all 6, not the 1-2 that look most
  relevant).
- **Contamination**: moot today, precisely because web search is currently
  never actually invoked (see above) — there is no live-web-search-derived
  post-T information entering any agent's output as the code stands. If
  Stage 4+ ever flips `web_search=True` anywhere, the contamination
  constraint from the master command applies in full: backward-looking
  evaluation of that agent's output becomes methodologically unsound, and
  only forward-recorded reads would be admissible (relevant to Stage 5's
  promotion-criteria design, not Stage 0's scope).
- **Reproducibility**: the heuristic path is fully deterministic (seeded
  RNG, keyword lists) — reproducible by construction. The LLM path is not,
  by nature of LLM sampling, and isn't exercised in any test.

## 4.5 Integration notes

- **Dependencies**: no conflicts found. `pydantic>=2.6`, `pydantic-
  settings>=2.2`, `httpx>=0.27`, `fastapi>=0.110`, `uvicorn[standard]>=0.29`,
  `python-dotenv>=1.0` installed cleanly into a fresh venv alongside
  `pytest`/`pytest-asyncio`; none of these packages appear in Vatican's own
  `requirements.txt` today, so nothing to downgrade or reconcile — this
  would be a purely additive dependency set, isolated per the master
  command's own instruction if anything did conflict.
- **`store_path: "./.bellwether_store.json"` is relative — confirmed a real
  risk.** Under a scheduler (e.g. GitHub Actions, matching Vatican's own
  `.github/workflows/` pattern) where the working directory isn't guaranteed
  identical run-to-run, this would silently create/read a different file
  each time, quietly losing prediction history with no error — needs an
  absolute, repo-relative path once this is wired into any scheduled job
  (Stage 4).
- **Committed secrets: none found.** Grepped the full source tree for
  `secret`/`api_key`/`API_KEY`/`sk-ant`/`token` — every hit is either a
  config field *declaration* (`anthropic_api_key: str | None = None`) or a
  placeholder in `.env.example`/`docker-compose.yml`
  (`${BELLWETHER_ANTHROPIC_API_KEY:-}`). No real key value anywhere.
- **Stray files — confirmed, but only in the second (non-source-of-truth)
  copy**: `__init__.py.bak`, committed `__pycache__/`, and a committed
  `.bellwether_store.json` all present in `2026-07-10/aik/.../bellwether-
  engine-main`. The Downloads source-of-truth copy has none of these — its
  own `.gitignore` correctly excludes `__pycache__/`, `.env`, and
  `.bellwether_store.json`. Vendoring (Stage 1) should copy from Downloads,
  not the second location, exactly as the master command already specified.

---

## 4.6 Where this lands

**(A) Macro-conditioning looks viable — for a narrow, real slice, not all 15
agents at once.** The mechanism (§4.3) is not a research question, it's a
day-or-two engineering task reusing three files that already exist
(`macro_data.py`, `rule_dsl.py`'s column-passthrough behavior,
`macro_risk_on.py`'s precedent). The data is the actual constraint: **2 of 15
agents (`monetary_policy` fully, the funding-rate half of `onchain`/
`derivatives_etf`) are real and free today; 1 more (`liquidity`'s VIX half)
is free and easy; the rest are paid, unresearched, or not independent
feeds at all.**

Priority order for Stage 2:
1. `monetary_policy` (real_yield_10y, dxy) — already built, zero new data
   work, just wiring `MonetaryPolicyAgent` to call `macro_data.py` instead of
   `MockMarketData`.
2. VIX for `liquidity` — one new yfinance call, same pattern as the existing
   SILVER/PLATINUM futures fallback.
3. BTC perp funding rate for `onchain`/`derivatives_etf` — already built
   (`funding_data.py`), same "just wire it" cost as #1.
4. Everything else in the opportunity map — paid, unresearched, or (ETF
   flows) confirmed blocked; not worth pursuing in this engagement without a
   new decision from you.

On the frequency question (§4.3): the honest answer is that macro
conditioning will only produce VIABLE-or-better hypotheses for (a) base
rules with real frequency headroom above the 30/yr floor, and (b)
macro fields shaped as regime tilts (true a majority of the time) rather
than narrow gates — recommended above, not a hedge.

**What I'm confident about**: the DSL mechanism (§4.3), the real-vs-mock
status of every agent's inputs (§4.2, each claim traced to a specific file),
the LLM/web-search finding (§4.4, a real code-level surprise, not inferred),
and the frequency arithmetic (§4.3, computed from this repo's own real
gate constants).

**What would change my mind**: if VIX or the on-chain metrics turn out to
have a free source I didn't find in this pass (I did not do a deep web
search for on-chain/stablecoin-supply free APIs — flagged as "unresearched"
above rather than "blocked," a genuinely open question), the opportunity map
in §4.2 would shift meaningfully — worth a dedicated follow-up search before
Stage 2 commits to a final wiring list.

**Decision needed from you**: proceed to Stage 1 (vendor Bellwether into
`vatican/bellwether/`) and Stage 2 priority-1/2/3 above, or do you want the
on-chain/stablecoin free-source research done first so the opportunity map
is complete before any code moves?
