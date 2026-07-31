# Philosophy Hypotheses — Backlog (feature/philosophy-hypotheses-dsl-check)

Two backlog items filed from this branch's investigation. Neither is built here —
this document exists so the scope isn't lost between sessions, not as a promise
either will be picked up next.

## Backlog Item 1 — VOLATILITY_CONTRACTION_RANGE_HOLD (Candidate 1), parked

Entry: 14-day ATR at or below the 20th percentile of its own trailing 252-day
distribution. Exit: price stays inside (or breaks) the range established AT
entry over the next 15 days. No direction, no profit target — this hypothesis
tests range-persistence itself, not a trade.

Three components needed before this can be built, none done here:

1. **New indicator: `atr_percentile_252`.** `rule_dsl.ALLOWED_FIELDS`/`Condition`
   already support a plain threshold comparison (`lte 20.0`) once a precomputed
   column exists — the DSL grammar is not the blocker. `compute_indicator_frame`
   needs a new rolling-percentile-rank column over atr14's own trailing 252-row
   window. Blocked on Backlog Item 2 below: a 252-row lookback cannot produce a
   single non-NaN value against the current 200-row candle exports, on any
   asset, on any timeframe (CONFIRMED — see Item 2).
2. **New ExitPlan shape: entry-frozen range.** `dynamic_target_condition`
   re-evaluates against the frame's CURRENT-row value every candle (a target
   that MOVES with the market); this hypothesis needs the opposite — a
   high/low boundary computed ONCE at entry (the trailing 15-day range as of
   that candle) and compared against every subsequent candle until it's
   breached or 15 days pass. Neither existing target shape, nor the ATR/
   percentage stop shapes (this hypothesis has no ATR-based or percentage-based
   stop concept at all), fit. Needs a new field, e.g.
   `entry_range_lookback_days`, plus the sizing/exit-evaluation logic to go
   with it.
3. **New evaluation approach: binomial hit-rate, not bootstrap-mean-R.**
   `run_backtest`/`classify_verdict`/`bootstrap_mean_r_ci` are all
   expectancy/R-multiple-shaped (`MIN_SAMPLE_SIZE=20` trades/half, positive
   expectancy on both halves). This hypothesis has no direction and no P&L —
   forcing it through the existing harness means fabricating a direction and a
   stop/target that don't correspond to what's actually being measured ("what
   % of low-vol periods stayed in range"). Needs its own small evaluation
   function (hit-rate + a binomial confidence interval), separate from
   `bootstrap_mean_r_ci`, not a bent version of it.

**Recommendation (unchanged from the original investigation):** treat this as
its own small research-agent extension later, sized and scoped on its own —
not squeezed into the existing entry-rule/ExitPlan/bootstrap-mean-R pipeline
piece by piece.

## Backlog Item 2 — the 200-row `CANDLE_COUNT` export cap

`nero_core/execution/export_candle_data.py:79` — `CANDLE_COUNT = 200`, applied
via `.tail(CANDLE_COUNT)` at export time (line 295). Verified directly: every
current export (BTC/EURUSD/GOLD/SILVER/BNB, both 4h and 24h) is exactly 200
rows. `nero_core/research_agent/pipeline.py`'s `default_candles_provider`
(the real candle source `auto_tester.test_hypothesis` runs against, via
`nero_core.research_agent.pipeline`) reads these same exported JSON files —
there is no separate, fuller-history data path for hypothesis testing today.

**Is this deliberate or arbitrary?** Deliberate for its ORIGINAL purpose,
arbitrary/incidental for its current second use as the research-agent's candle
source — these are two different questions with two different answers:

- The candle-export pipeline's own docstring frames it plainly as "Day 1 of
  the candlestick-chart arc... foundation for Day 2's candlestick charts" —
  200 was chosen as a reasonable amount of history for a chart display, not
  derived from any backtesting/indicator-lookback analysis. The Day 1 closing
  report (`docs/candle_export_day1_closing_report.md:120`) confirms 200 was
  simply "the full requested count" for that feature.
- This codebase's own quant code has already run into this mismatch once, and
  documented it explicitly rather than silently working around it:
  `nero_core/quant/quant_panel.py`'s module docstring states outright — "Day
  1's candle export currently produces ~200 candles per asset, not the 252 a
  'one trading year' convention would assume" — and every windowed function in
  that module was deliberately built to take its window as a caller-supplied
  integer and independently re-clamp to whatever's actually available, rather
  than assume 200 (or 252) is enough. `default_candles_provider`/`auto_tester`
  have no equivalent clamping or awareness today — a hypothesis simply gets
  however many rows the export file happens to contain, silently.

**Urgency.** This already blocks Candidate 1 outright (252-row lookback vs.
200-row cap, on any asset/timeframe). It will block ANY future hypothesis
needing more than ~200 periods of lookback — a 252-day percentile or
volatility-regime indicator, a 200-day moving average with any warmup margin,
a multi-year seasonal/regime study. Given quant_panel.py already had to design
around this exact number once, this isn't a hypothetical future problem — it's
a recurring one. Recommend treating "raise (or make configurable) the
research-agent's candle-history depth, independent of the chart-display
export's own 200-row default" as its own small, explicit follow-up — not
silently bumping `CANDLE_COUNT` globally, since that constant also drives
chart-display file size/load time for Day 2's UI, a genuinely different
constraint than research-agent lookback depth.
