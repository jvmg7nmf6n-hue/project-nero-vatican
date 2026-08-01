# TIMEFRAME_PERIODS_PER_YEAR — Asset-Class-Aware Redesign: Investigation & Closing Report

Branch: `feature/timeframe-periods-asset-aware`. Isolated from `main` and from
every other in-flight branch. Not merged to `main`.

## Background

A prior branch added `TIMEFRAME_PERIODS_PER_YEAR["4h"] = 1560` (forex-specific,
~24/5-week math) in the same window `feature/candle-data-gaps` landed 4h candle
exports for several non-forex assets (BTC, BNB, GOLD, SILVER, session-based
stocks). Because the table was keyed by bare timeframe string with no
asset-class awareness, that forex-sized constant would have been silently
applied to every non-forex 4h asset — turning an honest null Sharpe/volatility
into a fabricated-looking wrong number. That collision was averted by
excluding `"4h"` entirely as a stopgap (2026-07-31 cross-branch review). This
branch replaces the stopgap with a permanent, structural fix.

## Task 1 — Investigation findings

### Current dict, call sites, null-handling (verified, not assumed)

`TIMEFRAME_PERIODS_PER_YEAR` lived in `nero_core/quant/quant_panel.py`,
originally `dict[str, int]` keyed only by timeframe:
`{"12h": 730, "24h": 365, "1day": 252, "1week": 52}` — `"4h"` already absent.

**Exactly one production call site anywhere in the repo:**
`nero_core/execution/export_quant_metrics.py`'s `_metrics_for_file`, via
`periods_per_year_for_timeframe(timeframe)`. `asset` was already in scope at
that call site but was never passed through — the bare-string table had no use
for it. The only other caller, `tools/quant_panel_cross_validation.py`, is a
test-support cross-validation script (empyrical-reloaded reference check), not
production.

Verified (by reading every function body, not assumed) that every consumer
degrades honestly on `None`: `annualized_log_return`, `realized_volatility`,
`sharpe_ratio`, `sortino_ratio` (all in `quant_panel.py`) each start with
`if periods_per_year is None: return None`. `_metrics_for_file` prints a NOTE
and still writes the record with the field set to `null` — never raises, never
drops the entry.

**`quant_cross_asset.json` does not consume this table at all.**
`nero_core/execution/export_quant_cross_asset.py` uses
`nero_core.quant.cross_asset.volatility_regimes`, a completely separate
module with no import path to `quant_panel.py` or `export_quant_metrics.py`.
`volatility_regimes` accepts a `periods_per_year_map` parameter but its own
docstring says it's genuinely unused (correlation needs no annualization
factor), and the one caller never passes one. Confirmed via static import
analysis: `cross_asset.py` imports only `market_data`/`quant_intelligence`;
`export_quant_cross_asset.py` imports only `cross_asset.py`. The Task 3
byte-identical check for this file is therefore guaranteed by construction,
not just empirically observed.

### Existing asset-class mechanism, reused exactly

`nero_core/execution/export_candle_data.py`'s `CandlePair.fetch_family: str`
(`"crypto_metals" | "forex" | "stock"`), used to dispatch which fetch function
`IN_SCOPE_PAIRS` (~33 entries, derived from the live `strategies.json` roster)
routes through. Reused directly (`_ASSET_TO_FETCH_FAMILY` in
`export_quant_metrics.py`, built from `IN_SCOPE_PAIRS`) rather than
reinvented.

**Caveat found, not assumed:** `fetch_family` is a *fetch-routing* label, not
a *trading-calendar* label. It lumps GOLD and SILVER together under
`"crypto_metals"`, but they do not share a trading calendar — see below.

### Per-(asset_class, timeframe) derivations, verified against real exported candle data

Every number below was checked against actual `time` fields in
`docs/site_data/candles/*.json` (candles/span, weekday distribution, and for
the forex/commodity case, actual O/H/L/C on weekend candles) — not derived
from the textbook formula alone.

