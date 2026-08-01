"""Day 4/7 — Quant Intelligence Panel export. Reads every already-exported candle
file in docs/site_data/candles/ (no network needed for the candles themselves --
Day 1's own pipeline already fetched them) and writes docs/site_data/quant_metrics.json,
one entry per candle FILE (not per asset) -- GOLD and SILVER each have two files at two
different timeframes, and their volatility/Sharpe genuinely differ by timeframe, so
collapsing them into a single per-asset record would silently hide that. The frontend
looks up an entry by the exact same (sanitized asset, timeframe) key Day 2's candle
lookup already uses, so any two strategies sharing that same (asset, timeframe) pair
correctly see the identical panel -- the metrics are per-asset(+timeframe), never
per-strategy.

RISK-FREE RATE: sourced from nero_core.data_sources.fred_rates.fetch_policy_rate("USD")
-- FRED's DFF (Federal Funds Effective Rate, daily) -- NOT nero_core.data_sources.
macro_data's own DFII10 (the series MACRO_RISK_ON is wired to). DFII10 is a 10-Year
TIPS REAL yield: wrong maturity and wrong (real vs nominal) definition for a Sharpe-
ratio risk-free rate. DFF is the conventional short-term nominal proxy. Same t+2
business-day publication-lag discipline either series already uses in this codebase
(fred_rates.lagged_usable_rate, DAILY_LAG_BUSINESS_DAYS=2 -- identical to macro_data's
own DFII10_LAG_BUSINESS_DAYS=2). If FRED is unreachable, or returns no usable
observation after lag-shifting, every asset in this run falls back to
FALLBACK_RF_ANNUAL and rf_source is set to the literal "fallback_constant" -- never
silently presented as live data.

FAIL-INDEPENDENT: one corrupt/unparseable candle file is logged and skipped; every
other file is still processed and written, mirroring export_candle_data.py's own
per-pair try/except convention.
"""
from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.data_sources.fred_rates import fetch_policy_rate, lagged_usable_rate
from nero_core.execution.export_candle_data import IN_SCOPE_PAIRS
from nero_core.quant.quant_panel import (
    COMMODITY_FUTURES,
    COMMODITY_SPOT,
    CRYPTO,
    FOREX,
    STOCK,
    annualized_log_return,
    periods_per_year_for_timeframe,
    realized_volatility,
    rolling_zscore,
    sharpe_ratio,
    sortino_ratio,
)

# GOLD/SILVER split (feature/timeframe-periods-asset-aware): CandlePair.fetch_
# family ("crypto_metals"/"forex"/"stock") is a FETCH-ROUTING label, reused
# exactly as-is below -- not a second classification scheme. But it lumps GOLD
# and SILVER together despite them not sharing a trading calendar (verified
# empirically -- see quant_panel.py's own TIMEFRAME_PERIODS_PER_YEAR docstring),
# so this override sits on top of fetch_family rather than replacing it.
_ASSET_TO_FETCH_FAMILY: dict[str, str] = {pair.asset: pair.fetch_family for pair in IN_SCOPE_PAIRS}
_COMMODITY_ASSET_CLASS_OVERRIDE: dict[str, str] = {"GOLD": COMMODITY_SPOT, "SILVER": COMMODITY_FUTURES}
_FETCH_FAMILY_TO_ASSET_CLASS: dict[str, str] = {"crypto_metals": CRYPTO, "forex": FOREX, "stock": STOCK}


def classify_asset_class(asset: str) -> str | None:
    """None (never a guess) for any asset not on the live IN_SCOPE_PAIRS roster
    export_candle_data.py itself exports from -- the same roster this file's own
    candles_dir glob ultimately reads candle files for. GOLD/SILVER are
    special-cased to their own distinct classes (see the module-level comment
    above) before falling through to fetch_family's crypto_metals/forex/stock."""
    if asset in _COMMODITY_ASSET_CLASS_OVERRIDE:
        return _COMMODITY_ASSET_CLASS_OVERRIDE[asset]
    fetch_family = _ASSET_TO_FETCH_FAMILY.get(asset)
    if fetch_family is None:
        return None
    return _FETCH_FAMILY_TO_ASSET_CLASS.get(fetch_family)

SCHEMA_VERSION = 1
DEFAULT_CANDLES_DIR = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "candles"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "quant_metrics.json"

# Target windows: 252 for return-based metrics (a "one trading year" convention),
# re-clamped per-asset to whatever's actually available (Day 1 currently exports
# ~200 candles/asset -- see quant_panel.py's own docstring on why this is never
# hardcoded as a hard cutoff). Z-score uses its own, deliberately shorter target
# (20) -- a stretch reading is conventionally a short-lookback statistic, not a
# one-year one; it is not reported as its own `window_used` field (only the
# return-metrics window is), per this export's fixed JSON schema.
TARGET_WINDOW_RETURNS = 252
ZSCORE_WINDOW = 20

