"""CARRY_MOMENTUM v1.0.0 — Three New Hypothesis Batch, Hypothesis 2 (Forex).

MECHANISM: hold the high-yield side of a currency pair for carry; a momentum
filter confirms the carry isn't unwinding (a rate differential means nothing if
the high-yield currency is actively depreciating against the low-yield one). A
small PORTFOLIO of up to 3 simultaneous carry positions is the normal, desired
mode — not a single forced pick.

DATA AUDIT (tools/carry_momentum_data_audit.py,
docs/carry_momentum_data_audit.md): FRED policy-rate/short-yield series verified
live for all 8 currencies (see nero_core/data_sources/fred_rates.py's module
docstring for the exact series IDs, why each was chosen, and the documented
bond-yield substitutions for 5 of 8 currencies with no daily FRED series). All 7
Twelve Data forex pairs confirmed accessible, native 1day, ~19 years history,
already aligned on close_time (unlike GOLD/SILVER's cross-vendor 4-hour offset —
these all come from the same Twelve Data vendor).

CARRY DIRECTION per pair: for pair (base, quote) [e.g. EUR/USD: base=EUR,
quote=USD], differential = rate[base] - rate[quote]. differential > 0 -> LONG the
pair (long base, short quote — base is the high-yield side). differential < 0 ->
SHORT the pair (short base, long quote — quote is the high-yield side, held by
being short the pair). |differential| is the ranking magnitude across all 7
pairs.

MOMENTUM FILTER: "high-yield leg close > SMA(50)" generalizes across both
directions via the PAIR'S OWN price: LONG candidates require pair_close > SMA50
(pair strengthening, consistent with the high-yield base currency); SHORT
candidates require pair_close < SMA50 (pair weakening, consistent with the
high-yield quote currency strengthening in the direction that profits a short).

PORTFOLIO: at each daily evaluation, rank pairs that pass BOTH the differential
sign check and the momentum filter by |differential| descending; take up to the
top 3 that aren't already open (max 3 concurrent, ~1.5% aggregate risk). If none
pass momentum, NO_SIGNAL for that day (existing open positions are still managed
independently). Entry executes at the NEXT candle's open (signal detected on
candle i, filled at i+1's open — the established closed-candle convention).

EXIT (per position, independent of every other open position): stop 2.0xATR(14)
of the PAIR'S OWN price; target 2.0x the stop distance (1:2 reward:risk); holding
cap 20 sessions (carry needs time to accrue — documented, not a bug).

Needs multiple aligned price series (7 pairs) PLUS 8 aligned/lagged rate series
at once — does not fit the single-asset add_indicators/evaluate_entry/size_entry/
VariantSpec shape (like COINTEGRATION_PAIRS and GOLD_SILVER_RATIO_MR before it).
Its own self-contained multi-position state machine and backtest loop, reusing
only apply_slippage/reset_daily_guard_if_needed from mean_reversion.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

import pandas as pd

from nero_core.data_sources.fred_rates import align_rate_to_daily_candles, lagged_usable_rate
from nero_core.strategies.mean_reversion import apply_slippage, atr as compute_atr, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "CARRY_MOMENTUM"
STRATEGY_VERSION = "carry-momentum-v1.0.0"

PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "NZD/USD", "USD/CAD"]
PAIR_BASE_QUOTE: dict[str, tuple[str, str]] = {
    "EUR/USD": ("EUR", "USD"), "GBP/USD": ("GBP", "USD"), "USD/JPY": ("USD", "JPY"),
    "USD/CHF": ("USD", "CHF"), "AUD/USD": ("AUD", "USD"), "NZD/USD": ("NZD", "USD"), "USD/CAD": ("USD", "CAD"),
}
CURRENCIES = sorted({c for pair in PAIRS for c in PAIR_BASE_QUOTE[pair]})  # USD, EUR, GBP, JPY, CHF, AUD, NZD, CAD

MAX_CONCURRENT_POSITIONS = 3

STRATEGY_DESCRIPTION = (
    "Forex carry portfolio: up to 3 simultaneous positions, ranked by |rate "
    "differential| (FRED policy rate / short-yield proxy, publication-lag "
    "buffered) among pairs whose high-yield side also passes a 50-session "
    "momentum filter (pair close beyond its own SMA50, direction-aware). Stop "
    "2x ATR(14), target 2x stop (1:2 RR), 20-session holding cap. Fixed-"
    "fractional 0.5% risk per position (~1.5% aggregate). Execution at the next "
    "candle's open."
)


@dataclass(frozen=True)
class CarryMomentumParameters:
    sma_period: int = 50
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    reward_multiple: float = 2.0  # target = reward_multiple * stop distance (1:2 RR)
    max_holding_sessions: int = 20
    max_concurrent_positions: int = MAX_CONCURRENT_POSITIONS
    risk_per_trade: float = 0.005
    initial_equity: float = 10000.0
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 5.0  # 0.05% per side
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = CarryMomentumParameters()


@dataclass
class CarryOpenPosition:
    pair: str
    direction: str  # "LONG" | "SHORT" (of the pair itself)
    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float


@dataclass
class CarryMomentumState:
    equity: float
    daily_r: float = 0.0
    daily_guard_day: str | None = None
    open_positions: dict[str, CarryOpenPosition] = field(default_factory=dict)
    # Duck-types the single-asset `open_trade` contract as "is anything open" for
    # reset_daily_guard_if_needed's own generic reuse (it only reads/writes
    # equity/daily_r/daily_guard_day, never open_trade) -- no change needed there.


@dataclass(frozen=True)
class CarryEvaluation:
    passed: bool
    direction: str | None
    differential: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ExitEvent:
    pair: str
    exit_reason: str  # "STOP" | "TARGET" | "TIME"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    equity_after: float
    holding_sessions: int
    exit_close_time: int = 0


def build_master_calendar(pair_candles: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Inner-joins all 7 pairs' close_time (confirmed directly, docs/
    carry_momentum_data_audit.md: all Twelve Data forex pairs share the same
    close_time convention, unlike GOLD/SILVER's cross-vendor mismatch — an exact
    join is correct here, not a date-based one). Columns are namespaced per pair:
    "{pair}_open"/"_high"/"_low"/"_close"."""
    base_pair = PAIRS[0]
    frame = pair_candles[base_pair][["close_time", "date"]].copy()
    for pair in PAIRS:
        candles = pair_candles[pair][["close_time", "open", "high", "low", "close"]].rename(
            columns={c: f"{pair}_{c}" for c in ("open", "high", "low", "close")}
        )
        frame = frame.merge(candles, on="close_time", how="inner")
    return frame.sort_values("close_time").reset_index(drop=True)