| Asset class | Timeframe | Value | Derivation |
|---|---|---|---|
| crypto | 12h | 730 | 2 candles/day × 365 (24/7 market). Unchanged. |
| crypto | 24h | 365 | 1 candle/day × 365 (24/7 market). Unchanged. |
| crypto | 4h | **2190** | 6 candles/day × 365. Empirically confirmed: `BTC_4h.json` measures 6.03 candles/day, all 7 weekdays present evenly. NEW (was excluded). |
| forex | 1day | 252 | **UNCHANGED VALUE**, kept as-is (see Backlog below — this is likely wrong for what's actually live, but out of scope for this branch). |
| forex | 1week | 52 | 1 candle/week × 52. Asset-class-independent. Unchanged. |
| forex | 4h | **2190** | NOT the conventional 24/5-week formula (120h/week ÷ 4h × 52 = 1560). MEASURED: `EURUSD_4h.json`/`GOLD_4h.json` both measure 6.03 candles/day, every day of the week including weekends, at near-weekday density, with real (non-flat) O/H/L/C movement on Saturday/Sunday candles — statistically indistinguishable from `BTC_4h.json`'s own 6.03/day. This data provider does not appear to honor a hard weekend close for this asset/timeframe. Approved 2026-08-01 to use the measured value over the textbook one. NEW. |
| stock | 1day | 252 | Trading days only. Empirically confirmed: `AAPL_1day.json` measures 251.7 implied candles/365 days. Unchanged. |
| stock | 4h | **252** | NOT "6.5h RTH ÷ 4h ≈ 1.6 candles/day". Verified against `nero_core.data_sources.stock_data.resample_1h_to_4h_market_hours_aware` and `docs/stock_data_calibration_audit.md`: a 6.5h RTH session produces exactly 7 hourly candles → exactly ONE complete 4h bar/session (trailing ~2.5h/3-candle remainder dropped, never fabricated). Confirmed empirically: `AAPL_4h.json` has exactly 1 candle per trading day. So stock 4h and stock 1day share the identical real cadence. NEW. |
| commodity_spot (GOLD) | 24h | 365 | GOLD's Twelve Data spot XAU/USD trades near-continuously — `GOLD_24h.json` measures 366.8 implied candles/365 days, statistically indistinguishable from `BTC_24h.json`'s own. Was already using the old shared `"24h"` entry; now explicitly keyed as its own class. |
| commodity_spot (GOLD) | 4h | **2190** | Same measured continuous cadence as forex 4h — see above. NEW. |
| commodity_spot (GOLD) | 1week | 52 | Universal weekly constant. Unchanged. No `1day` export exists for GOLD (its daily-equivalent export uses the `24h` cadence key). |
| commodity_futures (SILVER) | *any* | **None** | See below — deliberately unset. |

### Why GOLD and SILVER cannot share one "commodity" class

Verified empirically: `SILVER_24h.json` measures 251.7 implied candles/365
days, with **zero Saturday candles and minimal Sunday** — a 5-day trading week
pattern, not GOLD's near-continuous one. Traced to the data source: SILVER's
Twelve Data endpoint 404s on this project's current plan (see
`market_data.py`'s own comment) and falls back to yfinance's `SI=F` — a COMEX
**futures** contract, a different instrument on a different exchange-session
schedule than GOLD's spot feed. A shared "commodity" bucket would have
reintroduced exactly the class of bug this whole table exists to prevent, one
level up.

**Decision (approved 2026-08-01): `commodity_futures` (SILVER) returns `None`
for every timeframe.** SILVER's real CME Globex trading-hours schedule has not
been independently verified against a primary source, so no number is
fabricated from an unconfirmed assumption. Filed as backlog (see below), out
of scope here.

## Task 2 — Redesign

`nero_core/quant/quant_panel.py`:
- `TIMEFRAME_PERIODS_PER_YEAR` is now `dict[tuple[str, str], int]`, keyed by
  `(asset_class, timeframe)`. Five asset-class constants: `CRYPTO`, `FOREX`,
  `STOCK`, `COMMODITY_SPOT`, `COMMODITY_FUTURES`.
- `periods_per_year_for_timeframe(asset_class: str | None, timeframe: str) -> int | None`
  — returns `None` for `asset_class=None`, or any combination not explicitly
  in the table. Never guesses, never falls back to another combination's
  constant.
- Every previously-correct value is unchanged (proven with `assertEqual`
  against the old hardcoded literal, not just re-reading the new table —
  `tests/test_quant_panel.py::PeriodsPerYearLookupTest`).

`nero_core/execution/export_quant_metrics.py`:
- New `classify_asset_class(asset: str) -> str | None`, built from
  `IN_SCOPE_PAIRS` (imported from `export_candle_data.py`, not reinvented)
  plus an explicit `{"GOLD": COMMODITY_SPOT, "SILVER": COMMODITY_FUTURES}`
  override sitting on top of `fetch_family`.
- `_metrics_for_file`'s one call site now computes `asset_class` and passes it
  through — the only change to that call site, confirmed a small, contained
  edit (see Task 3).
- **Output JSON schema is unchanged** — `asset_class` is used internally as a
  lookup key and discarded; no new field was added to
  `docs/site_data/quant_metrics.json`'s entry shape, so the byte-identical
  check isn't defeated by a schema addition.

`tools/quant_panel_cross_validation.py`: updated its one call site to
`periods_per_year_for_timeframe(classify_asset_class(asset), timeframe)`,
reusing the same classification function (not a second one). Smoke-tested
directly (`python -m tools.quant_panel_cross_validation`) — still
cross-validates GOLD/1week and EUR/USD/1week against `empyrical-reloaded`
with `rel_diff=0.000000` on vol/sharpe/sortino.

## Task 3 — Migration safety

**Call-site sweep:** grepped the whole repo for `periods_per_year_for_timeframe`
and `TIMEFRAME_PERIODS_PER_YEAR` — exactly two call sites exist
(`export_quant_metrics.py`, `quant_panel_cross_validation.py`), both updated,
confirmed by re-grep after the edit that no third site was missed. The
call-site change in `export_quant_metrics.py` is exactly what was flagged as
needing confirmation: **a small, contained change to one function
(`_metrics_for_file`)** — two new lines (`classify_asset_class` call +
threading its result through), no wider ripple. `classify_asset_class` itself
is new code, not a modification of anything that already worked.

**Regenerated `quant_metrics.json` against the real `docs/site_data/candles/`
directory, before vs. after, with `now`/risk-free-rate held fixed for a fair
diff** (`git stash` to get the pre-Task-2 code, run, restore, run again,
diff):

- **Every existing non-4h `(asset, timeframe)` entry is byte-identical**,
  except:
- **`SILVER/1week` and `SILVER/24h` changed from a real number to `null`.**
  This is not a regression — it's the direct, explicitly-approved consequence
  of the `commodity_futures` decision (`"return None for all timeframes"`,
  not just the newly-added `4h`). Before this branch, the old flat table
  applied `"1week": 52`/`"24h": 365` to SILVER too, with no asset-class
  awareness to stop it — producing a real but (per this investigation)
  unverified, likely-wrong Sharpe/vol for a COMEX futures contract on a
  different calendar than the constant assumed. Captured as a permanent
  regression test (`NonFourHourRegressionTest`), not just a one-off manual
  diff, so this exact split (byte-identical everywhere else, deliberately not
  for SILVER) is enforced going forward.
- Every new `4h` entry transitions from `null` to a real number
  (`crypto`/`forex`/`commodity_spot` → 2190, `stock` → 252), confirmed via the
  same before/after diff and a dedicated test (`FourHourTransitionTest`).

**`quant_cross_asset.json`:** confirmed unaffected by static import analysis
(see Task 1) — no code path from this table to that export exists, so
byte-identical output is guaranteed by construction, not merely observed.

**Downstream consumers of a 4h transitioning from null to real:** the only
consumer of `quant_metrics.json`'s `periods_per_year`/`sharpe`/`sortino`/etc.
fields is the frontend reading the exported JSON directly — no Python code in
this repo branches on whether a specific field is `null` vs. a number (every
consumer of `quant_panel.py`'s functions already had to handle `None` as a
first-class case, since almost every OTHER combination already returns it
today). No code was found, anywhere, that assumes "4h is always null" as an
invariant to rely on.

## Critical safety rule — confirmed

This branch touches **only** annualization math for metrics display/research
(`nero_core/quant/quant_panel.py`, `nero_core/execution/export_quant_metrics.py`,
`tools/quant_panel_cross_validation.py`, and their tests). It does not import,
reference, or modify `nero_core.execution.live_scheduler`,
`nero_core.strategies.registry`, any strategy's entry/exit logic, or any live
scheduler config. Nothing downstream of this change affects a currently-live
strategy's behavior — verified by the call-site sweep above (there are only
two call sites in the entire repo, and neither is anywhere near live trading
logic).

