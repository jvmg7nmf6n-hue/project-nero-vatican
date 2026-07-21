"""PEAD v1.0.0 — Three New Hypothesis Batch, Hypothesis 3 (Stocks).

MECHANISM: price drifts in the direction of an earnings surprise for days after
the announcement. Entry strictly AFTER the announcement — the first daily candle
whose own date is strictly later than the announcement timestamp.

DATA AUDIT (tools/pead_data_audit.py, docs/pead_data_audit.md) — HARD GATE
CLEARED: `nero_core.data_sources.earnings_data.fetch_earnings_surprises` (new
module, no such fetcher existed before this batch) confirmed EPS estimate/actual
+ surprise% available for all 7 tickers (56-99 resolved observations each, back
to 2001-2012 depending on the ticker's own history), and confirmed directly that
every announcement timestamp checked is hours before the earliest possible
next-trading-day open across the FULL history of every ticker — next-day-open
execution is lookahead-safe. SPY has no earnings of its own (confirmed) — it is
a benchmark only, never a PEAD signal ticker.

SURVIVOR-BIAS CAVEAT (see earnings_data.SURVIVOR_BIAS_CAVEAT, attached to every
report this strategy produces): the 7-ticker universe is large, currently-
successful companies by construction.

CONFIGS: rather than one hardcoded surprise threshold, {3%, 5%, 8%} x two holding
windows {5, 10 sessions} = 6 separate, explicitly versioned configs (see
strategy_version_for) — explores the drift structure instead of guessing one cut.
Every config is classified, none cherry-picked.

ENTRY: |surprise| >= threshold. Positive surprise -> LONG at next-day open;
negative -> SHORT at next-day open. One position per ticker at a time (an
overlapping earnings event while a position is still open from a PRIOR event is
skipped, not stacked).

EXIT: pure time-based drift test — held for exactly `holding_window_sessions`
sessions past entry, then closed at that session's close. A disaster stop
(2.0xATR(14), checked every session during the hold) can close it earlier as a
safety net; it is not the drift signal itself.

Event-driven (entries only occur on the sparse set of real earnings dates per
ticker, not every closed candle) — does not fit the single-asset per-candle
add_indicators/evaluate_entry/size_entry/VariantSpec shape used by continuously-
evaluated strategies. Its own self-contained backtest loop, reusing only
apply_slippage from mean_reversion.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import apply_slippage, atr as compute_atr
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "PEAD"

TICKERS = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN", "NVDA", "META"]
BENCHMARK_TICKER = "SPY"  # never traded -- see nero_core.data_sources.earnings_data

SURPRISE_THRESHOLDS_PCT = (0.03, 0.05, 0.08)
HOLDING_WINDOWS_SESSIONS = (5, 10)

STRATEGY_DESCRIPTION = (
    "Post-earnings-announcement drift: |surprise| >= threshold triggers LONG "
    "(positive surprise) or SHORT (negative surprise) at the next trading day's "
    "open, held for a fixed number of sessions (pure time-based exit) unless a "
    "2x ATR(14) disaster stop fires first. Fixed-fractional 0.5% risk per trade. "
    "Six configs (3 surprise thresholds x 2 holding windows), each independently "
    "classified, none cherry-picked. Survivor-bias caveat: the 7-ticker universe "
    "is large, currently-successful companies by construction."
)


def strategy_version_for(threshold_pct: float, holding_window_sessions: int) -> str:
    return f"pead-v1.0.0-surprise{int(round(threshold_pct * 100))}pct-hold{holding_window_sessions}"


@dataclass(frozen=True)
class PeadParameters:
    surprise_threshold_pct: float = 0.05
    holding_window_sessions: int = 5
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    risk_per_trade: float = 0.005
    initial_equity: float = 10000.0
    fee_bps: float = 10.0  # 0.1% per side
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = PeadParameters()


@dataclass
class OpenTrade:
    direction: str  # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    entry_index: int
    surprise_pct: float
    ticker: str


@dataclass
class PeadState:
    equity: float
    open_trade: OpenTrade | None = None


@dataclass(frozen=True)
class ExitEvent:
    ticker: str
    exit_reason: str  # "STOP" | "TIME"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    equity_after: float
    holding_sessions: int
    surprise_pct: float
    exit_close_time: int = 0


def add_atr(candles: pd.DataFrame, params: PeadParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    frame["atr"] = compute_atr(frame, params.atr_period)
    return frame


def _close_trade(
    trade: OpenTrade, exit_reason: str, raw_exit: float, state: PeadState, params: PeadParameters,
    sessions_held: int, close_time: int,
) -> ExitEvent:
    side = "sell" if trade.direction == "LONG" else "buy"
    exit_price = apply_slippage(raw_exit, params.slippage_bps, side)
    if trade.direction == "LONG":
        gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    else:
        gross_pnl = (trade.entry_price - exit_price) * trade.quantity
    exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl
    state.equity = equity_after
    state.open_trade = None

    return ExitEvent(
        ticker=trade.ticker, exit_reason=exit_reason, exit_price=exit_price, gross_pnl=gross_pnl, fees=total_fees,
        net_pnl=net_pnl, r_multiple=r_multiple, equity_after=equity_after, holding_sessions=sessions_held,
        surprise_pct=trade.surprise_pct, exit_close_time=close_time,
    )


def build_entry_plan(
    frame: pd.DataFrame, events: pd.DataFrame, params: PeadParameters = DEFAULT_PARAMETERS,
    direction_override: dict[pd.Timestamp, str] | None = None,
) -> dict[int, tuple[str, float]]:
    """Precomputes each qualifying event's own entry candle index (first candle
    strictly after the announcement) and direction -- multiple events mapping to
    the same entry_idx keep only the first encountered (chronological
    events.iterrows() order), matching "one position at a time" at the entry
    level too. `frame` must already be sorted by close_time with a reset index.

    `direction_override`: for the random-entry baseline ONLY -- maps an event's
    own announcement_time to a forced "LONG"/"SHORT" (ignoring the real surprise
    sign), so the same event-day/threshold/holding-window mechanics can be
    reused to test "does surprise DIRECTION carry the edge, vs just event-day
    volatility." None (the default) uses the real surprise-implied direction."""
    dates = frame["date"]
    entry_plan: dict[int, tuple[str, float]] = {}
    for event_time, row in events.iterrows():
        surprise_fraction = float(row["surprise_pct"]) / 100.0
        if abs(surprise_fraction) < params.surprise_threshold_pct:
            continue
        future_positions = frame.index[dates > event_time]
        if len(future_positions) == 0:
            continue
        entry_idx = int(future_positions[0])

        if direction_override is not None:
            direction = direction_override.get(event_time)
            if direction is None:
                continue
        else:
            direction = "LONG" if surprise_fraction > 0 else "SHORT"
        entry_plan.setdefault(entry_idx, (direction, surprise_fraction))
    return entry_plan


