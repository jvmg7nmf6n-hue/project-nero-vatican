"""CLI: backtest one or more registered strategy variants side by side over the same
real historical data, pulled live through nero_core.data_sources.market_data.

Usage:
    python tools/backtest_compare.py --assets BTC ETH SOL --interval 1h
    python tools/backtest_compare.py --variants breakout_momentum --assets BTC
    python tools/backtest_compare.py --variants mean_reversion_v1 breakout_momentum

No synthetic/fabricated price data is ever used here — if a market data fetch fails for
an asset, that asset is reported as SKIPPED with the reason, not silently substituted.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.breakout_momentum import (
    DEFAULT_PARAMETERS as BREAKOUT_MOMENTUM_PARAMETERS,
)
from nero_core.strategies.breakout_momentum import add_indicators as bm_add_indicators
from nero_core.strategies.breakout_momentum import evaluate_entry as bm_evaluate_entry
from nero_core.strategies.breakout_momentum import size_entry as bm_size_entry
from nero_core.strategies.breakout_momentum_volume_confirmed import (
    PARAMETERS as BM_VOLUME_CONFIRMED_PARAMETERS,
)
from nero_core.strategies.mean_reversion import (
    DEFAULT_PARAMETERS as V1_PARAMETERS,
    MeanReversionState,
    add_indicators as mr_add_indicators,
    evaluate_entry as evaluate_entry_v1,
    evaluate_exit,
    reset_daily_guard_if_needed,
    size_entry as mr_size_entry,
)
from nero_core.strategies.mean_reversion_v2 import (
    DEFAULT_V2_PARAMETERS,
    evaluate_entry_v2,
)
from nero_core.strategies.mean_reversion_gold_calibrated import (
    GOLD_CALIBRATED_PARAMETERS as MR_GOLD_PARAMETERS,
)
from nero_core.strategies.breakout_momentum_gold_calibrated import (
    GOLD_CALIBRATED_PARAMETERS as BM_GOLD_PARAMETERS,
)
from nero_core.strategies.mean_reversion_gold_calibrated_1week import (
    GOLD_CALIBRATED_1WEEK_PARAMETERS as MR_GOLD_1WEEK_PARAMETERS,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import (
    GOLD_CALIBRATED_1WEEK_PARAMETERS as BM_GOLD_1WEEK_PARAMETERS,
)
from nero_core.strategies.volatility_squeeze import (
    DEFAULT_PARAMETERS_MA100 as VS_MA100_PARAMETERS,
    DEFAULT_PARAMETERS_MA150 as VS_MA150_PARAMETERS,
    DEFAULT_PARAMETERS_MA200 as VS_MA200_PARAMETERS,
)
from nero_core.strategies.volatility_squeeze import add_indicators as vs_add_indicators
from nero_core.strategies.volatility_squeeze import evaluate_entry as vs_evaluate_entry
from nero_core.strategies.volatility_squeeze import size_entry as vs_size_entry
from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS as TREND_PULLBACK_PARAMETERS
from nero_core.strategies.trend_pullback import add_indicators as tp_add_indicators
from nero_core.strategies.trend_pullback import evaluate_entry as tp_evaluate_entry
from nero_core.strategies.trend_pullback import size_entry as tp_size_entry
from nero_core.strategies.mean_reversion_relaxed_pullback import PARAMETERS as MR_RELAXED_PULLBACK_PARAMETERS
from nero_core.strategies.mean_reversion_deep_value import PARAMETERS as MR_DEEP_VALUE_PARAMETERS
from nero_core.strategies.mean_reversion_target_1r import PARAMETERS as MR_TARGET_1R_PARAMETERS
from nero_core.strategies.mean_reversion_regime_filter import PARAMETERS as MR_REGIME_FILTER_PARAMETERS

# Matches the "insufficient_sample" convention from the original agent's report_row().
MIN_SAMPLE_SIZE = 20

DEFAULT_ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR", "GOLD"]

# The volatility-regime filter only needs recent history to judge "current" conditions
# (build_garch_volatility_report's own EWMA fallback already only looks at the trailing
# 252 observations internally). Capping the as-of slice fed into it keeps each per-candle
# recompute O(1) instead of O(i) — turning a long backtest from O(n^2) into O(n) — without
# giving it access to anything it wouldn't otherwise use, and without introducing lookahead.
GARCH_LOOKBACK_CANDLES = 300

INDICATOR_COLUMNS_TO_CHECK = ["rsi", "bb_lower", "ma20", "ma200", "atr", "breakout_high", "trend_ma", "ma50"]


@dataclass(frozen=True)
class VariantSpec:
    """Everything the generic backtest loop needs to run one registered strategy variant.
    Each strategy family plugs in its own add_indicators/evaluate_entry/size_entry;
    evaluate_exit and reset_daily_guard_if_needed are genuinely shared across all of them
    (see nero_core.strategies.mean_reversion) since exit/state mechanics don't vary by
    entry family."""

    key: str
    label: str
    params: Any
    add_indicators_fn: Callable[[pd.DataFrame, Any], pd.DataFrame]
    # (candle, as_of_intraday, as_of_daily, state, params, asset) -> entry evaluation with a `.passed` attribute
    evaluate_entry_fn: Callable[[pd.Series, pd.DataFrame, pd.DataFrame, MeanReversionState, Any, str], Any]
    size_entry_fn: Callable[[pd.Series, MeanReversionState, Any], Any]
    needs_daily: bool


VARIANT_SPECS: dict[str, VariantSpec] = {
    "mean_reversion_v1": VariantSpec(
        key="mean_reversion_v1",
        label="MEAN_REVERSION v1 (mean-reversion-v1.0.0)",
        params=V1_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v1(candle, state, params),
        size_entry_fn=mr_size_entry,
        needs_daily=False,
    ),
    "mean_reversion_v2": VariantSpec(
        key="mean_reversion_v2",
        label="MEAN_REVERSION v2 (mean-reversion-v2.0.0-regime-filtered)",
        params=DEFAULT_V2_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v2(
            candle, as_of_intraday, as_of_daily, state, params, asset=asset
        ),
        size_entry_fn=mr_size_entry,
        needs_daily=True,
    ),
    "breakout_momentum": VariantSpec(
        key="breakout_momentum",
        label="BREAKOUT_MOMENTUM v1 (breakout-momentum-v1.0.0)",
        params=BREAKOUT_MOMENTUM_PARAMETERS,
        add_indicators_fn=bm_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: bm_evaluate_entry(candle, state, params),
        size_entry_fn=bm_size_entry,
        needs_daily=False,
    ),
    "mean_reversion_gold_calibrated": VariantSpec(
        key="mean_reversion_gold_calibrated",
        label="MEAN_REVERSION gold-calibrated (mean-reversion-v1.1.0-gold-calibrated)",
        params=MR_GOLD_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v1(candle, state, params),
        size_entry_fn=mr_size_entry,
        needs_daily=False,
    ),
    "breakout_momentum_gold_calibrated": VariantSpec(
        key="breakout_momentum_gold_calibrated",
        label="BREAKOUT_MOMENTUM gold-calibrated (breakout-momentum-v1.1.0-gold-calibrated)",
        params=BM_GOLD_PARAMETERS,
        add_indicators_fn=bm_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: bm_evaluate_entry(candle, state, params),
        size_entry_fn=bm_size_entry,
        needs_daily=False,
    ),
    "mean_reversion_gold_calibrated_1week": VariantSpec(
        key="mean_reversion_gold_calibrated_1week",
        label="MEAN_REVERSION gold-calibrated 1week (mean-reversion-v1.2.0-gold-calibrated-1week)",
        params=MR_GOLD_1WEEK_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v1(candle, state, params),
        size_entry_fn=mr_size_entry,
        needs_daily=False,
    ),
    "breakout_momentum_gold_calibrated_1week": VariantSpec(
        key="breakout_momentum_gold_calibrated_1week",
        label="BREAKOUT_MOMENTUM gold-calibrated 1week (breakout-momentum-v1.2.0-gold-calibrated-1week)",
        params=BM_GOLD_1WEEK_PARAMETERS,
        add_indicators_fn=bm_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: bm_evaluate_entry(candle, state, params),
        size_entry_fn=bm_size_entry,
        needs_daily=False,
    ),
    "volatility_squeeze_ma200": VariantSpec(
        key="volatility_squeeze_ma200",
        label="VOLATILITY_SQUEEZE ma200 (volatility-squeeze-v1.0.0-ma200)",
        params=VS_MA200_PARAMETERS,
        add_indicators_fn=vs_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: vs_evaluate_entry(candle, state, params),
        size_entry_fn=vs_size_entry,
        needs_daily=False,
    ),
    "volatility_squeeze_ma150": VariantSpec(
        key="volatility_squeeze_ma150",
        label="VOLATILITY_SQUEEZE ma150 (volatility-squeeze-v1.0.0-ma150)",
        params=VS_MA150_PARAMETERS,
        add_indicators_fn=vs_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: vs_evaluate_entry(candle, state, params),
        size_entry_fn=vs_size_entry,
        needs_daily=False,
    ),
    "volatility_squeeze_ma100": VariantSpec(
        key="volatility_squeeze_ma100",
        label="VOLATILITY_SQUEEZE ma100 (volatility-squeeze-v1.0.0-ma100)",
        params=VS_MA100_PARAMETERS,
        add_indicators_fn=vs_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: vs_evaluate_entry(candle, state, params),
        size_entry_fn=vs_size_entry,
        needs_daily=False,
    ),
    "trend_pullback": VariantSpec(
        key="trend_pullback",
        label="TREND_PULLBACK (trend-pullback-v1.0.0)",
        params=TREND_PULLBACK_PARAMETERS,
        add_indicators_fn=tp_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: tp_evaluate_entry(candle, state, params),
        size_entry_fn=tp_size_entry,
        needs_daily=False,
    ),
    "mean_reversion_relaxed_pullback": VariantSpec(
        key="mean_reversion_relaxed_pullback",
        label="MEAN_REVERSION relaxed-pullback (mean-reversion-v1.0.0-relaxed-pullback)",
        params=MR_RELAXED_PULLBACK_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v1(candle, state, params),
        size_entry_fn=mr_size_entry,
        needs_daily=False,
    ),
    "mean_reversion_deep_value": VariantSpec(
        key="mean_reversion_deep_value",
        label="MEAN_REVERSION deep-value (mean-reversion-v1.0.0-deep-value)",
        params=MR_DEEP_VALUE_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v1(candle, state, params),
        size_entry_fn=mr_size_entry,
        needs_daily=False,
    ),
    "mean_reversion_target_1r": VariantSpec(
        key="mean_reversion_target_1r",
        label="MEAN_REVERSION target-1r (mean-reversion-v1.0.0-target-1r)",
        params=MR_TARGET_1R_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v1(candle, state, params),
        size_entry_fn=mr_size_entry,
        needs_daily=False,
    ),
    "mean_reversion_regime_filter": VariantSpec(
        key="mean_reversion_regime_filter",
        label="MEAN_REVERSION regime-filter (mean-reversion-v1.0.0-regime-filter)",
        params=MR_REGIME_FILTER_PARAMETERS,
        add_indicators_fn=mr_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: evaluate_entry_v1(candle, state, params),
        size_entry_fn=mr_size_entry,
        needs_daily=False,
    ),
    "breakout_momentum_volume_confirmed": VariantSpec(
        key="breakout_momentum_volume_confirmed",
        label="BREAKOUT_MOMENTUM volume-confirmed (breakout-momentum-v1.4.0-volume-confirmed)",
        params=BM_VOLUME_CONFIRMED_PARAMETERS,
        add_indicators_fn=bm_add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, params, asset: bm_evaluate_entry(candle, state, params),
        size_entry_fn=bm_size_entry,
        needs_daily=False,
    ),
}

DEFAULT_VARIANTS = ["mean_reversion_v1", "mean_reversion_v2"]


@dataclass(frozen=True)
class BacktestMetrics:
    asset: str
    variant: str
    sample_size: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown: float
    net_pnl: float
    ending_equity: float
    insufficient_sample: bool
    notes: tuple[str, ...]


def run_backtest(
    intraday: pd.DataFrame,
    spec: VariantSpec,
    daily: pd.DataFrame | None = None,
    asset: str = "",
) -> tuple[list[Any], MeanReversionState]:
    """Runs one strategy variant candle-by-candle over closed intraday candles.

    If `spec.needs_daily` and `daily` is provided, entry evaluation gets an "as-of" slice
    of both the intraday and daily history — never the full fetched history — so no
    future candle can influence a past decision. Variants that don't need daily context
    (v1, breakout momentum) simply ignore the as-of slices their adapter receives.
    """
    state = MeanReversionState(equity=spec.params.initial_equity)
    enriched = spec.add_indicators_fn(intraday, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    closed_trades: list[Any] = []

    use_daily = spec.needs_daily and daily is not None

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, spec.params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        as_of_intraday = evaluable.iloc[max(0, i + 1 - GARCH_LOOKBACK_CANDLES) : i + 1] if use_daily else evaluable.iloc[: i + 1]
        as_of_daily = daily[daily["close_time"] <= candle["close_time"]] if use_daily else None
        evaluation = spec.evaluate_entry_fn(candle, as_of_intraday, as_of_daily, state, spec.params, asset)

        if evaluation.passed:
            trade = spec.size_entry_fn(candle, state, spec.params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def compute_metrics(asset: str, variant: str, state: MeanReversionState, trades: list[Any]) -> BacktestMetrics:
    sample_size = len(trades)
    if sample_size == 0:
        return BacktestMetrics(
            asset=asset,
            variant=variant,
            sample_size=0,
            win_rate=0.0,
            expectancy_r=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            net_pnl=0.0,
            ending_equity=state.equity,
            insufficient_sample=True,
            notes=("No trades were closed in this window.",),
        )

    pnls = [t.net_pnl for t in trades]
    r_values = [t.r_multiple for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    win_rate = len(wins) / sample_size
    expectancy_r = sum(r_values) / sample_size
    profit_factor = (gross_win / gross_loss) if gross_loss else (gross_win if gross_win else 0.0)
    max_dd = _max_drawdown([t.equity_after for t in trades])
    net_pnl = sum(pnls)

    notes: list[str] = []
    insufficient = sample_size < MIN_SAMPLE_SIZE
    if insufficient:
        notes.append(
            f"Sample size ({sample_size}) is below the {MIN_SAMPLE_SIZE}-trade threshold — "
            "treat these numbers as exploratory, not conclusive."
        )

    return BacktestMetrics(
        asset=asset,
        variant=variant,
        sample_size=sample_size,
        win_rate=win_rate,
        expectancy_r=expectancy_r,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        net_pnl=net_pnl,
        ending_equity=state.equity,
        insufficient_sample=insufficient,
        notes=tuple(notes),
    )


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = -math.inf
    drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, (value - peak) / peak)
    return drawdown


def compare_asset(
    asset: str,
    client: MarketDataClient,
    variant_keys: list[str],
    interval: str = "1h",
    intraday_candles: int = 500,
    daily_days: int = 400,
) -> dict[str, object]:
    intraday_result = client.load_intraday(asset, interval=interval, candles=intraday_candles)
    needs_daily = any(VARIANT_SPECS[key].needs_daily for key in variant_keys)
    daily_result = client.load_daily(asset, days=daily_days) if needs_daily else None

    metrics: dict[str, BacktestMetrics] = {}
    for key in variant_keys:
        spec = VARIANT_SPECS[key]
        daily_prices = daily_result.prices if (spec.needs_daily and daily_result is not None) else None
        trades, state = run_backtest(intraday_result.prices, spec, daily=daily_prices, asset=asset)
        metrics[key] = compute_metrics(asset, spec.label, state, trades)

    return {
        "asset": asset,
        "intraday_source": intraday_result.source,
        "intraday_candle_count": len(intraday_result.prices),
        "daily_source": daily_result.source if daily_result is not None else "not fetched (no selected variant needs it)",
        "daily_candle_count": len(daily_result.prices) if daily_result is not None else 0,
        "variant_keys": variant_keys,
        "metrics": metrics,
    }


def format_comparison_table(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    header = (
        f"{'Asset':<6} {'Variant':<45} {'Trades':>7} {'Win%':>7} {'ExpR':>8} "
        f"{'PF':>8} {'MaxDD':>8} {'NetPnL':>10}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for entry in results:
        metrics: dict[str, BacktestMetrics] = entry["metrics"]
        for key in entry["variant_keys"]:
            m = metrics[key]
            pf_display = f"{m.profit_factor:.2f}" if math.isfinite(m.profit_factor) else "inf"
            lines.append(
                f"{m.asset:<6} {m.variant:<45} {m.sample_size:>7} {m.win_rate * 100:>6.1f}% "
                f"{m.expectancy_r:>8.3f} {pf_display:>8} {m.max_drawdown * 100:>7.1f}% {m.net_pnl:>10.2f}"
            )
        for key in entry["variant_keys"]:
            m = metrics[key]
            for note in m.notes:
                lines.append(f"    [{m.variant}] {note}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", default=DEFAULT_ASSETS)
    parser.add_argument("--variants", nargs="+", default=DEFAULT_VARIANTS, choices=list(VARIANT_SPECS))
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--intraday-candles", type=int, default=500)
    parser.add_argument("--daily-days", type=int, default=400)
    args = parser.parse_args()

    client = MarketDataClient()
    results: list[dict[str, object]] = []
    for asset in args.assets:
        try:
            result = compare_asset(asset, client, args.variants, args.interval, args.intraday_candles, args.daily_days)
            results.append(result)
            print(f"{asset}: OK — intraday {result['intraday_source']} ({result['intraday_candle_count']} candles), "
                  f"daily {result['daily_source']} ({result['daily_candle_count']} candles)")
        except MarketDataUnavailableError as exc:
            print(f"{asset}: SKIPPED — {exc}")
        except Exception as exc:  # noqa: BLE001 - one asset's unexpected failure must not lose every other asset's already-computed results
            print(f"{asset}: FAILED — {exc.__class__.__name__}: {exc}")

    print()
    if results:
        print(format_comparison_table(results))
    else:
        print("No assets produced usable data — nothing to compare.")


if __name__ == "__main__":
    main()