## What's covered now

| Asset class | Timeframes with a real value | Timeframes intentionally still `None` |
|---|---|---|
| crypto | 12h (730), 24h (365), 4h (2190) | 1day, 1week — no crypto export exists at either |
| forex | 1day (252, unchanged), 1week (52), 4h (2190) | 12h, 24h — no forex export exists at either |
| stock | 1day (252), 4h (252) | 12h, 24h, 1week — no stock export exists at any |
| commodity_spot (GOLD) | 24h (365), 4h (2190), 1week (52) | 1day — GOLD's daily-equivalent export uses the "24h" cadence key, not "1day" |
| commodity_futures (SILVER) | *(none)* | **every** timeframe — real CME Globex schedule not yet verified |
| *(unclassified asset)* | *(none)* | any asset not on the live `IN_SCOPE_PAIRS` roster (e.g. ETH) |

## Confirmed

- Zero output changes for existing non-4h timeframes, **except** the one
  explicitly-approved SILVER 1week/24h → null change (see Task 3).
- The averted-bug regression test passes: `BTC`'s (and every other non-forex
  asset's) 4h annualization now resolves to its own asset-specific constant,
  never forex's old `1560`, structurally — proven both at the lookup-function
  level (`test_quant_panel.py`) and at the full-export level
  (`test_export_quant_metrics.py`).
- Zero changes to live trading logic, entry/exit rules, or the live
  scheduler.

## Backlog (explicitly out of scope for this branch)

1. **Verify CME Globex silver trading hours, then add `commodity_futures`
   periods/year constants.** Filed per 2026-08-01 decision — do not fabricate
   from an unverified assumption.
2. **Forex/`commodity_spot` `"1day"` annualization constant (252) may not
   match this data provider's actual continuous-quoting behavior.**
   `EURUSD_1day.json`/`USDJPY_1day.json` measure ~366.8 implied candles/365
   days (Twelve Data serves a `"1day"` candle on every calendar day, weekends
   included, with real non-flat movement, not a forward-filled placeholder) —
   252 (a trading-days-only convention) does not match that empirically.
   **This value is already live on the site today** (EURUSD_1day/USDJPY_1day
   Sharpe/vol) — changing it needs its own dedicated investigation and
   before/after impact review (which live pages/strategies depend on the
   displayed value, how the numbers would shift), not a side effect of a
   different branch. Deliberately not touched here.
