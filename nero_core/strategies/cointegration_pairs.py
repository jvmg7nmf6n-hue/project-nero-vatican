"""COINTEGRATION_PAIRS — statistical-arbitrage pairs strategy for BTC/ETH.

HONEST LIMITATION (also called out in every report this strategy feeds): this system is
long-only paper trading (see CLAUDE.md hard rule 2 — no short execution). A real pairs
trade is market-neutral: long the underperforming leg, SHORT the outperforming leg. Here
only the long leg is simulated — "half a pair trade." Its PnL reflects only that leg's own
price move between the z-score-triggered entry and exit, NOT the true hedged spread PnL a
real pairs trade would realize (no short-leg PnL, no short-leg fees/borrow cost are
modeled). Treat every backtest number from this strategy as a directional bet timed by a
pairs signal, not as a market-neutral arbitrage return.

Unlike every other strategy in this codebase, this one needs TWO aligned price series at
once, so it does not fit the single-asset add_indicators/evaluate_entry/size_entry/
VariantSpec shape used elsewhere — it has its own self-contained state machine and
backtest loop (run_pairs_backtest), reusing only apply_slippage from mean_reversion.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.quant.quant_intelligence import engle_granger_cointegration
from nero_core.strategies.mean_reversion import apply_slippage
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "COINTEGRATION_PAIRS"
STRATEGY_VERSION = "cointegration-pairs-v1.0.0"
PAIR = ("BTC", "ETH")  # (x, independent leg; y, dependent leg) — most liquid, longest shared history

STRATEGY_DESCRIPTION = (
    "Statistical-arbitrage pair BTC-ETH only. hedge_ratio is a ROLLING OLS slope "
    "(Cov(BTC,ETH)/Var(BTC) over the trailing `window` candles — mathematically the same "
    "closed-form estimate a single-regressor OLS fit produces, just recomputed every "
    "candle instead of once) so the spread (ETH - hedge_ratio*BTC) and its z-score stay "
    "current without refitting via statsmodels on every candle. The full Engle-Granger "
    "test (nero_core.quant.quant_intelligence.engle_granger_cointegration, including its "
    "ADF residual test) is invoked as a confirmation GATE only at the moment a z-score "
    "threshold is actually crossed and a trade is about to open — requiring "
    "cointegrated_at_5pct over that same trailing window before the signal is trusted. "
    "Entry: |z| >= entry_z (long BTC when z is high / ETH looks like the outperformer and "
    "BTC the laggard; long ETH when z is low / vice versa). Exit: z reverts to exit_z "
    "(default 0.0) or reaches +/- stop_z (default 3.0) on the SAME side as entry. "
    "LONG-LEG-ONLY — see this module's docstring for what that does and doesn't mean for "
    "the PnL numbers."
)


@dataclass(frozen=True)
class CointegrationPairsParameters:
    window: int = 200
    entry_z: float = 2.0
    exit_z: float = 0.0
    stop_z: float = 3.0
    adf_significance: float = 0.05
    initial_equity: float = 10000.0
    # Fraction of equity allocated as notional to the single long leg — NOT a
    # stop-anchored risk_per_trade like the ATR-based strategies (there is no fixed price
    # stop here, only a z-score stop), so this is a simple capital-allocation fraction.
    notional_fraction: float = 0.10
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = CointegrationPairsParameters()


@dataclass
class OpenTrade:
    asset: str  # "BTC" or "ETH" — whichever leg is long
    entry_side: int  # +1 (entered on z >= entry_z, long BTC) or -1 (z <= -entry_z, long ETH)
    entry_price: float
    quantity: float
    notional: float
    entry_fee: float
    open_close_time: int
    entry_zscore: float


@dataclass
class PairsState:
    equity: float
    open_trade: OpenTrade | None = None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "REVERSION" or "STOP"
    asset: str
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float  # net_pnl / notional — a return-on-capital-allocated ratio, NOT a
    # stop-distance risk multiple (this strategy has no fixed price stop to measure against)
    exit_zscore: float
    equity_after: float


def align_pair_candles(x_candles: pd.DataFrame, y_candles: pd.DataFrame, x_name: str, y_name: str) -> pd.DataFrame:
    """Inner-join two single-asset candle frames on close_time — only candles present in
    BOTH series survive, so no gap in either asset's history can silently misalign the
    pair. Both inputs are assumed already-closed candles (upstream MarketDataClient
    contract); no additional lookahead is introduced by the join itself."""
    x = x_candles[["close_time", "date", "close"]].rename(columns={"close": f"{x_name}_close"})
    y = y_candles[["close_time", "date"]].assign(**{f"{y_name}_close": y_candles["close"]})
    merged = x.merge(y[["close_time", f"{y_name}_close"]], on="close_time", how="inner")
    return merged.sort_values("close_time").reset_index(drop=True)


def add_indicators(
    aligned: pd.DataFrame,
    params: CointegrationPairsParameters = DEFAULT_PARAMETERS,
    x_name: str = PAIR[0],
    y_name: str = PAIR[1],
) -> pd.DataFrame:
    """Attach rolling hedge_ratio, spread, and z-score to an aligned two-asset frame. No
    lookahead: every rolling value at row i only uses rows up to and including i."""
    frame = aligned.copy().sort_values("close_time").reset_index(drop=True)
    x = frame[f"{x_name}_close"].astype(float)
    y = frame[f"{y_name}_close"].astype(float)

    cov = x.rolling(params.window).cov(y)
    var = x.rolling(params.window).var()
    frame["hedge_ratio"] = cov / var.replace(0, float("nan"))
    frame["spread"] = y - frame["hedge_ratio"] * x
    spread_mean = frame["spread"].rolling(params.window).mean()
    spread_std = frame["spread"].rolling(params.window).std()
    frame["zscore"] = (frame["spread"] - spread_mean) / spread_std.replace(0, float("nan"))
    return frame


def determine_entry_side(z: float, entry_z: float) -> int:
    """+1 = long the x leg (z is high: y looks like the outperformer, x the laggard);
    -1 = long the y leg (z is low: vice versa); 0 = no signal."""
    if z >= entry_z:
        return 1
    if z <= -entry_z:
        return -1
    return 0


def determine_exit_reason(entry_side: int, z: float, exit_z: float, stop_z: float) -> str | None:
    """REVERSION when z has come back to exit_z on the entry side's terms, STOP when it
    instead diverged further to +/- stop_z. None if neither has happened yet."""
    if entry_side == 1:
        if z <= exit_z:
            return "REVERSION"
        if z >= stop_z:
            return "STOP"
    else:
        if z >= exit_z:
            return "REVERSION"
        if z <= -stop_z:
            return "STOP"
    return None


def run_pairs_backtest(
    aligned: pd.DataFrame,
    params: CointegrationPairsParameters = DEFAULT_PARAMETERS,
    x_name: str = PAIR[0],
    y_name: str = PAIR[1],
) -> tuple[list[ExitEvent], PairsState]:
    """Candle-by-candle simulation over an already-aligned, already-indicator-enriched
    two-asset frame (see align_pair_candles + add_indicators). Only ONE position open at
    a time; the Engle-Granger cointegration test is invoked exactly at the candles where
    a z-score threshold is crossed and would otherwise open a trade — not on every candle."""
    frame = aligned.dropna(subset=["zscore"]).reset_index(drop=True)
    state = PairsState(equity=params.initial_equity)
    closed_trades: list[ExitEvent] = []

    for i in range(len(frame)):
        row = frame.iloc[i]
        z = float(row["zscore"])

        if state.open_trade is not None:
            trade = state.open_trade
            price_now = float(row[f"{trade.asset}_close"])
            exit_reason = determine_exit_reason(trade.entry_side, z, params.exit_z, params.stop_z)

            if exit_reason is not None:
                exit_price = apply_slippage(price_now, params.slippage_bps, "sell")
                gross_pnl = (exit_price - trade.entry_price) * trade.quantity
                exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
                total_fees = trade.entry_fee + exit_fee
                net_pnl = gross_pnl - total_fees
                equity_after = state.equity + net_pnl
                state.equity = equity_after
                state.open_trade = None
                closed_trades.append(
                    ExitEvent(
                        exit_reason=exit_reason,
                        asset=trade.asset,
                        exit_price=exit_price,
                        gross_pnl=gross_pnl,
                        fees=total_fees,
                        net_pnl=net_pnl,
                        r_multiple=net_pnl / max(trade.notional, 1e-9),
                        exit_zscore=z,
                        equity_after=equity_after,
                    )
                )

        if state.open_trade is None:
            side = determine_entry_side(z, params.entry_z)
            asset = x_name if side == 1 else y_name if side == -1 else None

            if side != 0:
                window_start = max(0, i - params.window + 1)
                window_slice = frame.iloc[window_start : i + 1]
                result = engle_granger_cointegration(
                    window_slice[f"{x_name}_close"], window_slice[f"{y_name}_close"]
                )
                pvalue = result.get("adf_pvalue")
                confirmed = bool(result.get("cointegrated_at_5pct")) or (
                    pvalue is not None and pvalue < params.adf_significance
                )
                if confirmed:
                    raw_entry = float(row[f"{asset}_close"])
                    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
                    notional = min(
                        state.equity * params.notional_fraction,
                        state.equity * params.max_notional_pct,
                    )
                    quantity = notional / entry_price
                    entry_fee = notional * params.fee_bps / 10000.0
                    state.open_trade = OpenTrade(
                        asset=asset,
                        entry_side=side,
                        entry_price=entry_price,
                        quantity=quantity,
                        notional=notional,
                        entry_fee=entry_fee,
                        open_close_time=int(row["close_time"]),
                        entry_zscore=z,
                    )

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the Cointegration Pairs strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