def add_indicators(
    master: pd.DataFrame, rate_series_by_currency: dict[str, tuple[pd.Series, str]], params: CarryMomentumParameters = DEFAULT_PARAMETERS,
) -> pd.DataFrame:
    """Attaches each pair's own SMA50/ATR14 and each currency's own lagged,
    forward-filled rate onto the master calendar. No lookahead: SMA/ATR are
    standard trailing-window rolling stats; rates are lag-shifted (see
    fred_rates.lagged_usable_rate) BEFORE being forward-filled onto this grid."""
    frame = master.copy().sort_values("close_time").reset_index(drop=True)
    for pair in PAIRS:
        close = frame[f"{pair}_close"].astype(float)
        frame[f"{pair}_sma50"] = close.rolling(params.sma_period).mean()
        ohlc = frame[["date", "close_time", f"{pair}_high", f"{pair}_low", f"{pair}_close"]].rename(
            columns={f"{pair}_high": "high", f"{pair}_low": "low", f"{pair}_close": "close"}
        )
        frame[f"{pair}_atr"] = compute_atr(ohlc, params.atr_period)

    for currency, (series, frequency) in rate_series_by_currency.items():
        lagged = lagged_usable_rate(series, frequency)
        frame = align_rate_to_daily_candles(frame, lagged, f"rate_{currency}")
    return frame


