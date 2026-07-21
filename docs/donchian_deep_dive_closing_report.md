# Donchian Cross-Asset Deep-Dive — Consolidated Closing Report

Three tasks, each committed separately: Task 1 (data depth audit), Task 2 (37-config
focused sweep at maximum data depth), Task 3 (mechanism validation on 5 standout
configs). This report ties them together and gives the business framing.

## Headline result — precise, not oversold

**GOLD / 1week / N20 cleared every RAW statistical bar this project uses to define
SURVIVED**: positive expectancy both halves (+0.450 train, +0.448 test), adequate
sample both halves (N=144/38, both ≥ MIN_SAMPLE_SIZE=20), and a bootstrap 95% CI
that clears zero on both halves. **This is the first time DONCHIAN_TREND has
cleared that bar in four batches of cross-asset testing** — directly answering
this batch's own question ("is DONCHIAN permanently sample-limited, or does deeper
data resolve it?") in the affirmative: **deeper data resolves it.**

**However, its FINAL reported classification is PROMISING-WATCHLIST, not
SURVIVED** — per this project's own mandatory-grid-shift-verification rule, a raw
SURVIVED result must still clear grid-shift before being called SURVIVED, and
grid-shift is structurally NOT_APPLICABLE for a 1week strategy (no finer native
source exists to resample from without crossing the Friday-close/Sunday-open
settlement gap). **We are therefore NOT claiming "Vatican's first new verified
strategy family since the original three"** — that claim is reserved for a config
that clears grid-shift too, and none can, structurally, at this timeframe. What
changed in this batch is narrower and still real: the sample-size excuse is gone.
If GOLD/1week/N20 doesn't survive further scrutiny, it won't be for lack of data.

## Full results

37 configs run; 27 reached PROMISING-WATCHLIST or better (1 of those 27 — GOLD/
1week/N20 — reached raw SURVIVED before the grid-shift cap); 10 DIED. Full table:
`docs/donchian_task2_full_sweep.md`. Notable non-survivors: **USD/CHF DIED on all
3 N values** (strongly positive train, consistently negative test — a genuine
out-of-sample breakdown, not a sample artifact); **SPY/1day DIED on all 3 N
values** while SPY/1week and QQQ/1day both stayed promising on the same
underlying instruments — a real timeframe-specific effect, not noise.

## PROMOTION LIST

Every SURVIVED-or-better and PROMISING-WATCHLIST config is a live-wiring
candidate, honestly labeled. None of the 27 is wired by this batch — that remains
a separate future step. Grouped by strength:

**Tier 1 — raw-SURVIVED-quality, capped only by structural grid-shift limits:**
- GOLD / 1week / N20 (train N=144 ExpR=+0.450 CI[0.211,0.691], test N=38
  ExpR=+0.448 CI[0.007,0.901]) — **TIMING-CONFIRMED** per Task 3.

**Tier 2 — adequate sample both halves, train-CI clearly positive, cross-asset
N20 pattern:**
- EUR/USD / 1week / N20 — **TIMING-CONFIRMED**
- GBP/USD / 1week / N20 — **TIMING-CONFIRMED**
- USD/JPY / 1week / N40 — **TIMING-CONFIRMED**
- GOLD / 1week / N10 — **PROXIMITY-ONLY** (see mechanism caveat below)

**Tier 3 — remaining PROMISING-WATCHLIST configs (sample-limited on at least one
half, or CI crosses zero on both):** EUR/USD N10/N40, USD/JPY N10/N20, GBP/USD
N20 (train side only), GOLD N40, SILVER N20/N40, SPY 1week (all 3 N), QQQ 1week
and 1day (all 3 N each), AAPL/MSFT/GOOGL 1week N20, BTC 1week/1day N20, ETH 1day
N20 — full detail in `docs/donchian_task2_full_sweep.md`.

## Mechanism verdict (Task 3)

**Predominantly timing-based, with one real, N-specific exception.** 4 of 5
standout configs — including GOLD/1week/N20 itself — keep a clearly positive edge
even against a stricter "near-extreme, not necessarily past it" random baseline:
precise breakout confirmation is doing genuine work, not just proximity to a
trending asset. The exception is GOLD/1week/N10, whose edge over the near-breakout
baseline is slightly negative — on the SAME asset, the faster N10 parameter's
edge looks like "GOLD tends to keep moving near any recent extreme," not "the
exact breakout moment matters."

**Methodology positioning**: DONCHIAN_TREND's N20 (classic) and N40 (structural)
configurations should be described as genuine breakout-confirmation strategies.
N10 (tactical) should not be described the same way — if ever promoted, its honest
framing is "captures upside near recent extremes," a materially weaker and
different claim.

## Cross-asset pattern

**N20 is a genuine cross-asset signal, not an asset-specific fluke.** GOLD/N20
(raw SURVIVED), EUR/USD/N20, and GBP/USD/N20 all reach "adequate sample, train-CI
clearly positive" — three unrelated asset classes (a metal and two currency
pairs), the same N value, the same TIMING-CONFIRMED mechanism per Task 3. This is
the first time in this project's four-batch DONCHIAN_TREND history that a single N
value has shown this level of consistency across asset classes with adequate
(not sample-limited) statistics on at least one half.

## Business framing

DONCHIAN_TREND remains Vatican's strongest watch-list family, and this batch
sharpens exactly why: it is not sample-starved, it clears every bar except a
structural one (grid-shift at 1week), and its edge is now mechanistically
explained (breakout timing, not just trend proximity) for its two slower-N
variants. **Recommended next step: wire GOLD/1week/N20, EUR/USD/1week/N20,
GBP/USD/1week/N20, and USD/JPY/1week/N40 into live forward-testing** as the
Tier 1/2 promotion candidates above, carrying the honest "PROMISING-WATCHLIST —
grid-shift structurally inapplicable, not a data or CI shortfall" status string
Vatican's live scheduler manifest already uses for other 1week/24h configs. No
strategy in this batch is claimed as proven; the evidence bar for that (grid-shift
clearing) cannot be met at this timeframe by any config, a limitation of the
verification method itself, honestly disclosed rather than worked around.
