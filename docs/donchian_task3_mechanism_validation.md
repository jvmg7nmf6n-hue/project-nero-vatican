# Donchian Cross-Asset Deep-Dive, Task 3 — Mechanism Validation

Question: does DONCHIAN's precise N-period-high/low breakout **timing** add value,
or is the edge coming from merely being **near** a price extreme?

`tools/backtest_donchian_mechanism_validation.py` re-ran 5 of Task 2's standout
configs (the raw SURVIVED result, plus the next tier of adequate-sample/train-CI-
clear results sharing GOLD's N20 or representing another strong N) against a
stricter random-entry baseline: `near_breakout_mask` draws only from candles
within 2% of the N-period high or low — the same "near an extreme" pool DONCHIAN's
own breakout sits inside, but without requiring the exact breach. If the real
strategy's edge collapses against this stricter pool, precise timing adds nothing
over proximity. If the edge survives, timing is doing genuine work.

## Results

| Config | Real (N, ExpR) | Standard-pool edge | Near-breakout-pool edge | Verdict |
|---|---|---|---|---|
| GOLD / 1week / N20 | 185, +0.450 | +0.189 | **+0.066** | **TIMING-CONFIRMED** |
| GOLD / 1week / N10 | 259, +0.234 | +0.041 | **-0.023** | **PROXIMITY-ONLY** |
| EUR/USD / 1week / N20 | 111, +0.379 | +0.177 | **+0.126** | **TIMING-CONFIRMED** |
| GBP/USD / 1week / N20 | 160, +0.383 | +0.261 | **+0.146** | **TIMING-CONFIRMED** |
| USD/JPY / 1week / N40 | 113, +0.414 | +0.176 | **+0.116** | **TIMING-CONFIRMED** |

(Full-series analysis, not train/test — this is a mechanism diagnostic on the
already-established pattern, not a second generalization test.)

## Mechanism verdict: predominantly TIMING-CONFIRMED, with one real exception

**4 of 5 configs — including GOLD/1week/N20, the raw SURVIVED result — keep a
clearly positive edge even against the stricter near-breakout pool.** For these,
DONCHIAN's precise high/low breach is not just a proxy for "somewhere near an
extreme" — the exact moment of breakout carries real, additional information the
near-miss candles around it don't.

**GOLD/1week/N10 is the one exception, and it's worth taking seriously rather than
averaging away**: its near-breakout-pool edge is slightly **negative** (-0.023) —
meaning random entries anywhere within 2% of a 10-week extreme did marginally
**better** than DONCHIAN's own precise breakout requirement. On the SAME asset
(GOLD), the classic N20 parameter shows genuine timing value while the faster N10
parameter's edge appears to be almost entirely proximity-driven. This is a
meaningful, N-specific finding: **N20's edge is not merely "GOLD is a trending
asset that any near-extreme entry would catch" — it is specifically the breakout
CONFIRMATION that matters at that horizon.** N10's edge looks more like "GOLD
tends to keep moving once it's near any recent extreme," which a much simpler
(and cheaper-to-trigger) near-extreme rule would capture just as well.

## Implication for Vatican's methodology positioning

- **DONCHIAN_TREND's N20 configuration should be described as a genuine
  breakout-confirmation strategy** — the mechanism validation directly supports
  the "wait for the actual breach" design choice, not just a "near-trend" filter.
- **N10 should NOT be described the same way.** If N10 configs are ever promoted,
  the honest framing is "captures upside near recent extremes," not "profits from
  precise breakout timing" — the data does not support the stronger claim for this
  specific N/asset combination.
- This is exactly the kind of distinction a methodology page should make
  explicit rather than blend into one "DONCHIAN_TREND works" claim — the same
  strategy family can derive its edge from different mechanisms at different
  parameterizations, and only measuring both isolates which is which.
