"""Shared EMA-trail exit mechanics for the H-series trail-exit A/B variants
(nero_core.strategies.trend_pullback_trail,
nero_core.strategies.breakout_momentum_gold_calibrated_1week_trail).

ARMED-TRAIL RULE (the reason this isn't just "exit when price crosses below the EMA"):
the trail only activates after the FIRST post-entry CLOSE strictly above the trail EMA.
Both underlying strategies are pullback/dip entries — the entry candle's own close sits
at or below the trailing MA/EMA by construction (that's the entry signal), so an
unarmed trail would exit the trade on the very next candle almost every time. Until
armed, ONLY the disaster stop applies. Arming is evaluated using each candle's own
close vs EMA and takes effect starting the NEXT candle — never the same candle it
armed on, and never the entry candle itself (the entry candle's own exit check, in the
standard per-candle backtest loop, happens on a PRIOR iteration before the trade
existed, so it can never fire an exit against the trade that opens on it).

Once armed, the trail is checked exactly like the disaster stop (an intrabar LOW touch
against the current level), just with the level being the EMA (recomputed every candle
from CLOSED data only, no lookahead) instead of a level fixed at entry. SL is checked
first when both would fire on the same candle, matching every other strategy's
stop-before-target priority convention in this codebase.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import apply_slippage


def add_ema_column(candles: pd.DataFrame, ema_period: int, column_name: str = "trail_ema") -> pd.DataFrame:
    """Standard EWM close, no lookahead: row i only ever uses closes up to and
    including i (pandas' ewm is inherently causal/backward-looking)."""
    frame = candles.copy()
    frame[column_name] = frame["close"].astype(float).ewm(span=ema_period, adjust=False).mean()
    return frame


@dataclass(frozen=True)
class TrailExitEvent:
    exit_reason: str  # "SL" or "TRAIL"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float
    exit_close_time: int


def evaluate_trail_exit(candle: pd.Series, state, ema_column: str, fee_bps: float, slippage_bps: float) -> TrailExitEvent | None:
    """Checks the open trade (duck-typed: entry_price, stop_loss, quantity, entry_fee,
    risk_dollars, open_close_time, trail_armed — a mutable field this function updates
    in place) against the disaster stop, then (only if already armed BEFORE this
    candle) the EMA trail. Arming for FUTURE candles is updated after resolving this
    candle's own exit outcome, using this candle's own close vs EMA — so a candle can
    arm the trail, or exit via SL/an already-armed TRAIL, but never "arm and exit on its
    own arming" in the same pass."""
    trade = state.open_trade
    if trade is None:
        return None

    low = float(candle["low"])
    close = float(candle["close"])
    ema = float(candle[ema_column])
    candle_time = int(candle["close_time"])

    if low <= trade.stop_loss:
        exit_reason, raw_exit = "SL", trade.stop_loss
    elif trade.trail_armed and low <= ema:
        exit_reason, raw_exit = "TRAIL", ema
    else:
        exit_reason, raw_exit = None, None

    if exit_reason is None:
        if not trade.trail_armed and close > ema:
            trade.trail_armed = True
        return None

    exit_price = apply_slippage(raw_exit, slippage_bps, "sell")
    quantity = trade.quantity
    gross_pnl = (exit_price - trade.entry_price) * quantity
    exit_fee = exit_price * quantity * fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r = state.daily_r + r_multiple
    state.open_trade = None

    return TrailExitEvent(
        exit_reason=exit_reason,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        holding_hours=hours_held,
        equity_after=equity_after,
        exit_close_time=candle_time,
    )
