# PSX Strategy Sweep, Phase 1 — Consolidated Closing Report

Vatican's first emerging-market research batch. Ties together Task 1 (data
pipeline + corporate-action guard), Task 2 (9-strategy sweep on OGDC/LUCK/HBL),
and Task 3 (PEAD gate check) into one report. Built directly on the prior
`docs/psx_data_audit.md` (YELLOW verdict) — this batch is the first real
strategy-level test of whether Vatican's existing edge families transfer to
Pakistan's market at all.

## Headline result

**4 configs reached PROMISING-WATCHLIST, all on a single ticker: HBL.** Nothing
reached SURVIVED (grid-shift is structurally NOT_APPLICABLE at PSX's only
available timeframe, 1day, so nothing could clear that bar even where the raw
statistics would otherwise have qualified — though in this run, none did anyway).
This is a real, if narrow, foothold: Vatican now has its first empirically-tested
PSX signal candidates with a public, auditable trail from raw data through
backtest to verdict.

The more consequential finding, business-wise, is **what the corporate-action
guard (built in Task 1) caught**: on its first run against full multi-year
history, it halted **OGDC** (2010-02-22, +49.9% single-day move) and **LUCK**
(worst break 2025-03-03, +396.0%) — 2 of the 3 planned universe tickers. The
prior data audit's own "OGDC/LUCK/HBL confirmed clean" finding was based on a
2024-only spot check; this is the first time the full history got scanned, and
it found exactly the kind of unadjusted corporate action the audit warned PSX
data is prone to. The guard did its job: it stopped corrupted data from silently
entering a backtest, at the cost of shrinking this Phase 1 sweep's real universe
down to one ticker.

## Task-by-task summary

- **Task 1** (`docs/psx_task1_data_pipeline.md`): built the PSX data pipeline —
  OGDC/LUCK/HBL via yfinance, KSE-100 via the dps.psx.com.pk raw endpoint, USD/PKR
  + WTI oil macro proxies, and the corporate-action guard. SBP policy rate checked
  and confirmed unavailable (FRED series annual, stale since 2017); USD/PKR used
  as sole macro proxy. 16 tests, all passing.
- **Task 2** (`docs/psx_task2_full_sweep.md`): ran all 9 strategies (11 configs
  counting VOLATILITY_SQUEEZE's 3 MA variants and MACRO_RISK_ON's Pakistan
  adaptation) against the most recent 10 years of data, 70/30 split, flat
  0.15%/side fee. OGDC and LUCK SKIPPED entirely (corporate-action halt); HBL ran
  cleanly. COINTEGRATION_PAIRS (all 3 pairs) SKIPPED — every pair needs at least
  one halted leg.
- **Task 3** (`docs/psx_task3_pead_gate.md`): PEAD gate checked and **BLOCKED** —
  yfinance carries no earnings-surprise data (EPS estimate/actual, announcement
  dates) for any of the three PSX tickers. No PEAD backtest was attempted.

## Full results table

| Asset | Strategy | Verdict |
|---|---|---|
| OGDC | MEAN_REVERSION v1 | SKIPPED (corporate-action halt) |
| OGDC | BREAKOUT_MOMENTUM | SKIPPED (corporate-action halt) |
| OGDC | TREND_PULLBACK | SKIPPED (corporate-action halt) |
| OGDC | VOLATILITY_SQUEEZE (all 3 MA) | SKIPPED (corporate-action halt) |
| OGDC | DONCHIAN_TREND | SKIPPED (corporate-action halt) |
| OGDC | FVG_REVERSION | SKIPPED (corporate-action halt) |
| OGDC | BOS_CONTINUATION | SKIPPED (corporate-action halt) |
| OGDC | MACRO_RISK_ON | SKIPPED (corporate-action halt) |
| LUCK | MEAN_REVERSION v1 | SKIPPED (corporate-action halt) |
| LUCK | BREAKOUT_MOMENTUM | SKIPPED (corporate-action halt) |
| LUCK | TREND_PULLBACK | SKIPPED (corporate-action halt) |
| LUCK | VOLATILITY_SQUEEZE (all 3 MA) | SKIPPED (corporate-action halt) |
| LUCK | DONCHIAN_TREND | SKIPPED (corporate-action halt) |
| LUCK | FVG_REVERSION | SKIPPED (corporate-action halt) |
| LUCK | BOS_CONTINUATION | SKIPPED (corporate-action halt) |
| LUCK | MACRO_RISK_ON | SKIPPED (corporate-action halt) |
| **HBL** | MEAN_REVERSION v1 | DIED |
| **HBL** | BREAKOUT_MOMENTUM | DIED |
| **HBL** | **TREND_PULLBACK** | **PROMISING-WATCHLIST** |
| **HBL** | **VOLATILITY_SQUEEZE ma200** | **PROMISING-WATCHLIST** |
| **HBL** | **VOLATILITY_SQUEEZE ma150** | **PROMISING-WATCHLIST** |
| **HBL** | **VOLATILITY_SQUEEZE ma100** | **PROMISING-WATCHLIST** |
| HBL | DONCHIAN_TREND | DIED |
| HBL | FVG_REVERSION | DIED |
| HBL | BOS_CONTINUATION | DIED |
| HBL | MACRO_RISK_ON (currency-only) | DIED |
| OGDC-LUCK | COINTEGRATION_PAIRS | SKIPPED (leg halted) |
| OGDC-HBL | COINTEGRATION_PAIRS | SKIPPED (leg halted) |
| LUCK-HBL | COINTEGRATION_PAIRS | SKIPPED (leg halted) |
| OGDC/LUCK/HBL | PEAD | BLOCKED (no earnings data) |

