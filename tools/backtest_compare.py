"""CLI: backtest Mean Reversion v1 vs v2 (regime-filtered) side by side over the same
real historical data, pulled live through nero_core.data_sources.market_data.

Usage:
    python tools/backtest_compare.py --assets BTC ETH SOL --interval 1h

No synthetic/fabricated price data is ever used here — if a market data fetch fails for
an asset, that asset is reported as SKIPPED with the reason, not silently substituted.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.mean_reversion import (
    DEFAULT_PARAMETERS as V1_PARAMETERS,
    ExitEvent,
    MeanReversionParameters,
    MeanReversionState,
    add_indicators,
    evaluate_entry as evaluate_entry_v1,
    evaluate_exit,
    reset_daily_guard_if_needed,
    size_entry,
)
from nero_core.strategies.mean_reversion_v2 import (
    DEFAULT_V2_PARAMETERS,
    MeanReversionV2Parameters,
    evaluate_entry_v2,
)

# Matches the "insufficient_sample" convention from the original agent's report_row().
MIN_SAMPLE_SIZE = 20

DEFAULT_ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR", "GOLD"]


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
    params: MeanReversionParameters,
    daily: pd.DataFrame | None = None,
    asset: str = "",
) -> tuple[list[ExitEvent], MeanReversionState]:
    """Runs one strategy variant candle-by-candle over closed intraday candles.

    If `daily` is provided (and `params` is a MeanReversionV2Parameters), entry uses
    evaluate_entry_v2 with an "as-of" slice of both the intraday and daily history —
    never the full fetched history — so no future candle can influence a past decision.
    If `daily` is None, entry uses the plain v1 evaluate_entry.
    """
    state = MeanReversionState(equity=params.initial_equity)
    enriched = add_indicators(intraday, params)
    evaluable = enriched.dropna(subset=["rsi", "bb_lower", "ma20", "ma200", "atr"]).reset_index(drop=True)
    closed_trades: list[ExitEvent] = []

    use_v2 = daily is not None and isinstance(params, MeanReversionV2Parameters)

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        if use_v2:
            as_of_intraday = evaluable.iloc[: i + 1]
            as_of_daily = daily[daily["close_time"] <= candle["close_time"]]
            evaluation = evaluate_entry_v2(candle, as_of_intraday, as_of_daily, state, params, asset=asset)
        else:
            evaluation = evaluate_entry_v1(candle, state, params)

        if evaluation.passed:
            trade = size_entry(candle, state, params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def compute_metrics(asset: str, variant: str, initial_equity: float, state: MeanReversionState, trades: list[ExitEvent]) -> BacktestMetrics:
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
    interval: str = "1h",
    intraday_candles: int = 500,
    daily_days: int = 400,
) -> dict[str, object]:
    intraday_result = client.load_intraday(asset, interval=interval, candles=intraday_candles)
    daily_result = client.load_daily(asset, days=daily_days)

    v1_trades, v1_state = run_backtest(intraday_result.prices, V1_PARAMETERS)
    v2_trades, v2_state = run_backtest(intraday_result.prices, DEFAULT_V2_PARAMETERS, daily=daily_result.prices, asset=asset)

    v1_metrics = compute_metrics(asset, "v1 (mean-reversion-v1.0.0)", V1_PARAMETERS.initial_equity, v1_state, v1_trades)
    v2_metrics = compute_metrics(asset, "v2 (mean-reversion-v2.0.0-regime-filtered)", DEFAULT_V2_PARAMETERS.initial_equity, v2_state, v2_trades)

    return {
        "asset": asset,
        "intraday_source": intraday_result.source,
        "intraday_candle_count": len(intraday_result.prices),
        "daily_source": daily_result.source,
        "daily_candle_count": len(daily_result.prices),
        "v1": v1_metrics,
        "v2": v2_metrics,
    }


def format_comparison_table(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    header = (
        f"{'Asset':<6} {'Variant':<40} {'Trades':>7} {'Win%':>7} {'ExpR':>8} "
        f"{'PF':>8} {'MaxDD':>8} {'NetPnL':>10}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for entry in results:
        for key in ("v1", "v2"):
            m: BacktestMetrics = entry[key]
            pf_display = f"{m.profit_factor:.2f}" if math.isfinite(m.profit_factor) else "inf"
            lines.append(
                f"{m.asset:<6} {m.variant:<40} {m.sample_size:>7} {m.win_rate * 100:>6.1f}% "
                f"{m.expectancy_r:>8.3f} {pf_display:>8} {m.max_drawdown * 100:>7.1f}% {m.net_pnl:>10.2f}"
            )
        for key in ("v1", "v2"):
            m: BacktestMetrics = entry[key]
            for note in m.notes:
                lines.append(f"    [{m.variant}] {note}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", default=DEFAULT_ASSETS)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--intraday-candles", type=int, default=500)
    parser.add_argument("--daily-days", type=int, default=400)
    args = parser.parse_args()

    client = MarketDataClient()
    results: list[dict[str, object]] = []
    for asset in args.assets:
        try:
            result = compare_asset(asset, client, args.interval, args.intraday_candles, args.daily_days)
            results.append(result)
            print(f"{asset}: OK — intraday {result['intraday_source']} ({result['intraday_candle_count']} candles), "
                  f"daily {result['daily_source']} ({result['daily_candle_count']} candles)")
        except MarketDataUnavailableError as exc:
            print(f"{asset}: SKIPPED — {exc}")

    print()
    if results:
        print(format_comparison_table(results))
    else:
        print("No assets produced usable data — nothing to compare.")


if __name__ == "__main__":
    main()