def _check_pead_exit(
    candle: dict | pd.Series, i: int, state: PeadState, params: PeadParameters, close_time: int,
) -> ExitEvent | None:
    """Shared exit-check step (STOP then TIME), reused by both
    run_pead_backtest_rows and nero_core.execution.replay.replay_pead_events so
    the live path can never silently diverge from the tested backtest logic.
    Mutates state (via _close_trade) and returns the ExitEvent if a position
    closed, else None. No-op if nothing is open."""
    trade = state.open_trade
    if trade is None:
        return None
    sessions_held = i - trade.entry_index
    low, high, close = float(candle["low"]), float(candle["high"]), float(candle["close"])
    exit_reason: str | None = None
    raw_exit: float | None = None
    if trade.direction == "LONG":
        if low <= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif sessions_held >= params.holding_window_sessions:
            exit_reason, raw_exit = "TIME", close
    else:
        if high >= trade.stop_loss:
            exit_reason, raw_exit = "STOP", trade.stop_loss
        elif sessions_held >= params.holding_window_sessions:
            exit_reason, raw_exit = "TIME", close
    if exit_reason is None:
        return None
    return _close_trade(trade, exit_reason, raw_exit, state, params, sessions_held, close_time)


def _try_open_pead_trade(
    candle: dict | pd.Series, i: int, n: int, entry_plan: dict[int, tuple[str, float]], ticker: str,
    state: PeadState, params: PeadParameters, close_time: int,
) -> OpenTrade | None:
    """Shared entry-opening step, reused by both run_pead_backtest_rows and
    nero_core.execution.replay.replay_pead_events. Mutates state.open_trade and
    returns the OpenTrade if one was opened, else None (no qualifying event at
    this candle, a position is already open, insufficient forward history, or
    invalid risk geometry)."""
    if state.open_trade is not None or i not in entry_plan:
        return None
    direction, surprise_fraction = entry_plan[i]
    if i + params.holding_window_sessions >= n:
        return None  # insufficient forward history -- discard, not counted either way

    atr_value = candle.get("atr")
    if atr_value is None or pd.isna(atr_value) or float(atr_value) <= 0:
        return None
    atr_value = float(atr_value)

    raw_entry = float(candle["open"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy" if direction == "LONG" else "sell")
    stop_distance = params.atr_stop_multiple * atr_value
    if stop_distance <= 0:
        return None
    stop_loss = entry_price - stop_distance if direction == "LONG" else entry_price + stop_distance

    risk_dollars = state.equity * params.risk_per_trade
    quantity = risk_dollars / stop_distance
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * stop_distance
    entry_fee = notional * params.fee_bps / 10000.0

    trade = OpenTrade(
        direction=direction, entry_price=entry_price, stop_loss=stop_loss, quantity=quantity,
        notional=notional, risk_dollars=risk_dollars, entry_fee=entry_fee,
        open_close_time=close_time, entry_atr=atr_value, entry_index=i,
        surprise_pct=surprise_fraction * 100.0, ticker=ticker,
    )
    state.open_trade = trade
    return trade


def run_pead_backtest_rows(
    rows: list[pd.Series], entry_plan: dict[int, tuple[str, float]], ticker: str, params: PeadParameters = DEFAULT_PARAMETERS,
) -> tuple[list[ExitEvent], PeadState]:
    """The actual per-candle chronological loop, taking PRE-EXTRACTED rows and an
    already-built entry_plan (see build_entry_plan) -- split out from
    run_pead_backtest so a caller re-running the same ticker/half many times (a
    random-entry baseline over N_RUNS) can pre-extract `rows` ONCE and rebuild
    only the (cheap, event-count-sized) entry_plan per run, never re-paying
    pandas' per-row .iloc construction cost on every run. One position per
    ticker at a time -- walks candles chronologically (like every other strategy
    in this project) rather than resolving each event's trade in isolation, so an
    event whose own entry candle falls while a PRIOR event's trade is still
    genuinely open (in calendar time) is correctly skipped, not just
    superficially guarded against."""
    state = PeadState(equity=params.initial_equity)
    closed_trades: list[ExitEvent] = []
    n = len(rows)

    for i, candle in enumerate(rows):
        close_time = int(candle["close_time"])
        exit_event = _check_pead_exit(candle, i, state, params, close_time)
        if exit_event is not None:
            closed_trades.append(exit_event)
        _try_open_pead_trade(candle, i, n, entry_plan, ticker, state, params, close_time)

    return closed_trades, state


def run_pead_backtest(
    candles: pd.DataFrame, events: pd.DataFrame, ticker: str, params: PeadParameters = DEFAULT_PARAMETERS,
    direction_override: dict[pd.Timestamp, str] | None = None,
) -> tuple[list[ExitEvent], PeadState]:
    """Public single-call API: sorts `candles`, builds the entry plan, extracts
    rows, and runs run_pead_backtest_rows once. `candles` is one ticker's own
    daily OHLCV+ATR (see add_atr). `events` is nero_core.data_sources.
    earnings_data.fetch_earnings_surprises's own output. Callers re-running the
    SAME ticker/half many times (a random-entry baseline) should instead
    pre-extract rows once and call build_entry_plan + run_pead_backtest_rows
    directly, to avoid re-paying the row-extraction cost on every run."""
    frame = candles.sort_values("close_time").reset_index(drop=True)
    entry_plan = build_entry_plan(frame, events, params, direction_override)
    # Plain dicts, not pandas Series -- run_pead_backtest_rows only ever does
    # dict-style [] / .get() access, which a plain dict serves several times
    # faster than a Series does, and to_dict("records") builds the whole list in
    # one vectorized pass instead of N individual .iloc constructions.
    rows = frame.to_dict("records")
    return run_pead_backtest_rows(rows, entry_plan, ticker, params)


def register_variant(threshold_pct: float, holding_window_sessions: int, registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register one (threshold, holding_window) PEAD config. Raises
    StrategyAlreadyRegisteredError if called twice for the same combination."""
    params = PeadParameters(surprise_threshold_pct=threshold_pct, holding_window_sessions=holding_window_sessions)
    version = strategy_version_for(threshold_pct, holding_window_sessions)
    return registry.register(strategy_id=STRATEGY_ID, version=version, parameters=asdict(params), description=STRATEGY_DESCRIPTION)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Registers the FIRST of the 6 configs (3% threshold, 5-session hold) as
    the nominal "default" for registry-discovery purposes matching every other
    strategy module's own register_default_variant contract -- all 6 configs are
    independently registerable via register_variant."""
    return register_variant(SURPRISE_THRESHOLDS_PCT[0], HOLDING_WINDOWS_SESSIONS[0], registry)
