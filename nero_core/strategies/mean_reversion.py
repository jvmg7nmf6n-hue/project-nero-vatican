from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import pandas as pd

from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "MEAN_REVERSION"
STRATEGY_VERSION = "mean-reversion-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Long-only mean reversion: RSI below 35, close below the lower Bollinger Band, "
    "close above MA200 (uptrend filter), MA20 frozen target above entry. Ported from "
    "the original NERO mean_reversion_agent.py decision logic (candle indicators, "
    "entry/exit rules, fixed fractional position sizing) — network fetching, JSON/CSV "
    "state persistence, and CLI orchestration are intentionally left for a later phase, "
    "once execution wiring goes through the Truth Ledger instead."
)


@dataclass(frozen=True)
class MeanReversionParameters:
    """Strategy behavior parameters — the exact defaults from the original agent."""

    rsi_period: int = 14
    rsi_entry_below: float = 35.0
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    ma200_period: int = 200
    atr_period: int = 14
    atr_stop_multiple: float = 1.5
    # Widens the "close below lower Bollinger Band" trigger by this many ATRs — entry is
    # allowed whenever close < bb_lower + lower_bb_buffer_atr * atr. Default 0.0 keeps the
    # original strict "close below the band itself" rule unchanged; > 0.0 is what the
    # ported NERO MR_RELAXED_PULLBACK_V1 candidate used to catch pullbacks that don't
    # quite touch the band (see mean_reversion_relaxed_pullback.py).
    lower_bb_buffer_atr: float = 0.0
    # "FROZEN_MA20" (default, original v1.0.0 behavior) or "FIXED_1R" (target = entry +
    # 1x risk-per-unit) — see mean_reversion_target_1r.py, ported from the NERO
    # MR_TARGET_1R_V1 candidate's target_mode field.
    target_mode: str = "FROZEN_MA20"
    max_holding_hours: int = 24
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = MeanReversionParameters()


@dataclass
class OpenTrade:
    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_rsi: float
    entry_ma20: float
    entry_bb_lower: float
    entry_ma200: float
    entry_atr: float


@dataclass
class MeanReversionState:
    equity: float
    daily_r: float = 0.0
    daily_guard_day: str | None = None
    open_trade: OpenTrade | None = None
    last_evaluated_close_time: int = 0


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    rsi: float
    ma20: float
    bb_lower: float
    ma200: float
    atr: float


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, math.nan)
    values = 100.0 - (100.0 / (1.0 + rs))
    return values.fillna(100.0)


def atr(frame: pd.DataFrame, period: int) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(period).mean()


def add_indicators(candles: pd.DataFrame, params: MeanReversionParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach rolling indicators to closed candles. No lookahead: every value at row i
    only uses candles up to and including i."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["ma20"] = close.rolling(params.bollinger_period).mean()
    bb_std = close.rolling(params.bollinger_period).std(ddof=0)
    frame["bb_lower"] = frame["ma20"] - params.bollinger_std * bb_std
    frame["ma200"] = close.rolling(params.ma200_period).mean()
    frame["rsi"] = rsi(close, params.rsi_period)
    frame["atr"] = atr(frame, params.atr_period)
    return frame


def apply_slippage(price: float, slippage_bps: float, side: str) -> float:
    factor = slippage_bps / 10000.0
    return price * (1.0 + factor) if side == "buy" else price * (1.0 - factor)


def reset_daily_guard_if_needed(state: MeanReversionState, candle_date: pd.Timestamp) -> None:
    day = pd.Timestamp(candle_date).date().isoformat()
    if state.daily_guard_day != day:
        state.daily_guard_day = day
        state.daily_r = 0.0


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: MeanReversionParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Evaluate the entry rule set against one closed candle. Every rejection reason is
    reported, not just the first, so the caller can log a full audit trail even when no
    trade is opened."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")
    if float(candle["rsi"]) >= params.rsi_entry_below:
        reasons.append("RSI_NOT_BELOW_35")
    relaxed_bb_threshold = float(candle["bb_lower"]) + params.lower_bb_buffer_atr * float(candle["atr"])
    if float(candle["close"]) >= relaxed_bb_threshold:
        reasons.append("CLOSE_NOT_BELOW_LOWER_BB")
    if float(candle["close"]) <= float(candle["ma200"]):
        reasons.append("CLOSE_NOT_ABOVE_MA200")
    if params.target_mode == "FROZEN_MA20" and float(candle["ma20"]) <= float(candle["close"]):
        reasons.append("TARGET_NOT_ABOVE_ENTRY")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=float(candle["close"]),
        rsi=float(candle["rsi"]),
        ma20=float(candle["ma20"]),
        bb_lower=float(candle["bb_lower"]),
        ma200=float(candle["ma200"]),
        atr=float(candle["atr"]),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: MeanReversionParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional position sizing: risk `risk_per_trade` of equity per trade, ATR
    stop, MA20 as a frozen target. Returns None if the risk/reward geometry is invalid
    (non-positive risk or reward per unit) — callers should only invoke this after
    `evaluate_entry` has passed."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    stop_loss = entry_price - params.atr_stop_multiple * float(candle["atr"])
    risk_per_unit = entry_price - stop_loss
    if risk_per_unit <= 0:
        return None
    target = entry_price + risk_per_unit if params.target_mode == "FIXED_1R" else float(candle["ma20"])
    reward_per_unit = target - entry_price
    if reward_per_unit <= 0:
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
        entry_rsi=float(candle["rsi"]),
        entry_ma20=float(candle["ma20"]),
        entry_bb_lower=float(candle["bb_lower"]),
        entry_ma200=float(candle["ma200"]),
        entry_atr=float(candle["atr"]),
    )


def evaluate_exit(
    candle: pd.Series,
    state: MeanReversionState,
    params: MeanReversionParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Check the open trade (if any) against stop-loss, target, and max-holding-hours,
    in that priority order when a candle's range hits both stop and target. Mutates
    `state` (equity, daily_r, open_trade) in place when a trade is closed, mirroring the
    original agent's per-candle state evolution."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    stop_loss = trade.stop_loss
    target = trade.target
    low = float(candle["low"])
    high = float(candle["high"])
    close = float(candle["close"])

    if low <= stop_loss and high >= target:
        exit_reason, raw_exit = "SL", stop_loss
    elif low <= stop_loss:
        exit_reason, raw_exit = "SL", stop_loss
    elif high >= target:
        exit_reason, raw_exit = "TARGET", target
    elif hours_held >= params.max_holding_hours:
        exit_reason, raw_exit = "TIME", close
    else:
        return None

    exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
    quantity = trade.quantity
    gross_pnl = (exit_price - trade.entry_price) * quantity
    exit_fee = exit_price * quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r = state.daily_r + r_multiple
    state.open_trade = None

    return ExitEvent(
        exit_reason=exit_reason,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        holding_hours=hours_held,
        equity_after=equity_after,
    )


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the Mean Reversion strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry — changing these
    parameters means bumping STRATEGY_VERSION and registering that new version instead."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
