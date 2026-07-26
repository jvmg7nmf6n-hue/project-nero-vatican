"""CLI: Vatican's own independent verification harness for REPAIR_BREAKOUT_QUALITY
v1.0.0 (external spec, display name FIX_BREAKOUT_QUALITY — see
nero_core/strategies/repair_breakout_quality.py's module docstring for the mechanism
and for the two external-testing findings this implementation fixes: multi-candle
retest confirmation, and a no-gap-tolerance stop-loss).

Per the user's own instruction, the external 12-trade stats (66.7% win rate, +0.158R
expectancy, PF 1.63, CI -0.647R to +0.964R) are NEVER reused as evidence anywhere in
this codebase — this tool runs Vatican's own measurement from scratch:

  1. 70/30 CHRONOLOGICAL split (tools.backtest_train_test_split.split_chronological)
     on the last 3 years of native 4H candles (or less, if an asset's listing history
     is shorter — BTC/XRP/BNB are all well past 3 years old on Binance, so this should
     not bind in practice).
  2. Bootstrap 95% CI on the mean per-trade R multiple (tools.backtest_statistics.
     bootstrap_mean_r_ci), on EACH half independently.
  3. Random-entry baseline (tools.backtest_statistics.random_entry_baseline_single_asset)
     against the regime-only eligible pool (close > MA200, MA20 > MA200, ATR/close <=
     4% — see repair_breakout_eligible_mask) EXCLUDING the specific breakout+retest
     trigger, on EACH half independently — answers "would ANY entry timing within the
     same trend+low-vol regime do about as well, without the breakout/retest timing?"
  4. Grid-shift robustness: the primary 4H grid is itself built by resampling native
     1h candles at UTC offset 0 (nero_core.data_sources.candle_resampling.
     resample_hourly_to_grid) rather than fetched as Binance's own native "4h" candles,
     so offsets +1h/+2h/+3h are directly comparable re-runs of the exact same
     mechanism on a shifted bin boundary. Per this project's established convention
     (tools/backtest_metals_grid_shift_verification.py), grid-shift is a DEMOTION-ONLY
     check: it can knock a raw SURVIVED result down to PROMISING-WATCHLIST if it
     doesn't hold on every shift, but never promotes anything.

Verdict categories (tools.backtest_statistics.classify_verdict): SURVIVED, PROMISING-
WATCHLIST, DIED. Whatever comes out is reported as-is — no target outcome, no edge
claimed until this harness actually clears it.

No synthetic/fabricated price data is ever used — if a fetch fails, that asset is
reported SKIPPED with the reason.

Usage:
    python -m tools.backtest_repair_breakout_quality
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies import repair_breakout_quality as rbq
from tools.backtest_statistics import MIN_SAMPLE_SIZE, bootstrap_mean_r_ci, classify_verdict, random_entry_baseline_single_asset
from tools.backtest_train_test_split import split_chronological

ASSETS = ["BTC", "XRP", "BNB"]
TARGET_HOURS = 4
GRID_OFFSETS = [0, 1, 2, 3]  # exhaustive -- a 4h bin only has 4 possible UTC-clock offsets
HOURLY_FETCH_CANDLES = 27_000  # ~3.08 years of native 1h candles, comfortably past the 3-year scope
LOOKBACK_DAYS = 3 * 365

FEE_BPS = 10.0  # crypto convention, matches every other crypto strategy in this codebase
SLIPPAGE_BPS = 2.0

PARAMS = rbq.RepairBreakoutParameters(fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS)


def repair_breakout_eligible_mask(evaluable: pd.DataFrame) -> pd.Series:
    """The regime PRECONDITION only (close > MA200, MA20 > MA200, ATR/close <=
    atr_pct_max) -- deliberately excludes the breakout-high/retest-confirmation
    TRIGGER itself, matching this codebase's established convention (e.g.
    breakout_momentum_regime_mask, trend_pullback_regime_mask) for isolating "would any
    entry timing within the same regime do about as well?" from the specific mechanism
    under test."""
    return (
        (evaluable["close"] > evaluable["ma200"])
        & (evaluable["ma20"] > evaluable["ma200"])
        & (evaluable["atr_pct"] <= PARAMS.atr_pct_max)
    )


def _slice_last_n_days(hourly: pd.DataFrame, days: int) -> pd.DataFrame:
    if hourly.empty:
        return hourly
    frame = hourly.sort_values("close_time").reset_index(drop=True)
    cutoff = frame["date"].max() - pd.Timedelta(days=days)
    return frame[frame["date"] > cutoff].reset_index(drop=True)


def _half_stats(half_candles: pd.DataFrame, params: rbq.RepairBreakoutParameters) -> dict[str, object]:
    trades, _state = rbq.run_repair_breakout_backtest(half_candles, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    enriched = rbq.add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=rbq.INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    eligible_mask = repair_breakout_eligible_mask(evaluable)

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, params, rbq.size_entry, expectancy_r, len(trades), evaluate_exit_fn=rbq.evaluate_exit
    )
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _light_half_stats(half_candles: pd.DataFrame, params: rbq.RepairBreakoutParameters) -> dict[str, object]:
    """Grid-shift's own lighter check (no bootstrap/random-baseline re-run per shift --
    matches backtest_metals_grid_shift_verification.py's own division of rigor: full
    statistical machinery on the primary grid only, a cheap qualify check across
    shifts)."""
    trades, _state = rbq.run_repair_breakout_backtest(half_candles, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0
    return {"trades": len(trades), "expectancy_r": expectancy_r}


def _qualifies(train: dict, test: dict) -> bool:
    return (
        train["trades"] >= MIN_SAMPLE_SIZE and test["trades"] >= MIN_SAMPLE_SIZE
        and train["expectancy_r"] > 0 and test["expectancy_r"] > 0
    )


def run_asset(asset: str, client: MarketDataClient) -> dict[str, object]:
    start = time.monotonic()
    try:
        hourly_result = client.load_intraday(asset, interval="1h", candles=HOURLY_FETCH_CANDLES)
    except MarketDataUnavailableError as exc:
        return {"asset": asset, "error": str(exc)}

    hourly = _slice_last_n_days(hourly_result.prices, LOOKBACK_DAYS)
    if hourly.empty:
        return {"asset": asset, "error": "no usable 1h history after slicing to the last 3 years"}

    grid_results: dict[int, dict[str, object]] = {}
    for offset in GRID_OFFSETS:
        candles = resample_hourly_to_grid(hourly, TARGET_HOURS, offset)
        train, test = split_chronological(candles)
        if train.empty or test.empty:
            grid_results[offset] = {"error": "not enough resampled history to split 70/30"}
            continue
        if offset == 0:
            train_stats = _half_stats(train, PARAMS)
            test_stats = _half_stats(test, PARAMS)
        else:
            train_stats = _light_half_stats(train, PARAMS)
            test_stats = _light_half_stats(test, PARAMS)
        grid_results[offset] = {
            "candle_count": len(candles),
            "date_range": f"{candles['date'].min().date()} to {candles['date'].max().date()}",
            "train": train_stats, "test": test_stats,
            "qualifies": _qualifies(train_stats, test_stats),
        }

    primary = grid_results.get(0, {})
    if "error" in primary:
        return {"asset": asset, "error": primary["error"], "hourly_source": hourly_result.source}

    raw_verdict = classify_verdict(primary["train"], primary["test"])
    grid_shift_note = None
    verdict = raw_verdict
    if raw_verdict == "SURVIVED":
        other_offsets = [o for o in GRID_OFFSETS if o != 0]
        holds = all(
            "error" not in grid_results[o] and grid_results[o]["qualifies"] for o in other_offsets
        )
        if not holds:
            verdict = "PROMISING-WATCHLIST"
            failing = [o for o in other_offsets if "error" in grid_results[o] or not grid_results[o]["qualifies"]]
            grid_shift_note = f"raw SURVIVED did not hold at offset(s) {failing} -- capped to PROMISING-WATCHLIST"

    elapsed = time.monotonic() - start
    return {
        "asset": asset, "hourly_source": hourly_result.source, "hourly_candle_count": len(hourly),
        "grid_results": grid_results, "raw_verdict": raw_verdict, "verdict": verdict,
        "grid_shift_note": grid_shift_note, "elapsed_s": elapsed,
    }


def run_full_sweep() -> list[dict[str, object]]:
    client = MarketDataClient()
    results = []
    for asset in ASSETS:
        print(f"Running {asset}...", flush=True)
        result = run_asset(asset, client)
        results.append(result)
        if "error" in result:
            print(f"  {asset}: SKIPPED -- {result['error']}")
        else:
            print(f"  {asset}: {result['verdict']} ({result['elapsed_s']:.1f}s, {result['hourly_candle_count']} 1h candles used)")
    return results


def _fmt_half(stats: dict[str, object], light: bool = False) -> str:
    flag = "*" if stats["trades"] < MIN_SAMPLE_SIZE else ""
    if light:
        return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}"
    ci = stats["ci"]
    ci_str = f" CI=[{ci.lower_2_5:.3f},{ci.upper_97_5:.3f}]" if ci is not None else " CI=n/a"
    baseline = stats["baseline"]
    base_str = (
        f" vsRandom(mean={baseline.mean_random_expectancy_r:.3f}, edge={baseline.edge_over_random:.3f})"
        if baseline is not None else " vsRandom=n/a"
    )
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{ci_str}{base_str}"


def format_report(results: list[dict[str, object]]) -> str:
    lines = ["=== REPAIR_BREAKOUT_QUALITY v1.0.0 -- Vatican Independent Verification ===", ""]
    for r in results:
        if "error" in r:
            lines.append(f"{r['asset']}: SKIPPED -- {r['error']}")
            lines.append("")
            continue
        lines.append(f"--- {r['asset']} ({r['hourly_source']}, {r['hourly_candle_count']} 1h candles, last <= 3 years) ---")
        primary = r["grid_results"][0]
        lines.append(f"  4H grid, offset+0h (primary): {primary['date_range']} ({primary['candle_count']} candles)")
        lines.append(f"    TRAIN {_fmt_half(primary['train'])}")
        lines.append(f"    TEST  {_fmt_half(primary['test'])}")
        lines.append(f"    raw verdict: {r['raw_verdict']}")
        for offset in (1, 2, 3):
            g = r["grid_results"].get(offset, {})
            if "error" in g:
                lines.append(f"  4H grid, offset+{offset}h: SKIPPED -- {g['error']}")
                continue
            q = "QUALIFIES" if g["qualifies"] else "does not qualify"
            lines.append(
                f"  4H grid, offset+{offset}h: {q} -- TRAIN {_fmt_half(g['train'], light=True)} | "
                f"TEST {_fmt_half(g['test'], light=True)}"
            )
        if r.get("grid_shift_note"):
            lines.append(f"  note: {r['grid_shift_note']}")
        lines.append(f"  FINAL VERDICT: {r['verdict']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_full_sweep()
    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