def evaluate_carry_signal(row: pd.Series, pair: str, params: CarryMomentumParameters = DEFAULT_PARAMETERS) -> CarryEvaluation:
    """Every rejection reason is reported, not just the first."""
    reasons: list[str] = []
    base, quote = PAIR_BASE_QUOTE[pair]
    rate_base = row.get(f"rate_{base}")
    rate_quote = row.get(f"rate_{quote}")
    close = row.get(f"{pair}_close")
    sma50 = row.get(f"{pair}_sma50")

    if any(v is None or pd.isna(v) for v in (rate_base, rate_quote, close, sma50)):
        reasons.append("INDICATORS_NOT_AVAILABLE")
        return CarryEvaluation(passed=False, direction=None, differential=None, reasons=tuple(reasons))

    differential = float(rate_base) - float(rate_quote)
    if differential > 0:
        direction = "LONG"
    elif differential < 0:
        direction = "SHORT"
    else:
        direction = None
        reasons.append("NO_RATE_DIFFERENTIAL")

    momentum_pass = False
    if direction == "LONG":
        momentum_pass = float(close) > float(sma50)
    elif direction == "SHORT":
        momentum_pass = float(close) < float(sma50)
    if direction is not None and not momentum_pass:
        reasons.append("MOMENTUM_FILTER_FAILED")
        direction = None

    passed = direction is not None and not reasons
    return CarryEvaluation(passed=passed, direction=direction if passed else None, differential=differential, reasons=tuple(reasons))


def size_entry(
    row: pd.Series, pair: str, direction: str, state: CarryMomentumState, params: CarryMomentumParameters = DEFAULT_PARAMETERS,
) -> CarryOpenPosition | None:
    """Entry executes at THIS candle's own open (the candle after the signal was
    detected) -- matches the established next-candle execution convention."""
    raw_entry = float(row[f"{pair}_open"])
    atr = row.get(f"{pair}_atr")
    if atr is None or pd.isna(atr) or float(atr) <= 0:
        return None
    atr = float(atr)

    side = "buy" if direction == "LONG" else "sell"
    entry_price = apply_slippage(raw_entry, params.slippage_bps, side)
    stop_distance = params.atr_stop_multiple * atr
    if stop_distance <= 0:
        return None

    if direction == "LONG":
        stop_loss = entry_price - stop_distance
        target = entry_price + params.reward_multiple * stop_distance
    else:
        stop_loss = entry_price + stop_distance
        target = entry_price - params.reward_multiple * stop_distance

    risk_dollars = state.equity * params.risk_per_trade
    quantity = risk_dollars / stop_distance
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * stop_distance
    entry_fee = notional * params.fee_bps / 10000.0

    return CarryOpenPosition(
        pair=pair, direction=direction, entry_price=entry_price, stop_loss=stop_loss, target=target,
        quantity=quantity, notional=notional, risk_dollars=risk_dollars, entry_fee=entry_fee,
        open_close_time=int(row["close_time"]), entry_atr=atr,
    )


