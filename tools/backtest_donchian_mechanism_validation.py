"""CLI: Donchian Cross-Asset Deep-Dive, Task 3 — mechanism validation.

Question: does DONCHIAN's precise N-period-high/low breakout TIMING add value, or
is the edge coming from merely being near a price extreme?

For each of Task 2's standout configs (the raw SURVIVED result and the next tier of
"adequate sample, train-half CI clearly positive" results — see selection rationale
below), this compares two random-entry baselines against the SAME real strategy run
(same exits, same sizing, same holding cap, same params):

  1. STANDARD baseline (already implicit in Task 2's own classify_verdict): random
     entries drawn from every warmup-valid candle (donchian_bracket_eligible_mask).
  2. NEAR-BREAKOUT baseline (this task's own, stricter pool):
     nero_core.strategies.donchian_breakout_bracket.near_breakout_mask — random
     entries drawn ONLY from candles within 2% of the N-period high (for a LONG-
     side draw) or 2% of the N-period low (SHORT-side), i.e. the same "near an
     extreme" pool DONCHIAN's own breakout sits inside, but without requiring the
     exact high/low breach.

If the NEAR-BREAKOUT baseline's mean random expectancy is close to the real
strategy's own expectancy (edge_over_random near zero against THIS baseline
specifically), precise breakout TIMING adds little beyond proximity-to-extreme. If
the real strategy still clearly beats even this stricter baseline, precise timing
is doing genuine work.

CONFIG SELECTION (not exhaustive — 5 of the 27 Task 2 promising configs, chosen for
being the strongest, most representative signals rather than re-testing every
sample-limited result, which would not change this question's answer):
  - GOLD / 1week / N20 — the one raw SURVIVED result, top priority.
  - GOLD / 1week / N10 — the single largest sample in the whole sweep (258 trades
    combined), a genuine statistical-power outlier worth checking on its own.
  - EUR/USD / 1week / N20, GBP/USD / 1week / N20 — both reach "adequate sample,
    TRAIN-half CI clearly positive" and share N20 with GOLD's SURVIVED result,
    forming the cross-asset N20 pattern this batch's closing report flags.
  - USD/JPY / 1week / N40 — the strongest USD/JPY result (train CI clearly
    positive), representing the N40/structural preset in this validation set.

Full-series analysis (not train/test split) — this is a mechanism diagnostic on the
confirmed pattern itself, not a second generalization test; Task 2 already
established out-of-sample behavior.

Usage:
    python -m tools.backtest_donchian_mechanism_validation
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.strategies import donchian_breakout_bracket as dbb
from tools.backtest_donchian_deep_dive import (
    _fetch_forex_candles,
    _fetch_gold_weekly_uncapped,
    donchian_bracket_eligible_mask,
)
from tools.backtest_statistics import random_entry_baseline_single_asset

VALIDATION_CONFIGS = [
    {"label": "GOLD / 1week / N20", "fetch": _fetch_gold_weekly_uncapped, "n_key": "N20", "fee_bps": 10.0},
    {"label": "GOLD / 1week / N10", "fetch": _fetch_gold_weekly_uncapped, "n_key": "N10", "fee_bps": 10.0},
    {"label": "EUR/USD / 1week / N20", "fetch": lambda: _fetch_forex_candles("EUR/USD"), "n_key": "N20", "fee_bps": 5.0},
    {"label": "GBP/USD / 1week / N20", "fetch": lambda: _fetch_forex_candles("GBP/USD"), "n_key": "N20", "fee_bps": 5.0},
    {"label": "USD/JPY / 1week / N40", "fetch": lambda: _fetch_forex_candles("USD/JPY"), "n_key": "N40", "fee_bps": 5.0},
]


def run_validation() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for config in VALIDATION_CONFIGS:
        candles, method = config["fetch"]()
        params = dbb.build_parameters_for_n(config["n_key"], "1week", config["fee_bps"], 2.0)

        trades, _state = dbb.run_donchian_bracket_backtest(candles, params)
        r_values = [t.r_multiple for t in trades]
        real_expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

        enriched = dbb.add_indicators(candles, params)
        evaluable = enriched.dropna(subset=dbb.INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)

        standard_mask = donchian_bracket_eligible_mask(evaluable)
        standard_baseline = random_entry_baseline_single_asset(
            evaluable, standard_mask, params, dbb.size_entry, real_expectancy_r, len(trades), evaluate_exit_fn=dbb.evaluate_exit
        )

        near_mask = dbb.near_breakout_mask(evaluable, proximity_pct=2.0)
        near_baseline = random_entry_baseline_single_asset(
            evaluable, near_mask, params, dbb.size_entry, real_expectancy_r, len(trades), evaluate_exit_fn=dbb.evaluate_exit
        )

        print(
            f"{config['label']}: real N={len(trades)} ExpR={real_expectancy_r:.3f} | "
            f"standard-baseline edge={standard_baseline.edge_over_random:.3f} | "
            f"near-breakout-baseline edge={near_baseline.edge_over_random:.3f} "
            f"(eligible={int(near_mask.sum())}/{len(evaluable)} candles, {method})"
        )
        rows.append({
            "label": config["label"], "n_key": config["n_key"], "trades": len(trades),
            "real_expectancy_r": real_expectancy_r, "standard_baseline": standard_baseline,
            "near_breakout_baseline": near_baseline, "eligible_near_breakout_candles": int(near_mask.sum()),
            "total_evaluable_candles": len(evaluable),
        })
    return rows


def mechanism_verdict(row: dict[str, object]) -> str:
    """TIMING-CONFIRMED if the real strategy still clearly beats the near-breakout
    baseline (edge_over_random > a small tolerance); PROXIMITY-ONLY if the
    near-breakout baseline already captures most of the edge (edge_over_random close
    to zero or negative against that stricter pool)."""
    near = row["near_breakout_baseline"]
    if near is None:
        return "INCONCLUSIVE (no eligible near-breakout pool)"
    return "TIMING-CONFIRMED" if near.edge_over_random > 0.05 else "PROXIMITY-ONLY"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== Donchian Mechanism Validation: Timing vs. Proximity ===", ""]
    for r in rows:
        verdict = mechanism_verdict(r)
        lines.append(f"{r['label']} ({r['n_key']}): {verdict}")
        lines.append(
            f"    real: N={r['trades']} ExpR={r['real_expectancy_r']:.3f} | "
            f"standard-pool edge-over-random={r['standard_baseline'].edge_over_random:.3f} | "
            f"near-breakout-pool edge-over-random={r['near_breakout_baseline'].edge_over_random:.3f} "
            f"({r['eligible_near_breakout_candles']}/{r['total_evaluable_candles']} candles eligible)"
        )
    return "\n".join(lines)


def main() -> None:
    rows = run_validation()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
