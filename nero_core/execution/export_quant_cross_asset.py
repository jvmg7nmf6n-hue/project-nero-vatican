"""Day 5/7 Quant Intelligence Panel, Part 2 export. Reads every already-exported
candle file in docs/site_data/candles/ (no network -- Day 1's pipeline already
fetched them) and writes docs/site_data/quant_cross_asset.json: correlation matrix,
GARCH volatility regime, selected cointegration pairs, and BTC-benchmark lead-lag.

FAIL-INDEPENDENT PER PART: each of the four nero_core.quant.cross_asset functions
already fails independently per asset/pair internally (see that module). This
export additionally wraps each of the four PART-level calls in its own try/except,
so a catastrophic failure in, say, the cointegration part (an unexpected statsmodels
import error) still leaves the correlation matrix, volatility regimes, and lead-lag
parts intact in the output, rather than losing the whole file.

NO COMPOSITE SCORE: this file contains exactly the four arrays the task asks for --
correlation_matrix, volatility_regimes, cointegration, lead_lag -- and nothing else.
QuantConsensusReport (nero_core.quant.quant_intelligence's own composite 0-100
score) is never imported here, per this project's standing "no uncalibrated
composite scores" policy.
"""
from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.quant.cross_asset import cointegration_report, lead_lag_report, rolling_correlation_matrix, volatility_regimes

SCHEMA_VERSION = 1
DEFAULT_CANDLES_DIR = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "candles"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "quant_cross_asset.json"

CORRELATION_WINDOW = 30


@dataclass(frozen=True)
class QuantCrossAssetResult:
    part_errors: list[dict[str, str]]
    load_errors: list[dict[str, str]]


def _run_part(
    name: str,
    fn,
    candles_dir: Path,
    part_errors: list[dict[str, str]],
    load_errors: list[dict[str, str]],
) -> list[dict[str, object]]:
    """One part's catastrophic failure never aborts the other three -- see module
    docstring. Each part's own internal per-item load_errors are also collected
    here (already deduplicated, so the same corrupt file doesn't get reported
    once per part -- only the first part to touch it does)."""
    try:
        result = fn(candles_dir)
        load_errors.extend(e for e in result.get("load_errors", []) if e not in load_errors)
        return result.get("pairs") or result.get("entries") or []
    except Exception as exc:  # noqa: BLE001 - one part's failure must never abort the rest
        part_errors.append({"part": name, "message": f"{exc.__class__.__name__}: {exc}"})
        return []


def export_quant_cross_asset(
    candles_dir: Path = DEFAULT_CANDLES_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: datetime | None = None,
) -> QuantCrossAssetResult:
    now = now or datetime.now(timezone.utc)
    part_errors: list[dict[str, str]] = []
    load_errors: list[dict[str, str]] = []

    correlation_matrix = _run_part(
        "correlation_matrix",
        lambda d: rolling_correlation_matrix(d, window=CORRELATION_WINDOW),
        candles_dir, part_errors, load_errors,
    )
    regimes = _run_part("volatility_regimes", volatility_regimes, candles_dir, part_errors, load_errors)
    cointegration = _run_part("cointegration", cointegration_report, candles_dir, part_errors, load_errors)
    lead_lag = _run_part("lead_lag", lead_lag_report, candles_dir, part_errors, load_errors)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "last_updated": now.isoformat(),
        "correlation_matrix": correlation_matrix,
        "volatility_regimes": regimes,
        "cointegration": cointegration,
        "lead_lag": lead_lag,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")

    return QuantCrossAssetResult(part_errors=part_errors, load_errors=load_errors)


def main() -> None:
    """Never raises -- a script failure must show up in the GitHub Actions log,
    but must not fail the workflow step itself (same convention as
    export_quant_metrics.main())."""
    try:
        result = export_quant_cross_asset()
        print(f"Quant cross-asset export: part_errors={len(result.part_errors)}, load_errors={len(result.load_errors)}")
        for err in result.part_errors:
            print(f"  PART ERROR: {err}")
        for err in result.load_errors:
            print(f"  LOAD ERROR: {err}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
