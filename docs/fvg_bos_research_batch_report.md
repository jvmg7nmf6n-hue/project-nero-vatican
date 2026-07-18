# FVG/BOS Research Batch — Consolidated Report

Three tasks, live data throughout, standard rigor (registry versioning, tests, 70/30
chronological split, LOW SAMPLE flags, upgraded harness — bootstrap CI + random-entry
baseline). Full detail in each task's own doc: `docs/fvg_reversion_report.md`,
`docs/bos_continuation_report.md`, `docs/trend_pullback_filter_ab_report.md`.

**Verdict categories**: SURVIVED (positive both halves, adequate sample, CI clears
zero) / PROMISING-WATCHLIST (positive both halves, but LOW SAMPLE or CI crosses zero —
eligible for live forward-testing, not dead) / DIED (negative or flat).

## Task A — FVG_REVERSION v1.0.0 (7 assets × {2h, 4h, 12h} = 21 configs)

| Verdict | Count | Configs |
|---|---|---|
| SURVIVED | 0 | — |
| PROMISING-WATCHLIST | 3 | SOL/12h, XRP/12h, NEAR/12h |
| DIED | 18 | BTC/2h/4h/12h, ETH/2h/4h/12h, SOL/2h/4h, BNB/2h/4h/12h, XRP/2h/4h, DOGE/2h/4h/12h, NEAR/2h/4h |

## Task B — BOS_CONTINUATION v1.0.0 (7 assets × {4h, 12h, 24h} = 21 configs)

| Verdict | Count | Configs |
|---|---|---|
| SURVIVED | 0 | — |
| PROMISING-WATCHLIST | 13 | BTC/4h, ETH/4h, ETH/12h, SOL/12h, SOL/24h, BNB/4h, BNB/12h, BNB/24h, XRP/24h, DOGE/4h, DOGE/12h, DOGE/24h, NEAR/24h |
| DIED | 8 | BTC/12h, BTC/24h, ETH/24h, SOL/4h, XRP/4h, XRP/12h, NEAR/4h, NEAR/12h |

## Task C — Filter test on BNB/12h TREND_PULLBACK (side by side)

| Variant | Split | N | ExpR | Win% | PF | MaxDD | CI |
|---|---|---|---|---|---|---|---|
| v1 (unfiltered) | Train | 57 | 0.147 | 50.9% | 1.27 | -11.6% | crosses zero |
| v1 (unfiltered) | Test | 30 | 0.243 | 56.7% | 1.55 | -3.7% | crosses zero |
| fvg-filtered | Train | 32 | 0.168 | 50.0% | 1.33 | -5.9% | crosses zero |
| fvg-filtered | Test | 12 *LOW SAMPLE* | 0.095 | 50.0% | 1.19 | -3.2% | crosses zero |
| bos-filtered | Train | 57 | 0.147 | 50.9% | 1.27 | -11.6% | crosses zero |
| bos-filtered | Test | 30 | 0.243 | 56.7% | 1.55 | -3.7% | crosses zero |

bos-filtered = identical to v1 in every metric (the filter never once bound on this
data). fvg-filtered roughly halved the sample, improved train-half drawdown and
random-edge slightly, but test-half expectancy was worse than v1's, on too small a
sample to trust. Neither filter clearly raises per-trade quality.

## Recommended live forward-test watch-list

Every PROMISING-WATCHLIST config from Tasks A and B (per this batch's own definition —
positive both halves, eligible for forward-testing, not dead):

**From Task A (FVG_REVERSION):** SOL/12h, XRP/12h, NEAR/12h

**From Task B (BOS_CONTINUATION):** BTC/4h, ETH/4h, ETH/12h, SOL/12h, SOL/24h, BNB/4h,
BNB/12h, BNB/24h, XRP/24h, DOGE/4h, DOGE/12h, DOGE/24h, NEAR/24h

No config from either task SURVIVED. No config from Task C's two filtered variants is
recommended (neither beat unfiltered v1). No strategy's live-scheduler status changed
as part of this work.
