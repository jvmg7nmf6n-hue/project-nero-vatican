"""CC-1 directive Part B3a: real, structured live "distance to trigger"
data for the 3 fully-verified survivor strategies (BREAKOUT_MOMENTUM/GOLD,
TREND_PULLBACK/BNB, COINTEGRATION_PAIRS/BTC-ETH), computed via each
strategy's own real add_indicators function -- never a second, parallel
reimplementation of RSI/MA/z-score that could silently drift from what the
live strategy itself actually evaluates.

Real gap this fills (confirmed 2026-08-08 investigation): docs/site_data/
quant_metrics.json and quant_cross_asset.json exist but carry DIFFERENT
indicators (a generic price z-score over a different window; a
cointegration check over a different pair) -- neither is the same
computation these 3 strategies' own entry conditions use. Nothing
previously exported these strategies' own real RSI(14)/MA50/MA200/
breakout-high/pairs-z-score values in structured form -- only
human-readable NO_TRADE reason strings exist today
(docs/site_data/ledger_full.json's `reasoning` field).

DISTANCE, per condition, honestly separate -- never combined into one
score (B1c's own finding, same failure class as an uncalibrated
composite): BREAKOUT_MOMENTUM and TREND_PULLBACK each mix genuinely
different units (price-vs-price percentages alongside a 0-100 RSI
reading), so this file reports one distance PER real condition, never a
blended single number. COINTEGRATION_PAIRS' real condition is already a
single, already-normalized field (a z-score) vs. a single threshold --
its distance is the one real, non-arbitrary value entry_z - abs(z).

GOLD and BNB read from the already-exported docs/site_data/candles/ files
(no network needed, same pattern as export_quant_metrics.py). BTC-ETH
needs two live-aligned legs at 12h; neither is pre-exported to
docs/site_data/candles/ at that timeframe (confirmed: no ETH_*.json file
of any timeframe exists in that directory) -- fetched live via the same
tools.timeframe_data.fetch_timeframe_candles live_scheduler.py itself
uses for these exact two legs, never a synthetic substitute.

NO TIME-TO-TRIGGER LANGUAGE OR COMPUTATION OF ANY KIND, anywhere in this
file -- every field is a live, present-tense measurement of where the
market IS right now relative to a real threshold, never a prediction,
ETA, or rate-of-approach. This was a real temptation while writing this
(e.g. dividing a distance by a recent average per-candle move to estimate
"candles until trigger") and was deliberately not built -- see this
directive's own closing report.

FAIL-INDEPENDENT: one strategy's real data being unavailable (candle file
missing, live fetch failing) is recorded as its own `error` field and
does not prevent the other two from being written -- same convention as
export_quant_metrics.py's per-file try/except.
"""
from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies import breakout_momentum, cointegration_pairs, trend_pullback
from tools.timeframe_data import fetch_timeframe_candles

SCHEMA_VERSION = 1
DEFAULT_CANDLES_DIR = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "candles"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "survivor_distance.json"


@dataclass(frozen=True)
class SurvivorDistanceResult:
    written: list[str]
    errors: list[dict[str, str]]


def _load_candle_file(path: Path) -> pd.DataFrame:
    """Raises on any parse/shape problem -- caller's try/except handles it,
    matching export_quant_metrics.py's own division of responsibility.
    `time` in these files is epoch SECONDS (confirmed against real file
    content); every strategy's own add_indicators/evaluate_entry expects
    `close_time` in epoch MILLISECONDS (confirmed from evaluate_entry's own
    int(candle["close_time"]) usage elsewhere in this codebase)."""
    data = json.loads(path.read_text())
    rows = data["candles"]
    frame = pd.DataFrame(rows)
    frame["close_time"] = (frame["time"].astype(float) * 1000).astype("int64")
    return frame


def _breakout_momentum_distance(candles_dir: Path, now: datetime) -> dict[str, object]:
    frame = _load_candle_file(candles_dir / "GOLD_1week.json")
    indicators = breakout_momentum.add_indicators(frame)
    last = indicators.iloc[-1]
    close = float(last["close"])
    breakout_high = last.get("breakout_high")
    ma200 = last.get("ma200")
    rsi_value = last.get("rsi")
    params = breakout_momentum.DEFAULT_PARAMETERS
    return {
        "strategy_id": "BREAKOUT_MOMENTUM",
        "asset": "GOLD",
        "timeframe": "1week",
        "candle_close_time_ms": int(last["close_time"]),
        "conditions": [
            {
                "label": "close vs prior 20-week high (breakout level)",
                "unit": "pct",
                "distance": None if pd.isna(breakout_high) else round((close - float(breakout_high)) / float(breakout_high) * 100, 3),
                "note": "positive means close is already above the breakout level; negative is the real pct still needed to rise",
            },
            {
                "label": "close vs 200-period moving average",
                "unit": "pct",
                "distance": None if pd.isna(ma200) else round((close - float(ma200)) / float(ma200) * 100, 3),
            },
            {
                "label": f"RSI(14) vs momentum floor ({params.rsi_momentum_min})",
                "unit": "rsi_points",
                "distance": None if pd.isna(rsi_value) else round(float(rsi_value) - params.rsi_momentum_min, 3),
            },
        ],
    }


