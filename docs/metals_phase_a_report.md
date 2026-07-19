# Asset Expansion Phase A: Metals (Silver, Platinum) — Consolidated Report

Three tasks, each committed separately: Task 1 (data + calibration audit), Task 2
(full 9-strategy sweep), Task 3 (mandatory grid-shift verification). This report
consolidates all three. Full detail lives in `docs/metals_data_calibration_audit.md`,
`docs/metals_phase_a_full_sweep.md`, and `docs/metals_grid_shift_verification.md`.

## Headline result

**Zero of 76 tested (asset/pair, timeframe, strategy) configurations reach
SURVIVED.** 67 (88%) DIED outright. 9 were positive in both halves with an adequate
sample and went to grid-shift verification; all 9 remain PROMISING-WATCHLIST — 8
because grid-shift is structurally not applicable to daily continuous-futures data,
and the one genuinely testable config (PLATINUM / 2h / VOLATILITY_SQUEEZE ma150)
failed its grid-shift test outright. This is consistent with this project's own
stated ~1.5% historical survival rate for new strategy/asset combinations — reported
factually, not as a disappointment to explain away.

## Task 1: Data + calibration audit

- Twelve Data (GOLD's own source) returns HTTP 404 for both XAG/USD and XPT/USD —
  "available starting with the Grow or Venture plan." Confirmed directly, not
  inferred; GOLD's own XAU/USD is unaffected on the same key.
- Per user decision, added a yfinance fallback: COMEX Silver (SI=F) and NYMEX
  Platinum (PL=F) **continuous front-month futures** — not spot. Every data-source
  string produced says so explicitly. Depth is strong: ~876 days of 1h history
  (2024-02-23 onward) and 6,000+ daily candles back to 1997-2000 — deeper than
  GOLD's own Twelve Data intraday history.
- All 5 standard timeframes (2h/4h/12h/24h/1week) cleared the adequacy bar for both
  metals — no metal or timeframe was blocked; all ten combinations proceeded to
  Task 2.
- Both metals derive their **own** fee/slippage calibration rather than reusing
  GOLD's: measured price/ATR ratios (SILVER 68.10, PLATINUM 72.78 vs GOLD's 185.19)
  sit far outside the 30% reuse tolerance — and much closer to BTC's own ratio
  (70.21). First concrete signal that these metals' relative volatility profile
  looks more like crypto than like calm spot GOLD.
- Side discovery, fixed as part of this task: a real timestamp bug (pandas version
  drift caused `close_time` to be computed 1000x wrong for any datetime-string-based
  source) that would have silently broken TIME-exit logic for GOLD/metals in this
  environment. Fixed with a regression test; confirmed no live/committed Truth
  Ledger data was affected.

## Task 2: Full strategy sweep

All 9 strategies, both metals, all applicable timeframes per the task spec, plus
Gold-Silver / Silver-Platinum pairs and MACRO_RISK_ON — 76 configs total, every
strategy's logic unchanged, only calibration varying. Bootstrap 95% CI + random-entry
baseline on every config.

Two real, honestly-handled data findings: (1) Gold-Silver pairs are cross-vendor
(Twelve Data vs yfinance), and the two vendors stamp the same trading day's daily
close 4 hours apart — fixed for 24h/1week with a date-based alignment join that can
only recover rows, never misalign data; left as an honest near-zero-trade result at
12h, where a safe fix isn't available. (2) DONCHIAN_TREND's registered defaults bake
in GOLD's own fee scale (no crypto sibling to default against) — re-derived fresh
per metal rather than double-applying GOLD's factor.

9 of 76 configs cleared "positive both halves, >=20 trades each half" — see the full
list and table in `docs/metals_phase_a_full_sweep.md`.

## Task 3: Grid-shift verification

8 of the 9 Task 2 candidates are at 24h. Directly confirmed that
`resample_hourly_to_grid` cannot produce a single complete 24h bin for either metal
at ANY UTC offset — COMEX/NYMEX continuous futures carry a real ~2-hour daily
settlement gap around 23:00 UTC, every calendar day. This is a genuine structural
property of exchange-settled futures, not a bug, and the grid-shift question itself
doesn't apply the same way it does to continuously-traded GOLD/BTC — there is no
arbitrary UTC boundary here to re-test; the daily close **is** the exchange's real
settlement. Those 8 stay PROMISING-WATCHLIST, honestly marked NOT_APPLICABLE rather
than skipped silently or forced through an invented workaround.

