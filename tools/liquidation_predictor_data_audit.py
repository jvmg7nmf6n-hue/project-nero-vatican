"""Comprehensive Asset Expansion, Part C: Crypto, Task C3 — LIQUIDATION_PREDICTOR
STEP 1 data audit (mandatory, before any strategy code).

Checks, in order, EXACTLY as the task specifies:
  1. A free, pollable REST liquidation-data source usable from a US-based 30-min cron
     (Binance futures force-orders, Bybit v5 public REST, OKX public liquidation-orders,
     Coinalyze).
  2. The EXISTING funding pipeline's endpoint (fapi.binance.com, see
     nero_core.data_sources.funding_data) is reachable — if blocked, Bybit v5 public
     funding would be the fallback.
  3. Whether any free whale-transfer source actually exists (Glassnode free tier is
     explicitly NOT assumed to provide this — verified directly, not assumed).

Every check here is a REAL live HTTP call — nothing here is inferred from memory or
documentation alone. Run: python -m tools.liquidation_predictor_data_audit
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    verified_free_and_usable: bool
    detail: str


def _get(url: str, params: dict | None = None) -> tuple[int | None, str]:
    try:
        response = requests.get(url, params=params or {}, timeout=TIMEOUT_SECONDS)
        return response.status_code, response.text[:300]
    except requests.RequestException as exc:
        return None, f"{exc.__class__.__name__}: {exc}"


def check_binance_force_orders() -> CheckResult:
    """Binance futures' historical public liquidation feed (fapi/v1/allForceOrders)
    was discontinued — confirmed directly, not assumed."""
    status, detail = _get("https://fapi.binance.com/fapi/v1/allForceOrders", {"symbol": "BTCUSDT", "limit": 5})
    verified = status == 200
    return CheckResult(
        "Binance futures allForceOrders (public liquidation feed)",
        "https://fapi.binance.com/fapi/v1/allForceOrders", verified, f"status={status}: {detail}",
    )


def check_bybit_liquidation_endpoints() -> list[CheckResult]:
    """Bybit v5's public market-data namespace does not expose a documented
    historical-liquidation REST endpoint — every plausible path tried 404s."""
    results = []
    for path in ("/v5/market/liquidation", "/v5/market/recent-liq", "/v5/market/liq-records", "/v5/market/all-liquidation"):
        status, detail = _get(f"https://api.bybit.com{path}", {"category": "linear", "symbol": "BTCUSDT"})
        results.append(CheckResult(f"Bybit v5 {path}", f"https://api.bybit.com{path}", status == 200, f"status={status}: {detail}"))
    return results


def check_bybit_reachability_sanity() -> CheckResult:
    """NOT a liquidation source — proves the Bybit v5 API itself is reachable and
    public endpoints do work, so the 404s in check_bybit_liquidation_endpoints are a
    real 'no such route,' not a network/geo block. Deliberately kept OUT of the
    liquidation_sources list so it can never be miscounted as a verified liquidation
    endpoint (a real bug caught during this audit's own first run: a naive "any
    result in this list verified" check treated this 200 as if it were liquidation
    data)."""
    status, detail = _get("https://api.bybit.com/v5/market/recent-trade", {"category": "linear", "symbol": "BTCUSDT", "limit": 1})
    return CheckResult(
        "Bybit v5 recent-trade (reachability sanity check, NOT a liquidation source)",
        "https://api.bybit.com/v5/market/recent-trade", False, f"status={status}: {detail}",
    )


def check_okx_liquidation_orders() -> CheckResult:
    """OKX documents a public /api/v5/public/liquidation-orders endpoint — attempted
    directly rather than assumed reachable."""
    status, detail = _get(
        "https://www.okx.com/api/v5/public/liquidation-orders",
        {"instType": "SWAP", "uly": "BTC-USDT", "state": "filled"},
    )
    verified = status == 200
    return CheckResult(
        "OKX public liquidation-orders", "https://www.okx.com/api/v5/public/liquidation-orders", verified, f"status={status}: {detail}",
    )


def check_coinalyze() -> CheckResult:
    """Coinalyze's liquidation-history endpoint exists (confirmed: returns a real
    'Invalid/Missing API key' error, not a 404) but requires a registered API key —
    not a fully keyless free endpoint, so it does NOT verify as "free, pollable,
    no-signup" the way this task's bar requires."""
    status, detail = _get(
        "https://api.coinalyze.net/v1/liquidation-history",
        {"symbols": "BTCUSDT_PERP.A", "interval": "1hour", "from": 1, "to": 2},
    )
    return CheckResult(
        "Coinalyze liquidation-history (requires API key)", "https://api.coinalyze.net/v1/liquidation-history",
        False, f"status={status}: {detail}",
    )


