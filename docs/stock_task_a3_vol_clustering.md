# Comprehensive Asset Expansion, Part A: Stocks — Task A3 Vol-Clustering Multiplier

Applies the H2-BUILD vol-clustering position-sizing multiplier to Task A2's top 3
qualifying configs by test-half ExpR.

## Results

| Config | Metric | Multiplier OFF | Multiplier ON | Delta |
|---|---|---|---|---|
| INTU / 1day / MEAN_REVERSION v1 | ExpR (R/trade) | 0.3471 | 0.3471 | 0.0 (exact) |
| | Win rate | 56.92% | 56.92% | 0.0 |
| | MaxDD | -4.381% | -4.343% | **+0.04pp (slightly better)** |
| | Net P&L | +$2,467 | +$3,210 | +$744 |
| NVDA / 1week / BREAKOUT_MOMENTUM | ExpR (R/trade) | 0.4443 | 0.4443 | ~0 (float noise) |
| | Win rate | 65.52% | 65.52% | 0.0 |
| | MaxDD | -8.298% | -10.113% | **-1.82pp (worse)** |
| | Net P&L | +$4,634 | +$5,089 | +$456 |
| AAPL / 1week / BREAKOUT_MOMENTUM | ExpR (R/trade) | 0.3227 | 0.3227 | 0.0 (exact) |
| | Win rate | 60.40% | 60.40% | 0.0 |
| | MaxDD | -5.803% | -5.891% | **-0.09pp (worse)** |
| | Net P&L | +$6,018 | +$7,304 | +$1,286 |

## Finding: same R/win-rate invariance, but MaxDD direction is genuinely mixed here

The R-multiple/win-rate invariance already established for GOLD/BNB and the two forex
configs holds exactly again — no surprise, it's a mathematical property of uniform
position-size scaling, not an asset-specific one.

**MaxDD, however, is NOT uniformly worse this time.** INTU's drawdown very slightly
*improved* with the multiplier on (-4.381% -> -4.343%), while NVDA and AAPL both
widened (by -1.82pp and -0.09pp respectively) — a genuinely mixed result, unlike every
prior test in this batch where MaxDD moved in the same (worse) direction every time.
This is a useful correction to any premature "vol-clustering always inflates
drawdown" conclusion from the earlier crypto/forex results: **the drawdown effect is
config- and trade-sequence-dependent, not a fixed property of the multiplier itself.**

Net dollar P&L improved for all three stock configs (a different pattern from forex,
where it was mixed) — again a reminder that these effects come from where high-
cluster-score periods happen to land relative to wins/losses in each specific
history, not from a designed edge.

## Where does vol-clustering help stocks — dollars yes, risk-adjusted no

Consistent with every other asset class tested: R-adjusted performance (the only
metric that actually reflects skill/edge quality) never moves. Dollar P&L improved
for all three stock configs tested here, and MaxDD moved in different directions
per config — a more favorable-looking result than crypto/forex on the surface, but
one that reflects this specific sample of trades, not a property that would
necessarily replicate on a different config or a longer/different history.
