# Comprehensive Asset Expansion, Part C: Crypto, Task C2 — Vol-Clustering Comparative

Assembles the H2-BUILD vol-clustering multiplier (`nero_core.quant.vol_regime` +
`tools.vol_clustering_harness`) results across every asset class tested in this
batch: the crypto baseline (GOLD/1week, BNB/12h — first-ever runs, no prior
baseline existed for either), Task A3 (top 3 stocks), and Task B3 (top 2 forex,
"fewer if fewer qualify").

## Full comparative table

| Asset class | Config | ExpR delta | Win% delta | MaxDD delta | Net P&L delta |
|---|---|---|---|---|---|
| Crypto (GOLD) | GOLD/1week/BREAKOUT_MOMENTUM gold-calibrated | ~0 | 0.0 | **-0.84pp** | +$640 |
| Crypto (BNB) | BNB/12h/TREND_PULLBACK | ~0 | 0.0 | **-0.77pp** | +$254 (loss reduced) |
| Stocks | INTU/1day/MEAN_REVERSION v1 | 0.0 | 0.0 | **+0.04pp** | +$744 |
| Stocks | NVDA/1week/BREAKOUT_MOMENTUM | ~0 | 0.0 | **-1.82pp** | +$456 |
| Stocks | AAPL/1week/BREAKOUT_MOMENTUM | 0.0 | 0.0 | **-0.09pp** | +$1,286 |
| Forex | EUR/JPY/1week/BREAKOUT_MOMENTUM | ~0 | 0.0 | **-2.98pp** | -$261 |
| Forex | EUR/JPY/1day/BOS_CONTINUATION | ~0 | 0.0 | **-1.38pp** | +$50 |

*("~0" = on the order of 1e-16/1e-17, floating-point noise from independently
compounding equity paths, not a real effect; "0.0" = exactly zero.)*

## Finding 1: R-multiple expectancy and win-rate are PROVABLY invariant, everywhere

Across all 7 configs, 3 asset classes, and every strategy family tested
(MEAN_REVERSION, BREAKOUT_MOMENTUM, TREND_PULLBACK, BOS_CONTINUATION),
the ExpR and win-rate deltas are either exactly 0.0 or floating-point noise. This is
not a coincidence or a weak result across a small sample — it is a mathematical
certainty given how the multiplier is constructed: it scales `risk_per_trade`
uniformly at the moment of sizing, which scales both `risk_dollars` and the resulting
`net_pnl` by the same factor for that trade. Since `r_multiple = net_pnl /
risk_dollars`, the ratio is invariant to the scaling factor, trade by trade,
regardless of asset class, strategy family, or timeframe. **Any future report that
attributes an ExpR or win-rate change to this multiplier is describing a bug, not
this hypothesis's actual behavior.**

## Finding 2: MaxDD worsens in 6 of 7 configs — but not universally (a genuine correction)

6 of 7 configs show wider drawdown with the multiplier on; only INTU (stocks) shows a
very slight improvement (+0.04pp). This means the honest answer to "does
vol-clustering inflate drawdown" is **usually, but not universally** — it is a
real, observable tendency across most tested configs, not an absolute law. The one
exception matters: it proves the effect is genuinely sequence-dependent (whether
high-cluster-score periods happen to land on winning or losing trades in that
specific history), not a fixed mathematical consequence the way the ExpR invariance
is.

## Finding 3: Net dollar P&L usually improves (6 of 7) — but this is a coin flip dressed as a pattern

6 of 7 configs show improved dollar P&L with the multiplier on. Combined with
Finding 1 (R-adjusted performance is unchanged) and Finding 2 (drawdown usually
worsens), the coherent overall picture is: **sizing up during high-cluster-score
periods amplifies the absolute scale of whatever the underlying trade sequence
already contained** — bigger wins when winners land in clustered-vol windows, bigger
losses when losers do, and since real trade sequences have more winning trades than
losing ones in a positive-expectancy strategy (by definition), amplifying everything
proportionally will *usually* net out to more dollars, at the cost of a
correspondingly wider drawdown on the way there. This is not evidence of skill or
edge — it's leverage, dressed up as a signal.

## Where does vol-clustering help — and where does it merely inflate drawdown?

**It has not been observed to improve risk-adjusted returns anywhere in this batch —
that is a mathematical certainty for this specific multiplier design, not merely an
empirical absence of evidence.** Where it "helps" is in absolute dollar terms, most
of the time, at the cost of correspondingly wider (though not universally wider)
drawdown — the classic leverage trade-off, not a genuine edge. A trader who wants
more dollar P&L and is willing to accept more drawdown risk could apply this
multiplier and get a plausible-looking boost most of the time; a trader evaluating
whether this multiplier represents genuine skill should conclude it does not, since
the R-adjusted metric that actually measures strategy quality never moves.

**Recommendation**: do not present this multiplier as an "edge enhancer" in any
future documentation or UI copy. If it's ever offered as a user-facing option, it
should be labeled honestly as a leverage/risk-tolerance dial, not a performance
improvement — consistent with this project's no-fabricated-edge discipline.