def evaluate_exit(
    row: pd.Series, pair: str, state: CarryMomentumState, params: CarryMomentumParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Priority: STOP, then TARGET (tie-break to STOP if both hit the same
    candle), then TIME. holding_sessions is a placeholder here (0) -- the caller
    (run_backtest) knows the true candle-count and overwrites it via
    dataclasses.replace, since this function only sees one row at a time."""
    trade = state.open_positions.get(pair)
    if trade is None:
        return None

    close_time = int(row["close_time"])
    low = float(row[f"{pair}_low"])
    high = float(row[f"{pair}_high"])
    close = float(row[f"{pair}_close"])

    exit_reason: str | None = None
    raw_exit: float | None = None

    if trade.direction == "LONG":
        if low <= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif high >= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
        gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    else:  # SHORT
        if high >= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif low <= trade.target:
            exit_reason, raw_exit = "TARGET", trade.target
        else:
            return None
        exit_price = apply_slippage(raw_exit, params.slippage_bps, "buy")
        gross_pnl = (trade.entry_price - exit_price) * trade.quantity

    return _close_position(trade, pair, exit_reason, exit_price, gross_pnl, state, params, close_time)


def _check_time_exit(
    row: pd.Series, pair: str, state: CarryMomentumState, params: CarryMomentumParameters, sessions_held: int,
) -> ExitEvent | None:
    trade = state.open_positions.get(pair)
    if trade is None or sessions_held < params.max_holding_sessions:
        return None
    close_time = int(row["close_time"])
    close = float(row[f"{pair}_close"])
    exit_price = apply_slippage(close, params.slippage_bps, "sell" if trade.direction == "LONG" else "buy")
    if trade.direction == "LONG":
        gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    else:
        gross_pnl = (trade.entry_price - exit_price) * trade.quantity
    return _close_position(trade, pair, "TIME", exit_price, gross_pnl, state, params, close_time)


def _close_position(
    trade: CarryOpenPosition, pair: str, exit_reason: str, exit_price: float, gross_pnl: float,
    state: CarryMomentumState, params: CarryMomentumParameters, close_time: int,
) -> ExitEvent:
    exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r += r_multiple
    del state.open_positions[pair]

    return ExitEvent(
        pair=pair, exit_reason=exit_reason, exit_price=exit_price, gross_pnl=gross_pnl, fees=total_fees,
        net_pnl=net_pnl, r_multiple=r_multiple, equity_after=equity_after, holding_sessions=0, exit_close_time=close_time,
    )


def run_backtest(
    evaluable: pd.DataFrame, rate_series_by_currency: dict[str, tuple[pd.Series, str]] | None = None,
    params: CarryMomentumParameters = DEFAULT_PARAMETERS,
) -> tuple[list[ExitEvent], CarryMomentumState]:
    """`evaluable` must already carry every {pair}_sma50/{pair}_atr/rate_{currency}
    column (see add_indicators) and have had warmup-NaN rows dropped by the
    caller. rate_series_by_currency is unused here (indicators are already
    baked into `evaluable`) -- kept as an explicit parameter for call-site
    clarity/symmetry with add_indicators, not consumed."""
    state = CarryMomentumState(equity=params.initial_equity)
    closed_trades: list[ExitEvent] = []
    open_index: dict[str, int] = {}
    pending_entries: dict[str, str] = {}

    for i in range(len(evaluable)):
        row = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, row["date"])

        for pair, direction in list(pending_entries.items()):
            if pair not in state.open_positions and len(state.open_positions) < params.max_concurrent_positions:
                trade = size_entry(row, pair, direction, state, params)
                if trade is not None:
                    state.open_positions[pair] = trade
                    open_index[pair] = i
        pending_entries.clear()

        for pair in list(state.open_positions.keys()):
            sessions_held = i - open_index.get(pair, i)
            exit_event = evaluate_exit(row, pair, state, params)
            if exit_event is None:
                exit_event = _check_time_exit(row, pair, state, params, sessions_held)
            if exit_event is not None:
                exit_event = replace(exit_event, holding_sessions=sessions_held)
                closed_trades.append(exit_event)
                open_index.pop(pair, None)

        if len(state.open_positions) < params.max_concurrent_positions and state.daily_r > params.daily_loss_guard_r:
            candidates: list[tuple[float, str, str]] = []
            for pair in PAIRS:
                if pair in state.open_positions:
                    continue
                evaluation = evaluate_carry_signal(row, pair, params)
                if evaluation.passed:
                    candidates.append((abs(evaluation.differential), pair, evaluation.direction))
            candidates.sort(key=lambda c: c[0], reverse=True)
            slots_available = params.max_concurrent_positions - len(state.open_positions)
            for _, pair, direction in candidates[:slots_available]:
                pending_entries[pair] = direction

    return closed_trades, state


def carry_eligible_mask(evaluable: pd.DataFrame, pair: str) -> pd.Series:
    """The eligible pool for a random-entry baseline, per pair: candles where a
    momentum-passing carry candidate exists for THIS pair (regardless of whether
    it was actually ranked into the top 3 that day) -- isolates whether the
    RATE-DIFFERENTIAL RANKING adds value beyond just trading trending forex."""
    base, quote = PAIR_BASE_QUOTE[pair]
    rate_base = evaluable[f"rate_{base}"]
    rate_quote = evaluable[f"rate_{quote}"]
    close = evaluable[f"{pair}_close"]
    sma50 = evaluable[f"{pair}_sma50"]
    differential = rate_base - rate_quote
    long_ok = (differential > 0) & (close > sma50)
    short_ok = (differential < 0) & (close < sma50)
    return long_ok | short_ok


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register CARRY_MOMENTUM's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
