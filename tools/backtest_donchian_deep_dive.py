"""CLI: Donchian Cross-Asset Deep-Dive, Task 2 — focused DONCHIAN_TREND sweep at
maximum data depth. Tests whether deeper history (decades, not the last few years)
resolves the sample-size ceiling that kept DONCHIAN_TREND permanently
PROMISING-WATCHLIST across three prior batches (docs/comprehensive_asset_expansion_
closing_report.md).

Strategy: nero_core.strategies.donchian_breakout_bracket (bidirectional N-period
channel breakout, 2xATR stop, fixed 2R target, real-time holding cap) — see that
module's docstring for why this is a distinct, explicitly-versioned mechanism from the
existing long-only trailing-exit donchian-trend-v1.0.0.

Three N presets (N_PRESETS in the strategy module): N10 (tactical), N20 (classic
Donchian), N40 (structural), each with its own holding cap matched to let that horizon
develop.

Universe:
  Priority Tier (all 3 N values):
    - Forex: EUR/USD, USD/JPY, GBP/USD, USD/CHF @ 1week (Twelve Data, native, full
      depth already under the 5000-row outputsize cap — no special handling needed)
    - Metals: GOLD @ 1week (fetched via a DIRECT MarketDataClient.load_intraday call
      with candles=5000, bypassing tools.timeframe_data's own hardcoded 2000-candle
      cap — see docs/donchian_task1_depth_audit.md; recovers 1970-1988), SILVER @
      1week (yfinance SI=F, already its true max depth)
    - Stocks: SPY, QQQ @ 1week AND 1day (yfinance, full history)
  Secondary Tier (N20 only — classic-parameter efficiency check):
    - Stocks: AAPL, MSFT, GOOGL @ 1week
    - Crypto: BTC, ETH @ 1week AND 1day (Binance via MarketDataClient, comparison
      baseline — expected far shorter history than every other asset class here)

70/30 CHRONOLOGICAL SPLIT ON MAXIMUM AVAILABLE HISTORY (not capped at a recent
window) — this is the entire point of this batch, directly testing whether sample
size was the missing ingredient.

Fees: forex 0.05% (5 bps), stocks/metals 0.1% (10 bps), crypto 10 bps (unchanged
baseline). Slippage: 2 bps everywhere (unchanged baseline, not otherwise specified).
Sizing: 1% per trade (DonchianBracketParameters' own default).

GRID-SHIFT: capped at PROMISING-WATCHLIST for every config regardless of raw
classify_verdict outcome, per this task's own instruction. 1week: settlement-gap
precedent (no finer native source to resample from without crossing the
Friday-close/Sunday-open gap). 1day (SPY/QQQ/BTC/ETH): noted separately — an
intraday source DOES exist for these (1h), but only for a small recent window
(~730 days for stocks, longer but still far short of decades for crypto) that
cannot cover this batch's own multi-decade sample; grid-shift over that short a
window would test a different, much smaller sample than the one being classified,
so it is not run here either.

Random-entry baseline (Task 2's OWN classify_verdict input): donchian_bracket_
eligible_mask is True everywhere (warmup-valid candles) — DONCHIAN has no regime
precondition distinct from its own breakout trigger, matching the established
donchian_eligible_mask precedent from the metals/stocks sweeps. Task 3's stricter
near-breakout mechanism check (nero_core.strategies.donchian_breakout_bracket.
near_breakout_mask) is a SEPARATE follow-up, run only for configs that reach
SURVIVED or strong PROMISING-WATCHLIST here — see tools/backtest_donchian_mechanism_
validation.py.

No synthetic/fabricated data is ever used — if a fetch fails, that config is
reported SKIPPED with the reason; a mechanically invalid N/holding-cap combination
is also SKIPPED (never forced), per donchian_breakout_bracket.build_parameters_for_n.

Usage:
    python -m tools.backtest_donchian_deep_dive
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.data_sources.stock_data import StockDataUnavailableError, fetch_stock_ohlcv
from nero_core.strategies import donchian_breakout_bracket as dbb
from tools.backtest_statistics import MIN_SAMPLE_SIZE, bootstrap_mean_r_ci, classify_verdict, random_entry_baseline_single_asset
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

FEE_BPS_BY_CLASS = {"forex": 5.0, "stocks": 10.0, "metals": 10.0, "crypto": 10.0}
SLIPPAGE_BPS = 2.0

PRIORITY_FOREX = ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF"]
PRIORITY_METALS = ["GOLD", "SILVER"]
PRIORITY_STOCKS = ["SPY", "QQQ"]
PRIORITY_STOCK_TIMEFRAMES = ["1week", "1day"]

SECONDARY_STOCKS = ["AAPL", "MSFT", "GOOGL"]
SECONDARY_CRYPTO = ["BTC", "ETH"]
SECONDARY_CRYPTO_TIMEFRAMES = ["1week", "1day"]

ALL_N_KEYS = ["N10", "N20", "N40"]


def donchian_bracket_eligible_mask(evaluable: pd.DataFrame) -> pd.Series:
    """DONCHIAN has no regime precondition distinct from its own breakout trigger —
    the eligible pool for Task 2's OWN random baseline is every warmup-valid candle,
    matching the established donchian_eligible_mask precedent from the metals/stocks
    sweeps. (Task 3's near_breakout_mask is a separate, stricter follow-up pool.)"""
    return pd.Series(True, index=evaluable.index)


def _half_stats(half_candles: pd.DataFrame, params: dbb.DonchianBracketParameters) -> dict[str, object]:
    trades, _state = dbb.run_donchian_bracket_backtest(half_candles, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    enriched = dbb.add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=dbb.INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    eligible_mask = donchian_bracket_eligible_mask(evaluable)

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, params, dbb.size_entry, expectancy_r, len(trades), evaluate_exit_fn=dbb.evaluate_exit
    )
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _apply_grid_shift_cap(verdict: str, timeframe: str) -> tuple[str, str | None]:
    if verdict != "SURVIVED":
        return verdict, None
    if timeframe == "1week":
        note = "grid-shift NOT_APPLICABLE (1week: Friday-close/Sunday-open settlement gap, no finer native source); capped from raw SURVIVED"
    else:
        note = "grid-shift NOT_APPLICABLE (1day: an intraday source exists but only for a recent window far shorter than this config's multi-decade sample); capped from raw SURVIVED"
    return "PROMISING-WATCHLIST", note


def _fetch_forex_candles(pair: str) -> tuple[pd.DataFrame, str]:
    result = fetch_forex_ohlcv(pair, "1week")
    return result.prices, result.source


def _fetch_gold_weekly_uncapped() -> tuple[pd.DataFrame, str]:
    client = MarketDataClient()
    result = client.load_intraday("GOLD", interval="1week", candles=5000)
    return result.prices, result.source


def _fetch_silver_weekly() -> tuple[pd.DataFrame, str]:
    client = MarketDataClient()
    return fetch_timeframe_candles(client, "SILVER", "1week")


def _fetch_stock_candles(symbol: str, timeframe: str) -> tuple[pd.DataFrame, str]:
    result = fetch_stock_ohlcv(symbol, timeframe)
    return result.prices, result.source


def _fetch_crypto_candles(asset: str, timeframe: str) -> tuple[pd.DataFrame, str]:
    client = MarketDataClient()
    tf_key = "24h" if timeframe == "1day" else "1week"
    return fetch_timeframe_candles(client, asset, tf_key)


def _run_config(
    rows: list[dict[str, object]],
    candle_cache: dict[tuple, tuple[pd.DataFrame, str]],
    cache_key: tuple,
    fetch_fn,
    asset_label: str,
    timeframe: str,
    n_key: str,
    asset_class: str,
) -> None:
    start = time.monotonic()
    try:
        if cache_key not in candle_cache:
            candle_cache[cache_key] = fetch_fn()
        candles, method = candle_cache[cache_key]
    except (ForexDataUnavailableError, StockDataUnavailableError, MarketDataUnavailableError) as exc:
        print(f"{asset_label} / {timeframe} / DONCHIAN_TREND {n_key}: SKIPPED — {exc}")
        rows.append({"asset": asset_label, "timeframe": timeframe, "n_key": n_key, "error": str(exc)})
        return

    try:
        params = dbb.build_parameters_for_n(n_key, timeframe, FEE_BPS_BY_CLASS[asset_class], SLIPPAGE_BPS)
    except dbb.MechanicallyInvalidConfigError as exc:
        print(f"{asset_label} / {timeframe} / DONCHIAN_TREND {n_key}: SKIPPED — {exc}")
        rows.append({"asset": asset_label, "timeframe": timeframe, "n_key": n_key, "error": str(exc)})
        return

    train, test = split_chronological(candles)
    if train.empty or test.empty:
        reason = "not enough history to split 70/30"
        print(f"{asset_label} / {timeframe} / DONCHIAN_TREND {n_key}: SKIPPED — {reason}")
        rows.append({"asset": asset_label, "timeframe": timeframe, "n_key": n_key, "error": reason})
        return

    train_stats = _half_stats(train, params)
    test_stats = _half_stats(test, params)
    raw_verdict = classify_verdict(train_stats, test_stats)
    verdict, cap_note = _apply_grid_shift_cap(raw_verdict, timeframe)
    elapsed = time.monotonic() - start
    print(f"{asset_label} / {timeframe} / DONCHIAN_TREND {n_key}: {verdict} ({elapsed:.1f}s, {len(candles)} candles)")
    rows.append({
        "asset": asset_label, "timeframe": timeframe, "n_key": n_key, "method": method,
        "candle_count": len(candles), "channel_period": params.channel_period,
        "max_holding_hours": params.max_holding_hours,
        "train": train_stats, "test": test_stats, "verdict": verdict,
        "raw_verdict": raw_verdict, "grid_shift_note": cap_note,
    })


def run_full_sweep() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candle_cache: dict[tuple, tuple[pd.DataFrame, str]] = {}

    # --- Priority Tier: Forex, all 3 N values, 1week only ---
    for pair in PRIORITY_FOREX:
        for n_key in ALL_N_KEYS:
            _run_config(rows, candle_cache, ("forex", pair), lambda pair=pair: _fetch_forex_candles(pair),
                        pair, "1week", n_key, "forex")

    # --- Priority Tier: Metals, all 3 N values, 1week only ---
    for n_key in ALL_N_KEYS:
        _run_config(rows, candle_cache, ("metal", "GOLD"), _fetch_gold_weekly_uncapped, "GOLD", "1week", n_key, "metals")
    for n_key in ALL_N_KEYS:
        _run_config(rows, candle_cache, ("metal", "SILVER"), _fetch_silver_weekly, "SILVER", "1week", n_key, "metals")

    # --- Priority Tier: Stocks (SPY/QQQ), all 3 N values, both timeframes ---
    for symbol in PRIORITY_STOCKS:
        for timeframe in PRIORITY_STOCK_TIMEFRAMES:
            for n_key in ALL_N_KEYS:
                _run_config(rows, candle_cache, ("stock", symbol, timeframe),
                            lambda symbol=symbol, timeframe=timeframe: _fetch_stock_candles(symbol, timeframe),
                            symbol, timeframe, n_key, "stocks")

    # --- Secondary Tier: Stocks (AAPL/MSFT/GOOGL), N20 only, 1week only ---
    for symbol in SECONDARY_STOCKS:
        _run_config(rows, candle_cache, ("stock", symbol, "1week"),
                    lambda symbol=symbol: _fetch_stock_candles(symbol, "1week"), symbol, "1week", "N20", "stocks")

    # --- Secondary Tier: Crypto (BTC/ETH), N20 only, both timeframes ---
    for asset in SECONDARY_CRYPTO:
        for timeframe in SECONDARY_CRYPTO_TIMEFRAMES:
            _run_config(rows, candle_cache, ("crypto", asset, timeframe),
                        lambda asset=asset, timeframe=timeframe: _fetch_crypto_candles(asset, timeframe),
                        asset, timeframe, "N20", "crypto")

    return rows


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    ci = stats["ci"]
    ci_str = f" CI=[{ci.lower_2_5:.3f},{ci.upper_97_5:.3f}]" if ci is not None else " CI=n/a"
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{ci_str}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== Donchian Cross-Asset Deep-Dive: Focused Sweep ===", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['asset']} / {r['timeframe']} / {r['n_key']}: SKIPPED — {r['error']}")
            continue
        lines.append(
            f"{r['asset']} / {r['timeframe']} / {r['n_key']}: {r['verdict']} — "
            f"TRAIN {_fmt_half(r['train'])} | TEST {_fmt_half(r['test'])} ({r['candle_count']} candles)"
        )
        if r.get("grid_shift_note"):
            lines.append(f"    note: {r['grid_shift_note']}")

    survivors = [r for r in rows if r.get("verdict") in ("SURVIVED", "PROMISING-WATCHLIST")]
    lines.append("")
    lines.append(f"=== {len(survivors)} config(s) SURVIVED or PROMISING-WATCHLIST ===")
    for r in survivors:
        lines.append(f"  {r['asset']} / {r['timeframe']} / {r['n_key']}: {r['verdict']} (raw: {r['raw_verdict']})")
    return "\n".join(lines)


def main() -> None:
    rows = run_full_sweep()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
