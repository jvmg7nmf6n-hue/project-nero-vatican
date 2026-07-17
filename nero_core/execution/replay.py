"""Deterministic, always-rederived-from-the-ledger replay for the live scheduler.

No mutable state (equity, open positions) is ever persisted between scheduler runs.
Instead, each run recomputes the account's full history from its own INCEPTION candle
(the earliest candle_timestamp ever logged to execution_log for this asset/strategy/
version — or, on the very first run ever, "the newest currently-closed candle," so a
fresh deployment never backfills a fake trading history) forward to the newest
currently-closed candle, using the exact same strategy mechanics as backtesting. Only
candles strictly AFTER the last-already-logged candle_timestamp are actually returned for
insertion — everything before that is replayed silently, purely to reconstruct `state`
correctly. This mirrors tools/backtest_hypothetical_investment.py's "state starts fresh
at a cutoff, not at the dawn of history" design, just anchored to the immutable ledger
(nero_core.truth_ledger.execution_log) instead of a lookback-days parameter — so there is
nothing to persist beyond the ledger itself, and a missed/delayed run self-heals on the
next one.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from nero_core.quant.quant_intelligence import engle_granger_cointegration
from nero_core.strategies.cointegration_pairs import (
    CointegrationPairsParameters,
    OpenTrade as PairsOpenTrade,
    PairsState,
    determine_entry_side,
    determine_exit_reason,
)
from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, evaluate_exit, reset_daily_guard_if_needed


@dataclass(frozen=True)
class ReplayEvent:
    candle_close_time: int  # epoch ms — matches close_time convention used across the codebase
    signal_type: str  # "ENTRY" | "EXIT" | "NO_TRADE"
    entry_price: float | None
    exit_price: float | None
    reasoning: str


def find_account_start_index(evaluable: pd.DataFrame, inception_close_time_ms: int | None) -> int | None:
    """Index of the first replay row. None (nothing to do) if `evaluable` is empty. If
    `inception_close_time_ms` is None (nothing logged yet for this account), the account
    starts at the NEWEST currently-closed row — a fresh deployment never backfills
    history as if it had been trading all along. Otherwise, starts at the row matching
    the account's own recorded inception timestamp exactly, falling back to the earliest
    available row if that exact candle has aged out of the fetched window (rare, only
    for a very long-lived account against a bounded fetch — documented in DESIGN.md)."""
    if evaluable.empty:
        return None
    if inception_close_time_ms is None:
        return len(evaluable) - 1
    matches = evaluable.index[evaluable["close_time"] == inception_close_time_ms]
    if len(matches) == 0:
        return 0
    return int(matches[0])


def replay_single_asset_events(
    evaluable: pd.DataFrame,
    spec,
    asset: str,
    inception_close_time_ms: int | None,
    already_logged_close_time_ms: int | None,
) -> tuple[list[ReplayEvent], MeanReversionState]:
    """Deterministically replays one single-asset strategy (a tools.backtest_compare.
    VariantSpec) from its account inception row to the newest evaluable row. Returns
    (new_events, final_state) where new_events covers only rows strictly after
    `already_logged_close_time_ms`."""
    start_index = find_account_start_index(evaluable, inception_close_time_ms)
    state = MeanReversionState(equity=spec.params.initial_equity)
    events: list[ReplayEvent] = []
    if start_index is None:
        return events, state

    for i in range(start_index, len(evaluable)):
        candle = evaluable.iloc[i]
        close_time = int(candle["close_time"])
        reset_daily_guard_if_needed(state, candle["date"])
        should_emit = already_logged_close_time_ms is None or close_time > already_logged_close_time_ms

        exit_event = evaluate_exit(candle, state, spec.params)
        if exit_event is not None and should_emit:
            events.append(
                ReplayEvent(
                    candle_close_time=close_time,
                    signal_type="EXIT",
                    entry_price=None,
                    exit_price=exit_event.exit_price,
                    reasoning=(
                        f"{exit_event.exit_reason} exit, r_multiple={exit_event.r_multiple:.3f}, "
                        f"net_pnl={exit_event.net_pnl:.2f}"
                    ),
                )
            )

        as_of = evaluable.iloc[: i + 1]
        evaluation = spec.evaluate_entry_fn(candle, as_of, None, state, spec.params, asset)
        if evaluation.passed:
            trade = spec.size_entry_fn(candle, state, spec.params)
            if trade is not None:
                state.open_trade = trade
                if should_emit:
                    events.append(
                        ReplayEvent(
                            candle_close_time=close_time,
                            signal_type="ENTRY",
                            entry_price=trade.entry_price,
                            exit_price=None,
                            reasoning=f"entry conditions satisfied ({spec.label})",
                        )
                    )
            elif should_emit:
                events.append(
                    ReplayEvent(
                        candle_close_time=close_time,
                        signal_type="NO_TRADE",
                        entry_price=None,
                        exit_price=None,
                        reasoning="entry conditions passed but position sizing produced invalid risk geometry",
                    )
                )
        elif should_emit:
            reasons = ", ".join(evaluation.reasons) if evaluation.reasons else "no entry"
            events.append(
                ReplayEvent(candle_close_time=close_time, signal_type="NO_TRADE", entry_price=None, exit_price=None, reasoning=reasons)
            )

    return events, state


def replay_pairs_events(
    evaluable: pd.DataFrame,
    params: CointegrationPairsParameters,
    x_name: str,
    y_name: str,
    inception_close_time_ms: int | None,
    already_logged_close_time_ms: int | None,
) -> tuple[list[ReplayEvent], PairsState]:
    """Deterministically replays COINTEGRATION_PAIRS the same way
    `replay_single_asset_events` does for single-asset strategies. Re-implements
    cointegration_pairs.run_pairs_backtest's per-row logic rather than calling it,
    because that function's return contract only exposes CLOSED trades, not the
    per-candle ENTRY/NO_TRADE events a live audit log needs."""
    start_index = find_account_start_index(evaluable, inception_close_time_ms)
    state = PairsState(equity=params.initial_equity)
    events: list[ReplayEvent] = []
    if start_index is None:
        return events, state

    for i in range(start_index, len(evaluable)):
        row = evaluable.iloc[i]
        close_time = int(row["close_time"])
        z = float(row["zscore"])
        should_emit = already_logged_close_time_ms is None or close_time > already_logged_close_time_ms

        if state.open_trade is not None:
            trade = state.open_trade
            price_now = float(row[f"{trade.asset}_close"])
            exit_reason = determine_exit_reason(trade.entry_side, z, params.exit_z, params.stop_z)
            if exit_reason is not None:
                exit_price = apply_slippage(price_now, params.slippage_bps, "sell")
                gross_pnl = (exit_price - trade.entry_price) * trade.quantity
                exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
                net_pnl = gross_pnl - trade.entry_fee - exit_fee
                state.equity += net_pnl
                state.open_trade = None
                if should_emit:
                    events.append(
                        ReplayEvent(
                            candle_close_time=close_time,
                            signal_type="EXIT",
                            entry_price=None,
                            exit_price=exit_price,
                            reasoning=f"{exit_reason} exit on {trade.asset} leg, net_pnl={net_pnl:.2f}",
                        )
                    )

        if state.open_trade is None:
            side = determine_entry_side(z, params.entry_z)
            if side == 0:
                if should_emit:
                    events.append(
                        ReplayEvent(
                            candle_close_time=close_time,
                            signal_type="NO_TRADE",
                            entry_price=None,
                            exit_price=None,
                            reasoning=f"|z|={abs(z):.2f} below entry threshold {params.entry_z}",
                        )
                    )
            else:
                asset = x_name if side == 1 else y_name
                window_start = max(0, i - params.window + 1)
                window_slice = evaluable.iloc[window_start : i + 1]
                result = engle_granger_cointegration(window_slice[f"{x_name}_close"], window_slice[f"{y_name}_close"])
                pvalue = result.get("adf_pvalue")
                confirmed = bool(result.get("cointegrated_at_5pct")) or (pvalue is not None and pvalue < params.adf_significance)
                if confirmed:
                    raw_entry = float(row[f"{asset}_close"])
                    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
                    notional = min(state.equity * params.notional_fraction, state.equity * params.max_notional_pct)
                    quantity = notional / entry_price
                    entry_fee = notional * params.fee_bps / 10000.0
                    state.open_trade = PairsOpenTrade(
                        asset=asset,
                        entry_side=side,
                        entry_price=entry_price,
                        quantity=quantity,
                        notional=notional,
                        entry_fee=entry_fee,
                        open_close_time=close_time,
                        entry_zscore=z,
                    )
                    if should_emit:
                        events.append(
                            ReplayEvent(
                                candle_close_time=close_time,
                                signal_type="ENTRY",
                                entry_price=entry_price,
                                exit_price=None,
                                reasoning=f"z={z:.2f} crossed entry threshold, cointegration confirmed, long {asset} leg",
                            )
                        )
                elif should_emit:
                    events.append(
                        ReplayEvent(
                            candle_close_time=close_time,
                            signal_type="NO_TRADE",
                            entry_price=None,
                            exit_price=None,
                            reasoning=f"z={z:.2f} crossed entry threshold but cointegration NOT confirmed at {params.adf_significance}",
                        )
                    )

    return events, state
