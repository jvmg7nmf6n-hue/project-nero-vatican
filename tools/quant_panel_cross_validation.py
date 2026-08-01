"""CLI: cross-validate nero_core.quant.quant_panel's Sharpe ratio and realized
volatility against empyrical-reloaded (the maintained fork of Quantopian's
empyrical; the original is unmaintained and was not installed here -- see Day 4's
closing report for why empyrical-reloaded was chosen without needing to fall back
further to quantstats or a hand-computed reference).

TWO LONGEST-HISTORY ASSETS: every candle file currently holds exactly 200 candles,
but "history" in real calendar time differs by timeframe -- computed directly from
each file's own first/last timestamps (not assumed), the 5 "1week" assets (EUR/USD,
GBP/USD, GOLD, SILVER, USD/JPY) are tied for longest at 1393 days each, well ahead of
the 1day/24h assets (~199-290 days) and BNB's 12h (~99 days). GOLD and EUR/USD were
picked from that tied group as two assets from different asset classes.

CONVENTION ALIGNMENT (the actual point of this test): empyrical's own functions are
convention-agnostic about simple vs. log returns -- they just compute mean/std of
whatever return series they're handed. Feeding empyrical the SAME log-return series
quant_panel.py itself computes isolates a pure formula-correctness check (does
Vatican's Sharpe/Sortino/volatility ARITHMETIC match a trusted reference, given
identical inputs) from the SEPARATE, well-known small divergence that comparing
against simple returns would introduce -- ln(1+r) ~= r only for small r, so log vs.
simple returns is its own legitimate (and here, deliberately NOT tested) source of
difference. Empyrical's `risk_free`/`required_return` are both PER-PERIOD, so
rf_annual/periods_per_year is passed in, matching quant_panel's own per-period MAR
default exactly.

Usage:
    python -m tools.quant_panel_cross_validation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.execution.export_quant_metrics import classify_asset_class
from nero_core.quant.quant_panel import (
    cross_validates,
    log_returns,
    periods_per_year_for_timeframe,
    realized_volatility,
    relative_difference,
    sharpe_ratio,
    sortino_ratio,
)

CANDLES_DIR = Path(__file__).resolve().parents[1] / "docs" / "site_data" / "candles"

# Both from the tied-longest (1393-day) group, two different asset classes.
CROSS_VALIDATION_FILES = ["GOLD_1week.json", "EURUSD_1week.json"]

RF_ANNUAL_FOR_TEST = 0.0363  # matches a real fred_dff export run -- not refetched here (no network in this tool)


def _load_closes(filename: str) -> tuple[str, str, pd.Series]:
    data = json.loads((CANDLES_DIR / filename).read_text())
    closes = pd.Series([float(c["close"]) for c in data["candles"]])
    return data["asset"], data["timeframe"], closes


def cross_validate_asset(filename: str) -> dict[str, object]:
    import empyrical

    asset, timeframe, closes = _load_closes(filename)
    periods_per_year = periods_per_year_for_timeframe(classify_asset_class(asset), timeframe)
    returns = log_returns(closes)
    window = len(returns)  # use everything available -- no clamping needed for this check
    per_period_mar = RF_ANNUAL_FOR_TEST / periods_per_year

    mine_vol = realized_volatility(closes, window, periods_per_year)
    ref_vol = float(empyrical.annual_volatility(returns.to_numpy(), annualization=periods_per_year) * 100.0)

    mine_sharpe = sharpe_ratio(closes, window, periods_per_year, RF_ANNUAL_FOR_TEST)
    ref_sharpe = float(
        empyrical.sharpe_ratio(returns.to_numpy(), risk_free=per_period_mar, annualization=periods_per_year)
    )

    mine_sortino = sortino_ratio(closes, window, periods_per_year, RF_ANNUAL_FOR_TEST)
    ref_sortino = float(
        empyrical.sortino_ratio(returns.to_numpy(), required_return=per_period_mar, annualization=periods_per_year)
    )

    return {
        "asset": asset,
        "timeframe": timeframe,
        "n_returns": len(returns),
        "vol": (mine_vol, ref_vol, relative_difference(mine_vol, ref_vol)),
        "sharpe": (mine_sharpe, ref_sharpe, relative_difference(mine_sharpe, ref_sharpe)),
        "sortino": (mine_sortino, ref_sortino, relative_difference(mine_sortino, ref_sortino)),
    }


def format_report(results: list[dict[str, object]]) -> str:
    lines = ["=== Quant Panel Cross-Validation vs empyrical-reloaded ===", ""]
    for r in results:
        lines.append(f"--- {r['asset']} / {r['timeframe']} (n={r['n_returns']} returns) ---")
        for metric in ("vol", "sharpe", "sortino"):
            mine, ref, rel_diff = r[metric]
            verdict = "CROSS-VALIDATED" if cross_validates(mine, ref) else "*** DIVERGES ***"
            lines.append(f"  {metric:8s} mine={mine:.6f}  reference={ref:.6f}  rel_diff={rel_diff:.6f}  {verdict}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = [cross_validate_asset(f) for f in CROSS_VALIDATION_FILES]
    print(format_report(results))


if __name__ == "__main__":
    main()
