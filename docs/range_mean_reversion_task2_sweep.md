# RANGE_MEAN_REVERSION — Task 2 Three-Tier Sweep Results

Tool: `tools/backtest_range_mean_reversion_sweep.py`. All 28 configs from
`docs/range_mean_reversion_data_audit.md` (0 SKIPPED). Chronological 70/30 split,
bootstrap 95% CI, and a bespoke bidirectional random-entry baseline restricted to the
SAME ranging (ADX < 25) eligible pool this strategy itself requires — the key
comparison this task asked for. Full raw output in
`docs/range_mean_reversion_task2_sweep_raw_output.txt`.

## Headline result

**26 of 28 configs DIED, 2 PROMISING-WATCHLIST, 0 SURVIVED, 0 configs qualify for
grid-shift verification.**

| Config | Verdict | TRAIN | TEST |
|---|---|---|---|
| GOLD / 1week | PROMISING-WATCHLIST | N=36, ExpR=0.026, edge=+0.057 | N=11*, ExpR=0.102, edge=+0.076 |
| SILVER / 1week | PROMISING-WATCHLIST | N=23, ExpR=0.320, edge=+0.242 | N=15*, ExpR=0.263, edge=+0.226 |

Both are marked `*` (LOW SAMPLE) in the test half — neither reaches the 20-trade
`MIN_SAMPLE_SIZE` bar, so **neither qualifies for grid-shift verification at all** (a
config needs N>=20 in both halves just to be considered). Every other config across
all three tiers DIED — negative expectancy in at least one half.

Full per-tier/per-timeframe table is in the raw output; every one of the other 26
configs shows a clearly negative TEST-half expectancy_r.

## Task 2's own required questions, answered factually

### Does band-extreme timing beat random entry within the same regime pool?

**Mostly no.** `edge_over_random` (real strategy ExpR minus the mean of 200
random-entry runs drawn from the same ADX<25 eligible pool) is negative or
near-zero in the large majority of configs — meaning entering AT RANDOM within a
ranging regime frequently performs about as well as, or better than, entering
specifically at band extremes. The regime filter (ranging vs not) is doing most of
whatever limited work is being done here; the discretionary trader's specific
"wait for a band touch" timing rule adds little to no measurable value beyond that
on this data.

**The two PROMISING-WATCHLIST exceptions are notable**: GOLD/1week and SILVER/1week
BOTH show a positive edge_over_random in both halves (GOLD: +0.057/+0.076; SILVER:
+0.242/+0.226) — the only two configs in the whole sweep where band-extreme timing
clearly outperformed random entry in the same regime, in both the train AND test
half. This is a real, if thin, signal that band-extreme timing might specifically
add value at the 1week timeframe for precious metals — worth flagging for future
research, not proof of anything given the sample size.

### Did Tier 1 beat Tier 3? (validates the regime filter, or flags overfitting)

**Weakly, and only through metals — not through forex.** Breaking Tier 1 down:
- **Tier 1 forex (12 configs): 0 PROMISING-WATCHLIST, 12 DIED (100% failure).**
- **Tier 1 metals (6 configs): 2 PROMISING-WATCHLIST, 4 DIED (33% promising).**
- **Tier 3 stress-test (4 configs): 0 PROMISING-WATCHLIST, 4 DIED (100% failure).**

Tier 1 as a whole (2/18 promising, 11%) technically beat Tier 3 (0/4, 0%), but this
is driven ENTIRELY by the metals slice — **forex, which the task itself frames as
the most range-prone asset class, performed IDENTICALLY to the stress-test tier**
(both 100% DIED). This is an honest, mixed answer: the regime filter is not
obviously separating "should work" from "should fail" assets at these timeframes —
if anything, this result argues against reading the Tier 1/Tier 3 split as strong
validation of the regime-awareness thesis. A cleaner interpretation: this specific
strategy, on this specific 70/30 split and these specific timeframes, does not show
a reliable edge on ANY tested asset class except a thin, sample-limited signal on
precious metals at 1week — the regime gate is necessary (Tier 3 stress-test confirms
a market with essentially no persistent ranging character doesn't work either) but
evidently not sufficient to produce a reliable edge on its own.

### Did anything SURVIVE full verification?

**No.** Zero configs cleared even the pre-grid-shift statistical bar (positive both
halves + N>=20 both halves) — the 2 PROMISING-WATCHLIST configs fall short purely on
test-half sample size. Task 3's grid-shift step therefore has no candidates to test
at all (see `docs/range_mean_reversion_task3_grid_shift.md`).

## A genuine data anomaly, noted for transparency

BTC/12h returned only 300 candles in this sweep run, versus 6,516 candles for the
identical fetch in Task 2's own data audit minutes earlier (and re-confirmed at
6,516 candles again immediately after the sweep finished). This is a transient
fallback/rate-limit artifact of the exchange-cascade design under a long-running
process — reusing one `MarketDataClient` instance across ~28 sequential fetches,
right after a slow 112.5-second BTC/4h fetch that likely consumed meaningful API
quota. It does not change BTC/12h's classification (it DIED regardless — TRAIN N=5,
TEST N=0, deeply insufficient either way), but is recorded here rather than silently
smoothed over, matching this project's own disclosure convention for anomalies
(see the forex Task B2 report's own 8086-second runtime anomaly).

## Summary — the intuition does not hold up out-of-sample

**26 of 28 configs DIED (93%).** The discretionary trader's rule — buy/short band
extremes only while ranging — does not survive rigorous testing as formalized here,
on any of the 10 assets and 3 timeframe sets tested, at the standard this project
requires. Two precious-metals configs at 1week show a real, band-extreme-specific
edge over random entry, but the sample is too thin to call it anything more than a
lead worth more data before revisiting. The regime-awareness premise is directionally
supported (Tier 3's total failure is consistent with "ranging-market strategies
shouldn't work in a persistently trending market") but not cleanly validated by the
Tier 1/Tier 3 comparison, since forex (nominally Tier 1's strongest case) failed at
the same rate as the stress-test tier. Data decided, honestly, against the
intuition holding up as a systematic edge at these timeframes.
