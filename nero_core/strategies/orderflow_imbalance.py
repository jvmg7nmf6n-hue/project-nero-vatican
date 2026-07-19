"""ORDERFLOW_IMBALANCE v1.0.0 — EXPERIMENTAL, snapshot-based, forward-testing only, NO
BACKTEST EXISTS. Comprehensive Asset Expansion, Part C: Crypto, Task C1.

Binance's public order-book REST endpoint (nero_core.data_sources.orderbook_data) has
no historical replay — a depth snapshot is only ever "right now." That means, unlike
every other strategy in this codebase, there is no past to backtest against at all:
every result this strategy ever produces comes from live forward-testing starting the
moment it's wired into the scheduler, never from a historical simulation. This is the
exact wording that must accompany it everywhere (see
nero_core/execution/verification_status.py): "experimental — snapshot-based,
forward-testing only, no backtest exists."

RULE: LONG when imbalance_ratio (sum of bid volume / sum of ask volume, top 20 levels)
> entry_ratio_long (3.0) AND the latest closed 1h candle's close is above its MA20.
Mirrored SHORT when imbalance_ratio < entry_ratio_short (0.33) AND close < MA20. Exit:
imbalance_ratio crosses back through exit_ratio_long (1.5) / exit_ratio_short (0.67),
or a 2x-ATR(14, 1h) disaster stop, whichever comes first. Fixed-fractional 0.5% risk
per trade. BTC and ETH only, paper-tracking (Vatican never places real orders).

STATE, without a candle series to replay from: every other strategy in this codebase
reconstructs its running state by replaying candles from an inception timestamp (see
nero_core.execution.replay). That's not possible here — an order-book snapshot has no
history to replay. Instead, "am I in a position" is reconstructed each scheduler run
directly from the Truth Ledger's own execution_log: if the most recently logged
ORDERFLOW_IMBALANCE signal for this asset is an ENTRY with no later EXIT, a position
is open (direction and stop_loss are recovered from that ENTRY row's reasoning text,
the same "encode it in the reasoning string" convention nero_core.execution.
notify_ntfy already uses for r_multiple — see live_scheduler.py's
_reconstruct_open_position). Position sizing uses a fixed reference equity
(DEFAULT_PARAMETERS.initial_equity) rather than a running equity curve, since there is
no persisted account object to carry a real equity balance between runs for a
strategy with no backtest-style state machine — a known, documented simplification,
not an oversight.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "ORDERFLOW_IMBALANCE"
STRATEGY_VERSION = "orderflow-imbalance-v1.0.0"

STRATEGY_DESCRIPTION = (
    "EXPERIMENTAL — snapshot-based, forward-testing only, no backtest exists (Binance's "
    "public order-book REST endpoint has no historical replay, so there is no past to "
    "backtest against). LONG when the order-book depth imbalance_ratio (sum of bid "
    "volume / sum of ask volume, top 20 levels) exceeds 3.0 AND the latest closed 1h "
    "candle's close is above its MA20. Mirrored SHORT when ratio < 0.33 AND close < "
    "MA20. Exit: ratio crosses back through 1.5 (long) / 0.67 (short), or a 2x-ATR(14, "
    "1h) disaster stop, whichever comes first. Fixed-fractional 0.5% risk per trade. "
    "BTC and ETH only, paper-tracking (Vatican never places real orders)."
)


@dataclass(frozen=True)
class OrderflowImbalanceParameters:
    entry_ratio_long: float = 3.0
    entry_ratio_short: float = 1.0 / 3.0  # 0.33, the exact mirror of 3.0
    exit_ratio_long: float = 1.5
    exit_ratio_short: float = 2.0 / 3.0  # 0.67, the exact mirror of 1.5
    ma_period: int = 20
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.005  # 0.5%
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = OrderflowImbalanceParameters()


@dataclass(frozen=True)
class OrderflowIndicators:
    """The already-closed-1h-candle inputs this strategy needs — computed by the
    caller from ordinary OHLCV (this module has no opinion on how they were fetched,
    only what it does with them)."""

    close: float
    ma20: float
    atr: float


@dataclass(frozen=True)
class OpenPosition:
    direction: str  # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    direction: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    exit_reason: str | None  # "RATIO_REVERSAL" | "STOP"


def evaluate_entry(
    imbalance_ratio: float | None,
    indicators: OrderflowIndicators,
    has_open_position: bool,
    params: OrderflowImbalanceParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Every rejection reason is reported, not just the first. imbalance_ratio=None
    (the order book's ask_vol_20 was zero — a genuinely undefined ratio, see
    orderbook_data.py) always rejects; it is never treated as an extreme value in
    either direction."""
    reasons: list[str] = []
    if has_open_position:
        reasons.append("OPEN_POSITION_EXISTS")
    if imbalance_ratio is None:
        reasons.append("IMBALANCE_RATIO_UNDEFINED")
        return EntryEvaluation(passed=False, direction=None, reasons=tuple(reasons))

    direction: str | None = None
    if imbalance_ratio > params.entry_ratio_long and indicators.close > indicators.ma20:
        direction = "LONG"
    elif imbalance_ratio < params.entry_ratio_short and indicators.close < indicators.ma20:
        direction = "SHORT"
    if direction is None:
        reasons.append("NO_ENTRY_CONDITION_MET")

    passed = direction is not None and not reasons
    return EntryEvaluation(passed=passed, direction=direction if passed else None, reasons=tuple(reasons))


def size_entry(
    direction: str,
    close: float,
    atr: float,
    equity: float,
    params: OrderflowImbalanceParameters = DEFAULT_PARAMETERS,
) -> OpenPosition | None:
    """Fixed-fractional sizing against a 2x-ATR stop distance. Returns None if that
    distance isn't positive. `equity` is a fixed reference value (see module
    docstring's STATE section on why there's no running equity curve here)."""
    stop_distance = params.atr_stop_multiple * atr
    if stop_distance <= 0:
        return None
    stop_loss = close - stop_distance if direction == "LONG" else close + stop_distance

    risk_dollars = equity * params.risk_per_trade
    quantity = risk_dollars / stop_distance
    max_notional = equity * params.max_notional_pct
    notional = quantity * close
    if notional > max_notional:
        quantity = max_notional / close
        notional = max_notional
        risk_dollars = quantity * stop_distance
    fees = notional * params.fee_bps / 10000.0

    return OpenPosition(
        direction=direction, entry_price=close, stop_loss=stop_loss, quantity=quantity,
        notional=notional, risk_dollars=risk_dollars, entry_fee=fees,
    )


def evaluate_exit(
    position: OpenPosition,
    imbalance_ratio: float | None,
    indicators: OrderflowIndicators,
    params: OrderflowImbalanceParameters = DEFAULT_PARAMETERS,
) -> ExitDecision:
    """STOP is checked before RATIO_REVERSAL (priority matches every other strategy's
    "disaster stop first" convention). A None imbalance_ratio never triggers a ratio
    exit (it's undefined, not a value that could cross a threshold) — only the ATR
    stop can still fire that run."""
    if position.direction == "LONG":
        if indicators.close <= position.stop_loss:
            return ExitDecision(True, "STOP")
        if imbalance_ratio is not None and imbalance_ratio <= params.exit_ratio_long:
            return ExitDecision(True, "RATIO_REVERSAL")
    else:  # SHORT
        if indicators.close >= position.stop_loss:
            return ExitDecision(True, "STOP")
        if imbalance_ratio is not None and imbalance_ratio >= params.exit_ratio_short:
            return ExitDecision(True, "RATIO_REVERSAL")
    return ExitDecision(False, None)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register ORDERFLOW_IMBALANCE's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