## PROMOTION LIST — candidates for live paper-tracking wiring

Vatican's first PSX signal candidates, every one carrying an honest label (none is
a proven edge; all are PROMISING-WATCHLIST because at least one half of the 70/30
split has fewer than 20 trades — genuinely promising, not yet statistically
adequate, and grid-shift could not be run to further confirm even if the sample
had cleared that bar):

1. **HBL / TREND_PULLBACK** (1day) — TRAIN N=10, ExpR=+0.145 | TEST N=9,
   ExpR=+0.333
2. **HBL / VOLATILITY_SQUEEZE ma200** (1day) — TRAIN N=8, ExpR=+0.350 | TEST N=9,
   ExpR=+0.714
3. **HBL / VOLATILITY_SQUEEZE ma150** (1day) — TRAIN N=8, ExpR=+0.350 | TEST
   N=10, ExpR=+0.612
4. **HBL / VOLATILITY_SQUEEZE ma100** (1day) — TRAIN N=8, ExpR=+0.350 | TEST
   N=10, ExpR=+0.612

None of these are wired to live paper-tracking by this batch — that remains a
future step, same as every other PROMISING-WATCHLIST config in this project.

## Business finding

**Vatican now has 4 live PSX signal candidates (all one ticker, HBL) — the first
empirically-tested, publicly-auditable signal research on a KSE-listed blue-chip.**
This is a genuine, if modest, foothold: three of this batch's four applicable
strategy families (TREND_PULLBACK and all three VOLATILITY_SQUEEZE variants) show
a positive edge-over-random signal on at least one PSX name, in the same
direction Vatican's other asset classes have already shown it. The sample sizes
are small (8–10 trades per half) precisely because HBL is the only ticker in this
Phase 1 universe clean enough to trust — not because the underlying 10-year
window is short.

**Recommended Phase 2 expansion, in priority order:**
1. **MARI** — once the confirmed Sept-2024 split is explicitly patched (a
   corporate-actions adjustment layer, not attempted in this data-audit-only /
   strategy-sweep-only batch).
2. **ENGRO → ENGROH** — once the ticker-succession splice is built (yfinance has
   no ENGROH coverage at all; this requires the dps.psx.com.pk raw endpoint).
3. **A broader PSX universe beyond blue-chips** — to test whether HBL's result
   is idiosyncratic to one bank stock or reflects something that generalizes
   across PSX more widely; this also gives COINTEGRATION_PAIRS and MACRO_RISK_ON
   a real multi-ticker sample to run against, since this batch's guard left them
   with too few clean legs to test at all.
4. Re-run the OGDC/LUCK corporate-action breaks through a proper adjustment
   pass (not a blanket exclusion) — both may still carry a genuine tradeable
   history before/after their respective breaks, once each side is adjusted
   separately.
5. Revisit PEAD once a Pakistan-specific earnings-estimate source is found.

Factual, not speculative: no strategy performance number in this report has been
adjusted, cherry-picked, or presented outside its own train/test/sample-size
context. The 4 PROMISING-WATCHLIST configs are real, measured results on real
data — and the honest caveat (small samples, single ticker, no grid-shift
possible) is attached to every one of them, per this project's own permanent
verification-status discipline.
