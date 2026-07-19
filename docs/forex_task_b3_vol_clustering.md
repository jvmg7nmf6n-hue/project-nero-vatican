# Comprehensive Asset Expansion, Part B: Forex — Task B3 Vol-Clustering Multiplier

Applies the H2-BUILD vol-clustering position-sizing multiplier
(`nero_core.quant.vol_regime` + `tools.vol_clustering_harness`) to the top configs
from Task B2's sweep — only 2 configs cleared the adequate-both-halves bar (per B2's
own "fewer if fewer qualify" note), so both are used here.

## Results

| Config | Metric | Multiplier OFF | Multiplier ON | Delta |
|---|---|---|---|---|
| EUR/JPY / 1week / BREAKOUT_MOMENTUM | ExpR (R/trade) | 0.1885 | 0.1885 | ~0 (float noise) |
| | Win rate | 56.10% | 56.10% | 0.0 |
| | MaxDD | -6.95% | -9.92% | **-2.98pp (worse)** |
| | Net P&L | +$1,524 | +$1,262 | -$261 |
| EUR/JPY / 1day / BOS_CONTINUATION | ExpR (R/trade) | 0.0109 | 0.0109 | ~0 (float noise) |
| | Win rate | 44.07% | 44.07% | 0.0 |
| | MaxDD | -6.76% | -8.13% | **-1.38pp (worse)** |
| | Net P&L | +$184 | +$234 | +$50 |

## Finding: R-expectancy and win-rate are mathematically invariant to this multiplier

Both configs show an ExpR delta on the order of 1e-17 (pure floating-point noise, not
a real effect) and an EXACT 0.0 win-rate delta. This is not a measurement artifact —
it is the expected, provable behavior of a multiplier that scales `risk_per_trade`
(and therefore quantity/notional) uniformly at entry, without touching the stop
distance: R-multiple = net_pnl / risk_dollars, and scaling `risk_dollars` by a factor
scales `net_pnl` by the same factor (both derive from the same quantity), so the
RATIO is unchanged for every individual trade. Uniform position-size scaling can
change absolute dollar P&L and the equity-curve-based MaxDD, but by construction it
cannot move R-based expectancy or win-rate at all. This matches exactly what the
crypto baseline (GOLD/1week, BNB/12h — see the closing report) already showed.

## Finding: MaxDD gets worse, dollar P&L is mixed

For both forex configs, drawdown widened when the multiplier was on (BREAKOUT_MOMENTUM:
-6.95% -> -9.92%; BOS_CONTINUATION: -6.76% -> -8.13%) — sizing up during clustered-vol
periods concentrated more risk into exactly the kind of choppy stretches that produce
consecutive losses, without any offsetting R-adjusted improvement. Net dollar P&L
moved in OPPOSITE directions between the two configs (down for BREAKOUT_MOMENTUM, up
for BOS_CONTINUATION) — confirming this isn't a uniform "always better" or "always
worse" dollar effect either; it depends entirely on whether high-cluster-score periods
happened to coincide with wins or losses in each specific trade sequence, which is
exactly the kind of fragile, sequence-dependent behavior a genuinely lookahead-free
sizing rule should be expected to produce rather than a designed edge.

## Where does vol-clustering help forex — nowhere observed here

Neither forex config shows a benefit from the multiplier. Combined with the crypto
baseline's identical pattern, the working answer to this task's own question
("where does vol-clustering help, where does it merely inflate drawdown?") is: **it
has not been observed to help anywhere tested so far — it inflates drawdown with a
mathematically neutral (not negative, not positive) effect on R-adjusted returns.**
See the closing report for the full cross-asset-class comparative table (Task C2).
