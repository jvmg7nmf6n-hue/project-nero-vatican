"""LEADLAG_FOLLOW — built only because H5's Bonferroni-corrected Granger causality test
(tools/granger_leadlag_test.py) found 7 significant BTC-to-alt pairs. Entry: go long the
alt when BTC's own candle `lag` periods ago (the pair's specific detected Granger lag)
showed a >1x-ATR up-move (BTC's own ATR, on BTC's own candle). Exit: standard ATR
stop/target, timeframe-aware holding cap — reuses nero_core.strategies.mean_reversion.
evaluate_exit unchanged (this strategy's OpenTrade is a plain long position on the alt;
only the entry TRIGGER comes from a second asset's data).

`lag` has no single correct default — it is the specific value detected per (alt,
timeframe) pair by the Granger test, and is expected to be overridden via
dataclasses.replace() per pair/timeframe, exactly like GOLD fee calibration or
timeframe-aware holding caps elsewhere in this codebase. The registered v1.0.0 uses
lag=3 (the median of the 7 significant pairs) purely as a placeholder so the strategy
has a well-defined registered identity; no real backtest should use that placeholder
uncritically — always pass the pair's own detected lag.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import (
    MeanReversionState,
    apply_slippage,
    atr,
    evaluate_exit,
    reset_daily_guard_if_needed,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "LEADLAG_FOLLOW"
STRATEGY_VERSION = "leadlag-follow-v1.0.0"

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

STRATEGY_DESCRIPTION = (
    "Built only because H5's Bonferroni-corrected Granger causality test found a "
    "significant BTC-to-alt lead-lag relationship (tools/granger_leadlag_test.py). "
    "Long-only: enter the alt when BTC's own candle `lag` periods ago showed a >1x-ATR "
    "up-move (BTC's own ATR, computed on BTC's own candles). Exit: 1.5x ATR stop, 2.0x "
    "ATR target (on the ALT's own ATR), timeframe-aware max holding — reuses "
    "nero_core.strategies.mean_reversion.evaluate_exit unchanged. `lag` is pair-specific "
    "(see this module's docstring) — the registered default is a documented placeholder, "
    "not a value to backtest against blindly."
)


@dataclass(frozen=True)
class LeadLagFollowParameters:
    lag: int = 3  # placeholder — see module docstring; always override per pair
    atr_period: int = 14
    atr_stop_multiple: float = 1.5
    atr_target_multiple: float = 2.0
    # 1h-reference default — see nero_core.strategies.timeframe_calibration.
    # build_calibrated_params for the per-timeframe re-derivation any real backtest run
    # must use instead of this raw value.
    max_holding_hours: int = 24
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = LeadLagFollowParameters()


@dataclass
class OpenTrade:
    """Duck-types against mean_reversion.evaluate_exit's needs: open_close_time,
    stop_loss, target, quantity, entry_price, entry_fee, risk_dollars."""

    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    entry_btc_move: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    atr: float
    btc_lagged_up_move: bool | None


def align_leadlag_candles(x_candles: pd.DataFrame, y_candles: pd.DataFrame, x_name: str, y_name: str) -> pd.DataFrame:
    """Inner-join two single-asset candle frames on close_time, keeping FULL OHLCV for
    both (prefixed by asset name) — LEADLAG_FOLLOW needs BTC's own high/low/close (for
    its ATR and up-move detection) as well as the alt's (for standard ATR stop/target
    sizing and exit), unlike COINTEGRATION_PAIRS' align_pair_candles which only needs
    closes. Only candles present in BOTH series survive."""
    x = x_candles[["close_time", "date"] + OHLCV_COLUMNS].rename(columns={c: f"{x_name}_{c}" for c in OHLCV_COLUMNS})
    y = y_candles[["close_time"] + OHLCV_COLUMNS].rename(columns={c: f"{y_name}_{c}" for c in OHLCV_COLUMNS})
    merged = x.merge(y, on="close_time", how="inner")
    return merged.sort_values("close_time").reset_index(drop=True)


def add_indicators(
    aligned: pd.DataFrame,
    params: LeadLagFollowParameters = DEFAULT_PARAMETERS,
    x_name: str = "BTC",
    y_name: str = "ALT",
) -> pd.DataFrame:
    """Attach BTC's own ATR/up-move flag (shifted back by `lag` onto the alt's current
    candle — no lookahead, since lag >= 1 and BTC/alt share the same close_time index)
    and the alt's own ATR. Also aliases the alt's OHLC to plain "open"/"high"/"low"/
    "close" columns so this module can reuse mean_reversion.evaluate_exit unchanged."""
    frame = aligned.copy().sort_values("close_time").reset_index(drop=True)

    x_ohlc = pd.DataFrame(
        {
            "high": frame[f"{x_name}_high"].astype(float),
            "low": frame[f"{x_name}_low"].astype(float),
            "close": frame[f"{x_name}_close"].astype(float),
        }
    )
    x_atr = atr(x_ohlc, params.atr_period)
    x_move = x_ohlc["close"].diff()
    x_up_move = x_move > x_atr

    frame["btc_atr"] = x_atr
    frame["btc_move"] = x_move
    # The alt's candle at index i checks BTC's flag from `lag` candles earlier — a
    # forward shift of a backward-looking flag, so row i only ever reflects information
    # from row i-lag (strictly in the past relative to i since lag >= 1).
    frame["btc_lagged_up_move"] = x_up_move.shift(params.lag)

    y_ohlc = pd.DataFrame(
        {
            "high": frame[f"{y_name}_high"].astype(float),
            "low": frame[f"{y_name}_low"].astype(float),
            "close": frame[f"{y_name}_close"].astype(float),
        }
    )
    frame["atr"] = atr(y_ohlc, params.atr_period)
    # Aliases so mean_reversion.evaluate_exit (which reads plain high/low/close) works
    # unchanged against this two-asset frame.
    frame["close"] = y_ohlc["close"]
    frame["high"] = y_ohlc["high"]
    frame["low"] = y_ohlc["low"]
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: LeadLagFollowParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Evaluate the lead-lag-follow rule set against one closed (alt) candle. Every
    rejection reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    btc_lagged_up_move = candle.get("btc_lagged_up_move")
    if pd.isna(btc_lagged_up_move) or not bool(btc_lagged_up_move):
        reasons.append("BTC_LAGGED_UP_MOVE_NOT_DETECTED")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=float(candle["close"]),
        atr=float(candle["atr"]),
        btc_lagged_up_move=None if pd.isna(btc_lagged_up_move) else bool(btc_lagged_up_move),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: LeadLagFollowParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional position sizing on the ALT: stop = 1.5x ATR, target = 2.0x ATR
    (both independent fixed ATR multiples, same convention as VOLATILITY_SQUEEZE/
    TREND_PULLBACK). Returns None if the risk/reward geometry is invalid — callers
    should only invoke this after `evaluate_entry` has passed."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    entry_atr = float(candle["atr"])
    stop_loss = entry_price - params.atr_stop_multiple * entry_atr
    target = entry_price + params.atr_target_multiple * entry_atr
    risk_per_unit = entry_price - stop_loss
    reward_per_unit = target - entry_price
    if risk_per_unit <= 0 or reward_per_unit <= 0:
        return None

    risk_dollars = state.equity * params.risk_per_trade
    quantity = risk_dollars / risk_per_unit
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * risk_per_unit
    fees = notional * params.fee_bps / 10000.0

    return OpenTrade(
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        quantity=quantity,
        notional=notional,
        risk_dollars=risk_dollars,
        entry_fee=fees,
        open_close_time=int(candle["close_time"]),
        entry_atr=entry_atr,
        entry_btc_move=float(candle.get("btc_move", float("nan"))),
    )


INDICATOR_COLUMNS_TO_CHECK = ["atr", "btc_atr", "btc_lagged_up_move"]


def run_leadlag_backtest(
    aligned: pd.DataFrame,
    params: LeadLagFollowParameters = DEFAULT_PARAMETERS,
    x_name: str = "BTC",
    y_name: str = "ALT",
) -> tuple[list, MeanReversionState]:
    """Candle-by-candle simulation over an already-aligned two-asset frame (see
    align_leadlag_candles). Reuses mean_reversion.evaluate_exit unchanged for exits."""
    state = MeanReversionState(equity=params.initial_equity)
    enriched = add_indicators(aligned, params, x_name, y_name)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    closed_trades: list = []

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the Lead-Lag Follow strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