def check_existing_funding_pipeline() -> CheckResult:
    """The existing funding pipeline (nero_core.data_sources.funding_data) already
    uses this exact endpoint — this re-verifies it's still reachable and unauthenticated."""
    status, detail = _get("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": 2})
    return CheckResult(
        "Binance fapi.binance.com fundingRate (existing pipeline)", "https://fapi.binance.com/fapi/v1/fundingRate",
        status == 200, f"status={status}: {detail}",
    )


def check_glassnode_whale_transfer() -> CheckResult:
    """Glassnode's large-transaction-volume metric — confirmed to require
    authentication even on its documented free-tier endpoint (401), not a keyless
    free source. This task's instruction was explicit: do not assume it works."""
    status, detail = _get(
        "https://api.glassnode.com/v1/metrics/transactions/transfers_volume_large_sum", {"a": "BTC"},
    )
    return CheckResult(
        "Glassnode transfers_volume_large_sum (whale transfer proxy)",
        "https://api.glassnode.com/v1/metrics/transactions/transfers_volume_large_sum",
        status == 200, f"status={status}: {detail}",
    )


def check_whale_alert() -> CheckResult:
    """Whale Alert's public API requires an api_key param on every request — not a
    keyless free source."""
    status, detail = _get("https://api.whale-alert.io/v1/transactions", {"min_value": 500000, "start": 1600000000})
    return CheckResult(
        "Whale Alert transactions (whale transfer)", "https://api.whale-alert.io/v1/transactions",
        status == 200, f"status={status}: {detail}",
    )


def run_audit() -> dict[str, list[CheckResult]]:
    return {
        "liquidation_sources": [
            check_binance_force_orders(),
            *check_bybit_liquidation_endpoints(),
            check_okx_liquidation_orders(),
            check_coinalyze(),
        ],
        "diagnostics_not_liquidation_sources": [check_bybit_reachability_sanity()],
        "funding_pipeline": [check_existing_funding_pipeline()],
        "whale_transfer_sources": [check_glassnode_whale_transfer(), check_whale_alert()],
    }


def format_report(results: dict[str, list[CheckResult]]) -> str:
    lines = ["=== Task C3 STEP 1: LIQUIDATION_PREDICTOR Data Audit ===", ""]
    for section, checks in results.items():
        lines.append(f"--- {section} ---")
        for c in checks:
            status = "VERIFIED FREE+USABLE" if c.verified_free_and_usable else "NOT USABLE"
            lines.append(f"  [{status}] {c.name}")
            lines.append(f"    {c.url}")
            lines.append(f"    {c.detail}")
        lines.append("")

    any_liquidation_source_verified = any(c.verified_free_and_usable for c in results["liquidation_sources"])
    lines.append("=== Conclusion ===")
    if any_liquidation_source_verified:
        lines.append("A free, pollable liquidation source verified — proceed to STEP 2 build.")
    else:
        lines.append(
            "NO free, pollable, keyless REST liquidation-data source verified. Per the "
            "task's own instruction, LIQUIDATION_PREDICTOR is marked BLOCKED-ON-DATA — "
            "only this audit is committed, no strategy code, never a proxy-faked signal."
        )
    return "\n".join(lines)


def main() -> None:
    print(format_report(run_audit()))


if __name__ == "__main__":
    main()
