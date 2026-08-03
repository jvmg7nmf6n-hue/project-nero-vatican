# COINTEGRATION_PAIRS short-leg cost re-simulation — scope only

**Status: scoping document. No code in this document has been implemented or run.**
Written in response to a direct request to scope (not build) what it would take to
replace the earlier ~0.24%-round-trip *estimate* for the missing short leg with an
actual computed number, before COINTEGRATION_PAIRS's badge keeps saying "Verified."

## 1. What's actually being measured today

`run_pairs_backtest` (`nero_core/strategies/cointegration_pairs.py`) is honest about
this in its own module docstring: it simulates **one leg only**. When the z-score
signal says "long BTC, short ETH," the backtest opens a real long BTC position and
does nothing else — no ETH position, no short-leg PnL, no short-leg fees, no borrow/
funding cost. The reported OOS `r_multiple` of +0.003 (`net_pnl / notional` on that
single long leg) is therefore a directional bet timed by a pairs signal, not a
market-neutral arbitrage return. Adding the second leg is not a refinement of this
number — it replaces what is being measured.

## 2. Data availability — better than the earlier estimate assumed

The earlier ~0.24% figure was an estimate because I hadn't checked what data actually
exists in this repo. It does:

- **Price data for both legs**: already present. `align_pair_candles` already inner-joins
  BTC and ETH closes on `close_time` — the aligned frame passed to `run_pairs_backtest`
  already carries both legs' prices on every row. No new price data source is needed.
- **Funding-rate data (the actual missing cost)**: `nero_core/data_sources/funding_data.py`
  + `data/funding_cache/{BTC,ETH}_funding.csv` already exist, built for the unrelated
  FUNDING_EXTREME strategy. `BTC_funding.csv` has 7,509 real Binance USDT-perp funding
  settlements from 2019-09-10 onward; `ETH_funding.csv` has 7,275. Binance settles
  funding every 8h (00:00/08:00/16:00 UTC) and this cache stores every settlement's
  real rate and exact timestamp — `load_funding_history(asset)` returns it as a
  DataFrame, cache-first, live-fetch-fallback, no synthetic data. This means the
  short leg's carrying cost can be **computed from real historical settlements for
  the exact holding period of each trade**, not assumed as a flat estimate.

This changes the framing: the earlier ~0.24% was a guess because I didn't check;
a real number is achievable without fetching anything new.

## 3. What execution model the short leg represents (a decision, not a computation)

Two different real-world ways to actually get short exposure, with different cost
structures:

- **Spot margin short** (borrow ETH, sell it, buy back later): cost is a margin
  interest rate, which Binance does not expose a clean historical public series for
  in this codebase today. Would require either a new data source or a hand-documented
  assumption (which is exactly the kind of unverified estimate this task exists to
  replace).
- **USDT-perp short** (short an ETH-USDT perpetual future): cost is the funding rate
  — data for this already exists (Section 2). This is also the realistic way a crypto
  market-neutral pairs trade is actually implemented in practice, since perp funding
  is liquid and continuously quoted where margin borrow often isn't.

**Recommendation: model the short leg as a USDT-perp short**, using the real cached
funding history, specifically because it's the option with real data already in this
repo. This is a call for the user to confirm before implementation, not something I've
decided unilaterally — it changes what "COINTEGRATION_PAIRS" is claimed to trade.

## 4. What would actually need to change in `run_pairs_backtest`

Today `OpenTrade`/`ExitEvent` describe one leg. A real two-leg simulation needs:

- **`OpenTrade`**: add the short leg's entry price, quantity, notional, and entry fee
  (mirroring the long leg's existing fields), plus the `open_close_time` it already
  has (needed to look up which funding settlements the trade spans).
- **Short-leg sizing** (a second decision the user needs to make, since it changes the
  R definition again): dollar-neutral (short notional = long notional) or
  hedge-ratio-weighted (short notional = long notional × `hedge_ratio` at entry, the
  textbook beta-neutral construction this strategy's own spread definition already
  implies). The current single-leg `notional_fraction` sizing says nothing about this.
- **Short-leg PnL at exit**: `(entry_price_short - exit_price_short) * quantity_short`
  (short gains when price falls) — `apply_slippage` reused in the mirrored direction
  (sell to open, buy to close) and `fee_bps` applied to both legs' entry and exit,
  exactly as the long leg already does.
- **Funding cost accrual**: at exit, sum `funding_rate * notional_short` for every
  `load_funding_history(short_asset)` settlement whose `settlement_time` falls between
  the trade's `open_close_time` and its exit `close_time`. Sign matters: a short
  position *receives* funding when the rate is positive and *pays* when negative —
  get this backwards and the "cost" becomes a fabricated tailwind, which would be a
  new, worse version of the fabrication problem this task exists to avoid.
- **`ExitEvent`**: `gross_pnl`/`fees`/`net_pnl`/`r_multiple` all need to become the
  *combined* two-leg numbers. The existing `r_multiple` docstring comment (`net_pnl /
  notional`, already flagged as non-comparable to other strategies' R) would need a
  matching update once `notional` itself means "combined long+short capital
  allocated," not one leg's.
- **New test coverage**: a two-leg P&L fixture proving the short leg's sign, fee, and
  funding-accrual math independently of the long leg (mirroring
  `tests/test_cointegration_pairs.py`'s existing per-mechanic test structure), plus a
  full-history re-run through the same OOS split (`docs/grid_shift_robustness_followup.md`'s
  4-offset grid-shift audit) so the new number is checked with the same rigor as the
  original, not just computed once and trusted.

## 5. Rough size of the change

Not a parameter tweak — a genuine extension of the strategy's own backtest engine.
Bounded, though: no new external data pipeline (Section 2), and the mechanical pieces
(mirrored fee/slippage math, a funding-settlement date-range sum) are each individually
small and testable in isolation. Realistic scope: new dataclass fields + short-leg P&L
+ funding accrual + updated tests + a full backtest re-run and grid-shift re-check,
done as its own reviewable unit — not bundled into an unrelated change.

## 6. What would still NOT be captured even after this

Being upfront about the residual gap so a "Verified" badge after this work still isn't
overclaiming:

- **Perp-vs-spot basis risk**: the backtest's long leg is implicitly spot-like (no
  funding modeled on it); a real market-neutral implementation would likely run both
  legs as perps, meaning the long leg would *also* accrue/pay funding. Modeling funding
  on the short leg only, while leaving the long leg unchanged, would itself be a
  half-fix — this needs to be symmetric across both legs or explicitly justified why not.
- **Liquidation/margin risk on the short leg**: not modeled; the current single-leg
  backtest has no leverage or liquidation concept at all.
- **Execution slippage still uses a flat `slippage_bps` assumption** on both legs, not
  real order-book depth at the moment of the trade — same limitation the long leg
  already has today, just now applying to two legs instead of one.

## Bottom line

A real computed number (not an estimate) is achievable without new data acquisition,
because the funding-rate history this needs already exists in this repo for an
unrelated strategy. What's needed is (a) the user's sign-off on the two framing
decisions in Sections 3 and 4 (perp-vs-margin execution model; dollar-neutral vs
hedge-ratio-weighted short sizing), since both change what the resulting R actually
means, and (b) the implementation and test work in Section 4, done as its own PR. Per
the instruction this document responds to, none of that implementation has been done
here.
