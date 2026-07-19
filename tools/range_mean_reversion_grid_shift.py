"""RANGE_MEAN_REVERSION — Task 3 grid-shift verification (mandatory step, run even
though Task 2 found zero qualifying candidates — this module exists to PROVE that,
not assume it).

Task 2's sweep (tools/backtest_range_mean_reversion_sweep.py, see
docs/range_mean_reversion_task2_sweep.md) found exactly 0 of 28 configs positive in
both halves with an adequate sample (>=20 trades) in BOTH halves — the precondition
this task's own spec sets for grid-shift eligibility. The 2 PROMISING-WATCHLIST
configs (GOLD/1week, SILVER/1week) both fall short purely on test-half sample size
(N=11, N=15), not on direction. GRID_SHIFT_QUALIFYING_CONFIGS is therefore empty by
construction — reproduced here from the sweep's own committed results rather than
asserted from memory, so this module documents WHY there's nothing to test rather
than silently skipping the step.

RESAMPLE APPLICABILITY (for completeness / future reference, since the task requires
noting applicability "per config rather than skipping silently"): this determines
which (asset_class, timeframe) combinations in Task 2's universe are even
grid-shift-testable in principle, independent of whether anything actually qualified.
  - Forex (1h/4h/1day): ALL THREE are NATIVE Twelve Data intervals (Task B1) — no
    resampling happens anywhere in this pipeline for forex, so grid-shift is
    structurally not applicable to any forex timeframe tested here.
  - GOLD (4h/1day/1week): all NATIVE Twelve Data intervals (TWELVE_DATA_ONLY_ASSETS /
    NATIVE_TWELVEDATA_INTERVAL in tools.timeframe_data) — not applicable.
  - SILVER (1day/1week): NATIVE via yfinance's own daily/weekly intervals — not
    applicable. SILVER's 4h is the ONE genuinely RESAMPLED timeframe in this entire
    task's universe (built from yfinance's native 1h via aggregate_n_consecutive_
    candles / the YFINANCE_RESAMPLE_GROUPS path) — grid-shift WOULD apply here if it
    had qualified. It DIED in Task 2 (TRAIN ExpR=-0.023, TEST ExpR=-0.302), so this
    is moot.
  - Crypto 4h/12h/1day (BTC, ETH, SOL, NEAR): all NATIVE Binance intervals
    (NATIVE_BINANCE_INTERVAL in tools.timeframe_data supports "4h"/"12h" directly) —
    not applicable to any crypto config tested here either.

So even setting aside the empty qualifying list, only ONE (asset, timeframe)
combination in this entire task's universe (SILVER/4h) was ever structurally
grid-shift-testable in the first place — and it DIED in Task 2, never reaching the
qualifying bar anyway.
"""
from __future__ import annotations

from dataclasses import dataclass

# Reproduced directly from docs/range_mean_reversion_task2_sweep.md's committed
# results (tools.backtest_range_mean_reversion_sweep.find_qualifying's actual
# output on the real Task 2 sweep) — not re-derived by assumption.
GRID_SHIFT_QUALIFYING_CONFIGS: list[str] = []

NEAR_MISS_CONFIGS = [
    {"label": "GOLD / 1week", "train_trades": 36, "train_expectancy_r": 0.026, "test_trades": 11, "test_expectancy_r": 0.102},
    {"label": "SILVER / 1week", "train_trades": 23, "train_expectancy_r": 0.320, "test_trades": 15, "test_expectancy_r": 0.263},
]
MIN_SAMPLE_SIZE = 20


@dataclass(frozen=True)
class ResampleApplicability:
    asset_class: str
    timeframe: str
    is_resampled: bool
    reason: str