The one genuinely testable config (PLATINUM / 2h / VOLATILITY_SQUEEZE ma150) got a
real 0h/+1h grid-shift run and failed — its test half turns negative on both the
control and shifted grid, the exact fragile pattern H6 was built to catch.

## Did any strategy family transfer from crypto/gold to metals?

Not cleanly — nothing reaches SURVIVED — but the sweep surfaces several partial,
directionally interpretable signals worth recording for future research phases:

- **MACRO_RISK_ON transfers best to SILVER, not PLATINUM.** SILVER/24h is the
  best-sampled positive-both-halves result in the entire sweep (N=158 train, N=94
  test, both positive). PLATINUM/24h DIED (positive train, negative test). This
  tracks the two metals' real-world character: silver has a genuine monetary/
  precious-metal identity closer to gold's, while platinum is more of an industrial
  metal (autocatalyst demand) with a weaker link to the dollar/real-yield regime
  this strategy trades. A believable, non-arbitrary split, not noise dressed up as
  a story.
- **TREND_PULLBACK's edge shifts slower on metals than on crypto.** BNB's own
  survivor is at 12h; for both SILVER and PLATINUM, TREND_PULLBACK's strongest
  (positive-both-halves) readings cluster at 24h, with 12h notably weak (PLATINUM's
  12h DIED outright; SILVER's 12h sample is nearly empty). The same family, a
  different natural timeframe per asset class.
- **DONCHIAN_TREND (GOLD's own 1week-only hypothesis strategy) shows the most
  consistent cross-metal signal**: positive both halves for BOTH SILVER and
  PLATINUM at 1week, echoing the original GOLD-1week rationale, though samples are
  thin (13-17 trades train, 9 test) and neither clears CI.
- **FVG_REVERSION and BOS_CONTINUATION continue to fail.** Both already died in the
  prior crypto research batch; metals add no exception (FVG: 6/6 DIED; BOS: only one
  weak PROMISING-WATCHLIST out of 6). A consistent cross-asset "this family doesn't
  work," reinforcing rather than contradicting the earlier verdict.
- **COINTEGRATION_PAIRS's weak, sample-limited character repeats.** Silver-Platinum
  (clean, same-vendor data) shows the same "positive but thin, live-proving" profile
  BTC-ETH already has (PROMISING-WATCHLIST at 24h, N=19/22). Gold-Silver is
  compromised more by cross-vendor data plumbing than by a clean test of the
  underlying cointegration hypothesis.

## Do metals behave more like GOLD (slow/weekly/macro) or crypto (fast/volatile)?

Genuinely mixed, on two different dimensions:

- **Relative volatility (Task 1's ATR/price ratio): crypto-like.** Both metals'
  measured price/ATR ratios sit close to BTC's, far from GOLD's much calmer ratio —
  quantitatively, these metals move more like a volatile crypto asset than like
  spot gold, relative to their own price.
- **Best-performing timeframe: neither, exactly — daily (24h) is the metals' own
  apparent sweet spot.** Nearly every strategy family's best (or only)
  positive-both-halves result for metals clusters at 24h — slower than crypto's
  known 12h/2h preference (BNB/TREND_PULLBACK, most FVG/BOS testing), but faster
  than GOLD's own established 1week-only survivor. DONCHIAN_TREND is the one clean
  exception, echoing GOLD's 1week preference on both metals.

Taken together: metals aren't a clean stand-in for either precedent. They trade
with crypto-like relative volatility but reward a timeframe roughly between crypto's
and GOLD's — 24h, not 12h and not 1week. Any future metals-specific strategy
development should treat 24h as the natural default starting point, not inherit
GOLD's 1week or BNB's 12h by assumption.

## What's next

No metals strategy is ready for live paper-tracking from this phase — nothing
reached SURVIVED. The 9 PROMISING-WATCHLIST configs (particularly SILVER/24h/
MACRO_RISK_ON, and the DONCHIAN_TREND 1week pair) are reasonable candidates to
revisit once more live history accrues on the yfinance futures feed (SI=F/PL=F only
go back to 2024-02-23 at 1h — thin by this project's usual standards, unlike GOLD's
years of Twelve Data history). Phase B (stocks) remains explicitly out of scope for
this session per the task's own instruction, pending its own survivorship-bias data
audit.