# A documented, clearly-labeled placeholder -- used ONLY when a live FRED fetch (or
# a lag-shifted usable observation) is unavailable at export time. Never presented
# as live data: rf_source is set to the literal "fallback_constant" whenever this
# is used, specifically so a reader never mistakes it for a fetched rate.
FALLBACK_RF_ANNUAL = 0.045


@dataclass(frozen=True)
class QuantMetricsResult:
    written: list[str]
    errors: list[dict[str, str]]


def fetch_risk_free_rate(now: datetime | None = None) -> tuple[float, str]:
    """(rf_annual, rf_source). rf_source is "fred_dff" for a live, lag-respecting
    FRED value, or the literal "fallback_constant" otherwise. Broad except is
    deliberate here: ANY failure mode (missing API key, network error, empty
    response, no usable observation after lag-shifting) must fall back, not
    just the documented MacroDataUnavailableError -- a quant panel showing a
    conservative constant beats one that crashes the whole export."""
    try:
        series, _source, frequency = fetch_policy_rate("USD")
        lagged = lagged_usable_rate(series, frequency).dropna()
        if lagged.empty:
            return FALLBACK_RF_ANNUAL, "fallback_constant"
        latest_pct = float(lagged.iloc[-1])
        return latest_pct / 100.0, "fred_dff"
    except Exception:  # noqa: BLE001 - see docstring: any failure mode falls back
        return FALLBACK_RF_ANNUAL, "fallback_constant"


def _load_candle_file(path: Path) -> tuple[str, str, pd.Series]:
    """Raises on any parse/shape problem -- the caller is responsible for the
    fail-independent try/except, matching export_candle_data.py's own division
    of responsibility (a helper that can raise, a loop that never lets one
    raise take down the rest)."""
    data = json.loads(path.read_text())
    asset = data["asset"]
    timeframe = data["timeframe"]
    closes = pd.Series([float(c["close"]) for c in data["candles"]])
    return asset, timeframe, closes


def _metrics_for_file(
    asset: str, timeframe: str, closes: pd.Series, rf_annual: float, now: datetime
) -> dict[str, object]:
    asset_class = classify_asset_class(asset)
    periods_per_year = periods_per_year_for_timeframe(asset_class, timeframe)
    if periods_per_year is None:
        print(
            f"  NOTE: no periods/year for asset_class={asset_class!r} timeframe={timeframe!r} "
            f"(asset={asset}) -- annualized metrics will be null."
        )

    return_count = max(len(closes) - 1, 0)
    window_used = min(TARGET_WINDOW_RETURNS, return_count)
    windowed_closes = closes.tail(window_used + 1) if window_used > 0 else closes.iloc[0:0]

    return {
        "asset": asset,
        "timeframe": timeframe,
        "periods_per_year": periods_per_year,
        "window_used": window_used,
        "rf_annual": rf_annual,
        "log_return_annualized": annualized_log_return(windowed_closes, periods_per_year),
        "zscore_current": rolling_zscore(closes, ZSCORE_WINDOW),
        "realized_vol_annualized": realized_volatility(closes, window_used, periods_per_year),
        "sharpe": sharpe_ratio(closes, window_used, periods_per_year, rf_annual),
        "sortino": sortino_ratio(closes, window_used, periods_per_year, rf_annual),
        "computed_at": now.isoformat(),
    }


def export_quant_metrics(
    candles_dir: Path = DEFAULT_CANDLES_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: datetime | None = None,
    rf_fetch_fn: Callable[[], tuple[float, str]] | None = None,
) -> QuantMetricsResult:
    now = now or datetime.now(timezone.utc)
    rf_fetch_fn = rf_fetch_fn or fetch_risk_free_rate
    rf_annual, rf_source = rf_fetch_fn()

    written: list[str] = []
    errors: list[dict[str, str]] = []
    entries: list[dict[str, object]] = []

    if not candles_dir.exists():
        return QuantMetricsResult(written=[], errors=[{"file": str(candles_dir), "message": "candles directory does not exist"}])

    for path in sorted(candles_dir.glob("*.json")):
        try:
            asset, timeframe, closes = _load_candle_file(path)
            entry = _metrics_for_file(asset, timeframe, closes, rf_annual, now)
            entry["rf_source"] = rf_source
        except Exception as exc:  # noqa: BLE001 - one corrupt file must never abort the rest
            errors.append({"file": path.name, "message": f"{exc.__class__.__name__}: {exc}"})
            continue
        entries.append(entry)
        written.append(path.name)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "last_updated": now.isoformat(),
        "metrics": entries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")

    return QuantMetricsResult(written=written, errors=errors)


def main() -> None:
    """Never raises -- a script failure must show up in the GitHub Actions log,
    but must not fail the workflow step itself (same convention as
    export_candle_data.main())."""
    try:
        result = export_quant_metrics()
        print(f"Quant metrics export: written={len(result.written)}, errors={len(result.errors)}")
        for err in result.errors:
            print(f"  ERROR: {err}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