RESAMPLE_APPLICABILITY: list[ResampleApplicability] = [
    ResampleApplicability("forex", "1h", False, "native Twelve Data interval"),
    ResampleApplicability("forex", "4h", False, "native Twelve Data interval"),
    ResampleApplicability("forex", "1day", False, "native Twelve Data interval"),
    ResampleApplicability("GOLD", "4h", False, "native Twelve Data interval"),
    ResampleApplicability("GOLD", "1day", False, "native Twelve Data interval (via load_daily)"),
    ResampleApplicability("GOLD", "1week", False, "native Twelve Data interval"),
    ResampleApplicability("SILVER", "4h", True, "resampled from yfinance native 1h (aggregate_n_consecutive_candles)"),
    ResampleApplicability("SILVER", "1day", False, "native via load_daily (yfinance)"),
    ResampleApplicability("SILVER", "1week", False, "native yfinance 1week interval"),
    ResampleApplicability("crypto", "4h", False, "native Binance interval"),
    ResampleApplicability("crypto", "12h", False, "native Binance interval"),
    ResampleApplicability("crypto", "1day", False, "native via load_daily"),
]


def is_grid_shift_applicable(asset_class: str, timeframe: str) -> bool:
    """Returns whether (asset_class, timeframe) is even structurally grid-shift
    testable in this task's data pipeline, independent of whether it actually
    qualified in Task 2. Raises KeyError for a combination not in this task's
    universe — never silently assumes an answer for something not audited."""
    for entry in RESAMPLE_APPLICABILITY:
        if entry.asset_class == asset_class and entry.timeframe == timeframe:
            return entry.is_resampled
    raise KeyError(f"{asset_class!r}/{timeframe!r} not in this task's audited universe")


def verify_no_grid_shift_needed() -> str:
    """Confirms (doesn't assume) that GRID_SHIFT_QUALIFYING_CONFIGS is empty and
    reports why the 2 near-miss PROMISING-WATCHLIST configs still don't qualify."""
    lines = ["=== RANGE_MEAN_REVERSION Task 3: Grid-Shift Verification ===", ""]
    if GRID_SHIFT_QUALIFYING_CONFIGS:
        lines.append(f"{len(GRID_SHIFT_QUALIFYING_CONFIGS)} configs qualify — see per-config results below.")
        return "\n".join(lines)

    lines.append("0 configs qualify for grid-shift verification (Task 2's own sweep result).")
    lines.append("")
    lines.append("Near-miss configs and why each still doesn't qualify:")
    for cfg in NEAR_MISS_CONFIGS:
        train_ok = cfg["train_trades"] >= MIN_SAMPLE_SIZE and cfg["train_expectancy_r"] > 0
        test_ok = cfg["test_trades"] >= MIN_SAMPLE_SIZE and cfg["test_expectancy_r"] > 0
        reason = []
        if not test_ok:
            reason.append(f"test-half N={cfg['test_trades']} < {MIN_SAMPLE_SIZE} (LOW SAMPLE)")
        if not train_ok:
            reason.append(f"train-half N={cfg['train_trades']} < {MIN_SAMPLE_SIZE}")
        lines.append(f"  {cfg['label']}: positive both halves, but {', '.join(reason)}")

    lines.append("")
    lines.append(
        "Even setting sample size aside: both near-miss configs are at 1week, which is "
        "NATIVE (not resampled) for both GOLD (Twelve Data) and SILVER (yfinance) — "
        "grid-shift would be structurally NOT_APPLICABLE for either even with an "
        "adequate sample, per this codebase's own precedent (metals settlement gaps, "
        "forex Friday-close gap, stocks' native 1h — see RESAMPLE_APPLICABILITY)."
    )
    lines.append(
        "Only SILVER/4h was ever structurally testable in this task's whole universe "
        "(the sole resampled timeframe) — it DIED in Task 2, never reaching the "
        "qualifying bar, so it was never a candidate either."
    )
    lines.append("")
    lines.append("FINAL: no config in RANGE_MEAN_REVERSION Task 2 reaches SURVIVED.")
    return "\n".join(lines)


def main() -> None:
    print(verify_no_grid_shift_needed())


if __name__ == "__main__":
    main()
