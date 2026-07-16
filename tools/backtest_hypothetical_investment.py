"""CLI: simulate a specific hypothetical investment — "if $X had been invested N days ago
using strategy Y on asset Z" — and report the trade-by-trade equity progression.

Indicators are warmed up over the FULL available history (so MA200 etc. are already valid
at the simulation's start date — this is genuinely available historical data, not
lookahead). But the simulated account only starts existing, and can only open its first
trade, at the first evaluable candle on or after the cutoff date. Any trade still open at
the most recent candle is reported as OPEN/unresolved, never given a fabricated outcome.

Usage:
    python tools/backtest_hypothetical_investment.py --asset GOLD --timeframe 1week \
        --variant breakout_momentum_gold_calibrated_1week --starting-equity 2000 --lookback-days 365
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, VARIANT_SPECS

LARGE_CANDLE_REQUEST = 20_000  # request enough for full available history / proper indicator warmup


@dataclass(frozen=True)
class TradeRecord:
    entry_date: pd.Timestamp
    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    risk_dollars: float
    exit_date: pd.Timestamp
    exit_reason: str
    net_pnl: float
    r_multiple: float
    equity_after: float


def run_hypothetical_investment(
    asset: str,
    timeframe: str,
    variant_key: str,
    starting_equity: float,
    lookback_days: int,
    client: MarketDataClient,
    now: datetime | None = None,
) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    spec = VARIANT_SPECS[variant_key]
    result = client.load_intraday(asset, interval=timeframe, candles=LARGE_CANDLE_REQUEST)
    enriched = spec.add_indicators_fn(result.prices, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)

    eligible = evaluable[evaluable["date"] >= pd.Timestamp(cutoff)]
    if eligible.empty:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "variant": spec.label,
            "source": result.source,
            "error": f"No evaluable candles on or after cutoff {cutoff.date()} (data ends {evaluable['date'].max() if not evaluable.empty else 'n/a'}).",
        }
    start_index = int(eligible.index[0])

    state = MeanReversionState(equity=starting_equity)
    trades: list[TradeRecord] = []
    pending_entry: dict[str, object] | None = None

    for i in range(start_index, len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        trade_before_exit = state.open_trade
        exit_event = evaluate_exit(candle, state, spec.params)
        if exit_event is not None and pending_entry is not None:
            trades.append(
                TradeRecord(
                    entry_date=pending_entry["entry_date"],
                    entry_price=trade_before_exit.entry_price,
                    stop_loss=trade_before_exit.stop_loss,
                    target=trade_before_exit.target,
                    quantity=trade_before_exit.quantity,
                    risk_dollars=trade_before_exit.risk_dollars,
                    exit_date=candle["date"],
                    exit_reason=exit_event.exit_reason,
                    net_pnl=exit_event.net_pnl,
                    r_multiple=exit_event.r_multiple,
                    equity_after=state.equity,
                )
            )
            pending_entry = None

        evaluation = spec.evaluate_entry_fn(candle, evaluable.iloc[: i + 1], None, state, spec.params, asset)
        if evaluation.passed:
            new_trade = spec.size_entry_fn(candle, state, spec.params)
            if new_trade is not None:
                state.open_trade = new_trade
                pending_entry = {"entry_date": candle["date"]}

    open_trade_summary = None
    if state.open_trade is not None:
        open_trade_summary = {
            "entry_date": pending_entry["entry_date"] if pending_entry else None,
            "entry_price": state.open_trade.entry_price,
            "stop_loss": state.open_trade.stop_loss,
            "target": state.open_trade.target,
            "quantity": state.open_trade.quantity,
            "risk_dollars": state.open_trade.risk_dollars,
            "status": "OPEN as of the most recent available candle — no outcome yet, not fabricated",
        }

    return {
        "asset": asset,
        "timeframe": timeframe,
        "variant": spec.label,
        "source": result.source,
        "starting_equity": starting_equity,
        "final_equity": state.equity,
        "total_return_pct": (state.equity / starting_equity - 1.0) * 100.0,
        "window_start": evaluable.iloc[start_index]["date"],
        "window_end": evaluable.iloc[-1]["date"],
        "candles_in_window": len(evaluable) - start_index,
        "trades": trades,
        "open_trade": open_trade_summary,
    }


def format_report(report: dict[str, object]) -> str:
    if "error" in report:
        return f"{report['asset']} / {report['timeframe']} / {report['variant']}: {report['error']}"

    lines: list[str] = []
    lines.append(f"Asset: {report['asset']}   Timeframe: {report['timeframe']}   Variant: {report['variant']}")
    lines.append(f"Source: {report['source']}")
    lines.append(f"Simulation window: {report['window_start'].date()} to {report['window_end'].date()} ({report['candles_in_window']} candles)")
    lines.append(f"Starting equity: ${report['starting_equity']:.2f}")
    lines.append("")
    header = f"{'#':>3} {'Entry Date':<12} {'Entry $':>10} {'Stop $':>10} {'Target $':>10} {'Exit Date':<12} {'Reason':<8} {'NetPnL':>10} {'R':>7} {'Equity After':>13}"
    lines.append(header)
    lines.append("-" * len(header))
    for idx, t in enumerate(report["trades"], start=1):
        lines.append(
            f"{idx:>3} {t.entry_date.date()!s:<12} {t.entry_price:>10.2f} {t.stop_loss:>10.2f} {t.target:>10.2f} "
            f"{t.exit_date.date()!s:<12} {t.exit_reason:<8} {t.net_pnl:>10.2f} {t.r_multiple:>7.3f} {t.equity_after:>13.2f}"
        )
    if not report["trades"]:
        lines.append("(no closed trades in this window)")
    if report["open_trade"] is not None:
        ot = report["open_trade"]
        lines.append("")
        lines.append(
            f"OPEN at end of window: entered {ot['entry_date'].date() if ot['entry_date'] is not None else 'n/a'} "
            f"@ {ot['entry_price']:.2f}, stop {ot['stop_loss']:.2f}, target {ot['target']:.2f}, "
            f"risk ${ot['risk_dollars']:.2f} — {ot['status']}"
        )
    lines.append("")
    lines.append(f"Final equity: ${report['final_equity']:.2f}")
    lines.append(f"Total return: {report['total_return_pct']:+.2f}%")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="GOLD")
    parser.add_argument("--timeframe", default="1week")
    parser.add_argument("--variant", default="breakout_momentum_gold_calibrated_1week", choices=list(VARIANT_SPECS))
    parser.add_argument("--starting-equity", type=float, default=2000.0)
    parser.add_argument("--lookback-days", type=int, default=365)
    args = parser.parse_args()

    client = MarketDataClient()
    report = run_hypothetical_investment(
        args.asset, args.timeframe, args.variant, args.starting_equity, args.lookback_days, client
    )
    print(format_report(report))


if __name__ == "__main__":
    main()