def _trend_pullback_distance(candles_dir: Path, now: datetime) -> dict[str, object]:
    frame = _load_candle_file(candles_dir / "BNB_12h.json")
    indicators = trend_pullback.add_indicators(frame)
    last = indicators.iloc[-1]
    close = float(last["close"])
    ma50 = last.get("ma50")
    ma200 = last.get("ma200")
    rsi_value = last.get("rsi")
    prior_near_ma50 = bool(last.get("prior_near_ma50", False))
    params = trend_pullback.DEFAULT_PARAMETERS
    rsi_band_distance = None
    if not pd.isna(rsi_value):
        r = float(rsi_value)
        if params.rsi_lower <= r <= params.rsi_upper:
            rsi_band_distance = round(min(r - params.rsi_lower, params.rsi_upper - r), 3)
        else:
            rsi_band_distance = round(-min(abs(r - params.rsi_lower), abs(r - params.rsi_upper)), 3)
    return {
        "strategy_id": "TREND_PULLBACK",
        "asset": "BNB",
        "timeframe": "12h",
        "candle_close_time_ms": int(last["close_time"]),
        "conditions": [
            {
                "label": "close vs 200-period moving average (established uptrend)",
                "unit": "pct",
                "distance": None if pd.isna(ma200) else round((close - float(ma200)) / float(ma200) * 100, 3),
            },
            {
                "label": "50-period MA vs 200-period MA (established uptrend)",
                "unit": "pct",
                "distance": None if (pd.isna(ma50) or pd.isna(ma200)) else round((float(ma50) - float(ma200)) / float(ma200) * 100, 3),
            },
            {
                "label": "prior candle already pulled back near 50-period MA",
                "unit": "boolean_state",
                "distance": None,
                "note": f"real, already-resolved state (not a live distance): {prior_near_ma50} as of the prior closed candle",
            },
            {
                "label": "close vs 50-period moving average (recovery above)",
                "unit": "pct",
                "distance": None if pd.isna(ma50) else round((close - float(ma50)) / float(ma50) * 100, 3),
            },
            {
                "label": f"RSI(14) within neutral band [{params.rsi_lower}, {params.rsi_upper}]",
                "unit": "rsi_points",
                "distance": rsi_band_distance,
                "note": "positive means already inside the band (distance to nearer edge); negative means outside it",
            },
        ],
    }


def _cointegration_pairs_distance(client: MarketDataClient, now: datetime) -> dict[str, object]:
    x_asset, y_asset = cointegration_pairs.PAIR  # ("BTC", "ETH")
    x_candles, _x_method = fetch_timeframe_candles(client, x_asset, "12h")
    y_candles, _y_method = fetch_timeframe_candles(client, y_asset, "12h")
    aligned = cointegration_pairs.align_pair_candles(x_candles, y_candles, x_asset, y_asset)
    indicators = cointegration_pairs.add_indicators(aligned)
    last = indicators.iloc[-1]
    z = last.get("zscore")
    params = cointegration_pairs.DEFAULT_PARAMETERS
    z_distance = None if pd.isna(z) else round(params.entry_z - abs(float(z)), 4)
    return {
        "strategy_id": "COINTEGRATION_PAIRS",
        "asset": f"{x_asset}-{y_asset}",
        "timeframe": "12h",
        "candle_close_time_ms": int(last["close_time"]),
        "conditions": [
            {
                "label": f"|z-score of spread| vs entry threshold ({params.entry_z})",
                "unit": "z_units",
                "distance": z_distance,
                "note": "the spread's real current z-score is already a normalized distance; this is entry_z - |z| (0 or below means the threshold is currently met)",
                "raw_zscore": None if pd.isna(z) else round(float(z), 4),
            },
        ],
    }


def export_survivor_distance(
    candles_dir: Path = DEFAULT_CANDLES_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: datetime | None = None,
    market_data_client: MarketDataClient | None = None,
) -> SurvivorDistanceResult:
    now = now or datetime.now(timezone.utc)
    client = market_data_client or MarketDataClient()

    written: list[str] = []
    errors: list[dict[str, str]] = []
    entries: list[dict[str, object]] = []

    for label, fn in (
        ("BREAKOUT_MOMENTUM/GOLD", lambda: _breakout_momentum_distance(candles_dir, now)),
        ("TREND_PULLBACK/BNB", lambda: _trend_pullback_distance(candles_dir, now)),
        ("COINTEGRATION_PAIRS/BTC-ETH", lambda: _cointegration_pairs_distance(client, now)),
    ):
        try:
            entry = fn()
            entry["computed_at"] = now.isoformat()
        except (FileNotFoundError, MarketDataUnavailableError, KeyError, ValueError) as exc:
            errors.append({"strategy": label, "message": f"{exc.__class__.__name__}: {exc}"})
            continue
        entries.append(entry)
        written.append(label)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "last_updated": now.isoformat(),
        "distances": entries,
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")

    return SurvivorDistanceResult(written=written, errors=errors)


def main() -> None:
    """Never raises -- a script failure must show up in the GitHub Actions
    log but must not fail the workflow step itself (same convention as
    export_quant_metrics.main())."""
    try:
        result = export_survivor_distance()
        print(f"Survivor distance export: written={len(result.written)}, errors={len(result.errors)}")
        for err in result.errors:
            print(f"  ERROR: {err}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
