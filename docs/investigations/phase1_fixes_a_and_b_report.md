# Phase 1 Fixes A & B — Closing Report

**Branch:** `feature/phase1-fixes-a-and-b`, branched fresh from `origin/main`
at **`a5b234b`** (confirmed via `git log -1` immediately after branching —
not from `feature/investigation-phase1-infra-audit`, which remains
untouched and independent). Not merged, not pushed.

**ROLE NOTE (per this session's own instruction):** this branch was
authored by CC-1 as a one-off substitution for CC-2, same as the
investigation branch before it. Unlike that branch, **this one DOES modify
existing production files** (`nero_core/execution/export_site_data.py`,
`nero_core/quant/quant_panel.py`, `website/lib/*.ts`) — a human should
independently re-review the full diff before merge, not rely on this
summary alone. Review command:

```
git diff origin/main..feature/phase1-fixes-a-and-b
```

## Fix A — PEAD open-position display asymmetry

**What changed:** a trailing ENTRY row excluded from the confirmed-clean
subset solely by `exclude_unrecorded_source` (not quarantined, not a
mismatched-source pair) previously collapsed silently to
`open_position: None` with zero explanation — identical to "no signal has
ever fired," which is what MSFT/TSLA/META's live PEAD entries show today.

- `nero_core/execution/export_site_data.py`: new `unverified_open_entries`
  field (0 or 1) on every `stats.json` strategy entry. Derived from the
  previously-discarded raw trailing open entry, checked against
  `is_quarantined(...)` and `data_source is None` — a lone open entry can
  never fail `exclude_mismatched_sources` (no paired exit to disagree
  with), so this fully characterizes "unrecorded-source-only" exclusion
  without reimplementing quarantine logic.
- `website/lib/statLine.ts`: new branch renders `"N entry/entries pending
  source verification"`, checked after the existing `unverified_trades`
  branch (a config with both a past unverified round trip and a current
  unverified open entry still leads with the resolved-trade message).
- `website/lib/chartDescription.ts`: same message replaces the actively
  misleading `"No completed trades yet — strategy is live and monitoring
  for setups"` on the strategy detail page for this specific case.
- `website/lib/types.ts`: `unverified_open_entries?: number` added,
  optional (older cached exports predate it), same convention as the
  existing `unverified_trades?: number`.

**New test coverage, red-then-green:**
- Backend: 3 new tests in `tests/test_export_site_data.py`
  (`QuarantineAwareStatsTest`) — confirmed `KeyError` before the fix,
  passing after.
- Frontend: 3 new tests in `website/__tests__/statLine.test.ts`, 1 new
  test in `website/__tests__/chartDescription.test.ts` — confirmed wrong
  output (`"awaiting first signal"` / `"No completed trades yet..."`)
  before the fix, correct message after.

**Verification method:** ran `write_site_data` against the real, live
`data/truth_ledger.db` with `output_dir` pointed at a scratch temp
directory (never `docs/site_data/`, per safety rail #3). Confirmed real
data: MSFT and TSLA and META (both `surprise3pct`/`surprise8pct` configs)
now show `unverified_open_entries: 1`; GOOGL unaffected (still
`unverified_trades: 1`, its own separate resolved-quarantine case); AAPL/
AMZN unaffected (`unverified_open_entries: 0`, genuinely clean open
positions).

**Discrepancy found and flagged, per safety rail #6 (not silently worked
around):** `chartDescription.ts`'s `statusLine` had **no** existing
"pending source verification" handling for the resolved-but-quarantined
case either (e.g. GOOGL) before this branch — it said `"No completed
trades yet"` regardless of `unverified_trades`. The investigation's Fix A
sketch assumed this honesty pattern "already used for the resolved-trade
case" existed in both `statLine.ts` and `chartDescription.ts`; it only
existed in the former. **This branch fixes only the open-entry case this
task asked for** — GOOGL's own resolved-but-quarantined case still shows
`"No completed trades yet"` on its strategy detail page, unchanged from
before this branch. That sibling gap in `chartDescription.ts` is real but
was not requested here and remains unfixed — flagged for a human decision
on a future branch, not expanded into silently.

## Fix B — Forex annualization

**B1. Value decision (1day):** used **365**, not the raw empirical 366.83.
Reason: every other continuously-quoted asset class in
`TIMEFRAME_PERIODS_PER_YEAR` already uses the clean, round 365 (CRYPTO/
COMMODITY_SPOT `24h`) rather than its own individually-measured raw sample
value — no reason found in this codebase to break that established
convention for FOREX specifically.

**B2. Hardcoded-value check:** grepped the full test suite (Python and
website) for any `FOREX`/`1day` == 252 assertion. Found two, both updated
in the same commit as the value change:
- `tests/test_quant_panel.py`: `test_forex_1day_unchanged` (asserted
  `OLD_VALUE = 252`) replaced with `test_forex_1day_corrected_from_252_to_365`.
- `tests/test_export_quant_metrics.py`: `NonFourHourRegressionTest`'s
  `EXISTING_NON_4H_COMBOS` list included `("EUR/USD","1day",252)` /
  `("USD/JPY","1day",252)` among combos asserted byte-identical to their
  pre-migration value — removed from that list, given their own dedicated
  test (`test_eurusd_and_usdjpy_1day_deliberately_change_from_252_to_365`),
  mirroring the existing SILVER-deliberately-changes-to-null test's own
  pattern. No hardcoded reference found anywhere in the website test suite.

**B3. GBP/USD 1week check (new scope, not covered by the investigation):**
pulled real `GBPUSD_1week.json` candle timestamps — all 200 candles fall
on Monday, 52.40 implied candles/year, zero flat-OHLC candles. **Confirmed
fine as-is** — matches the existing universal `"1week": 52` convention
already used everywhere in the table. No fix needed; no third commit.

**B4. Before/after numbers** (rf_annual=0.045, window_used=199 held fixed
for a controlled comparison, matching the investigation's own methodology;
separately confirmed the live `export_quant_metrics` pipeline end-to-end
via a scratch export resolves `periods_per_year` to 365 for both assets):

| Asset | Metric | Before (252) | After (365) |
|---|---|---|---|
| EUR/USD | `log_return_annualized` | −0.011763 | −0.017038 |
| EUR/USD | `realized_vol_annualized` | 5.0378 | 6.0630 |
| EUR/USD | `sharpe` | −1.1267 | −1.0232 |
| EUR/USD | `sortino` | −1.5588 | −1.4350 |
| USD/JPY | `log_return_annualized` | −0.006795 | −0.009842 |
| USD/JPY | `realized_vol_annualized` | 6.8670 | 8.2644 |
| USD/JPY | `sharpe` | −0.7543 | −0.6636 |
| USD/JPY | `sortino` | −0.8775 | −0.7761 |

No sign flips for either asset. Realized volatility grows ~20% for both;
Sharpe/Sortino move toward zero (less negative) for both.

## Full verification

- **Python suite:** `python -m unittest discover` → **2027 tests, 0
  failures** (before: main's 2023-test baseline; after: 2027 — +3 from Fix
  A's new backend tests, +1 from Fix B's new `test_export_quant_metrics.py`
  test; `test_quant_panel.py`'s change was a rename/rewrite of an existing
  test, net 0 new). Unlike the investigation branch, **every test here is
  fully green** — no intentional failures.
- **No-auto-wire suite:** `tests/test_research_agent_no_auto_wire.py` →
  3/3 passing, unchanged.
- **Website suite:** `npx jest` → **48 suites / 539 tests, 0 failures**
  (before: 535 per this session's earlier work; after: 539 — +3 from
  `statLine.test.ts`, +1 from `chartDescription.test.ts`).
- **No `live_scheduler`/`default_registry` references** anywhere in this
  branch's diff — confirmed via `git diff origin/main..HEAD | grep`, zero
  hits.

## Commit list (each independently revertable, per safety rail #7)

```
efebf2e  Fix B (1day): correct forex TIMEFRAME_PERIODS_PER_YEAR from 252 to 365
9ce39f4  Fix A: honest "pending source verification" message for unverified open entries
```

(No third commit for a B3/1week fix — B3 confirmed the existing value is
already correct, nothing to change.)

## Status

Ready for human review and merge decision. **Not pushed, not merged.**
`feature/investigation-phase1-infra-audit`'s remaining findings (Phase C —
CME Silver hours, Phase D — repair_forward_tracker EXIT idempotency, Phase
E — mirror_condition eq boundary) are **not touched by this branch** and
remain pending separate review, as instructed.
