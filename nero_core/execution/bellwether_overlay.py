"""Bellwether macro-conflict overlay (CC-1 comprehensive directive, Part C).

Runs Bellwether once, persists what it said (nero_core.truth_ledger.macro_reads),
then ANNOTATES ORDERFLOW_IMBALANCE/BTC entries with whether they fired against a
strong, aligned, opposing macro read. Annotate-only: this module never reads
ORDERFLOW_IMBALANCE's own decision logic and never writes to execution_log --
strategies trade exactly as they would without this file existing.

WHY ORDERFLOW_IMBALANCE/BTC, not the original GOLD-1wk Momentum target: the three
"verified survivors" (BREAKOUT_MOMENTUM/GOLD, TREND_PULLBACK/BNB,
COINTEGRATION_PAIRS/BTC-ETH) have logged zero ENTRY rows between them, ever
(confirmed directly against data/truth_ledger.db, 2026-08-07) -- an overlay
targeting them would annotate nothing. ORDERFLOW_IMBALANCE/BTC is the only
strategy actually trading (54 real entries, 2026-07-19 to 2026-08-06). See
docs/bellwether_stage2_report.md's Part C section for the full retarget writeup,
including this strategy's own honest status: EXPERIMENTAL, snapshot-based,
forward-testing only, NO BACKTEST EXISTS (nero_core/strategies/
orderflow_imbalance.py's own module docstring) -- annotating an unbacktested
strategy is a weaker experiment than annotating a verified one would have been,
stated here rather than buried.

ORDERFLOW_IMBALANCE/ETH is deliberately NOT annotated: Bellwether's Asset enum
(vatican/bellwether/bellwether/schemas.py) only has GOLD and BITCOIN -- there is no
ETH read to annotate with, not a scoping choice made here.

THE THRESHOLD (per A1's agreement/coverage split, replacing the old blended-
confidence rule): flag `conflicted=True` only when ALL of —
  1. the macro read's BITCOIN bias is directionally OPPOSITE the entry
     (BEARISH/STRONG_BEARISH vs a LONG entry; BULLISH/STRONG_BULLISH vs SHORT), AND
  2. bitcoin_agreement >= CONFLICT_AGREEMENT_THRESHOLD (0.6), AND
  3. bitcoin_coverage  >= CONFLICT_COVERAGE_THRESHOLD (0.15), AND
  4. the read's own bitcoin_analysis provenance is REAL or MIXED (never flag from
     a synthetic-only read).
0.6 agreement is chosen as meaningfully ABOVE the current live-wiring mean
(~0.52, measured in the Part A/B re-run sweep) -- only reads more aligned than
typical get to flag anything. 0.15 coverage is chosen as a floor above the
~0.135 "single-signal discretization artifact" floor found in that same sweep
(see the report) -- requires roughly 2+ real-provenance BTC signals actually
contributing, not one signal's Bias enum happening to land mid-band. ANNOTATE
ONLY: this never skips, resizes, or suppresses a trade -- see
process_orderflow_conflicts' own docstring for the circuit breaker.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BELLWETHER_ROOT = _REPO_ROOT / "vatican" / "bellwether"
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_BELLWETHER_ROOT))

from bellwether.config import Settings  # noqa: E402
from bellwether.orchestrator import Orchestrator  # noqa: E402
from bellwether.schemas import Asset  # noqa: E402

from nero_core.execution.live_scheduler import (  # noqa: E402
    ORDERFLOW_ID,
    ORDERFLOW_VERSION,
    _ORDERFLOW_DIRECTION_PATTERN,
)
from nero_core.truth_ledger.execution_log import DEFAULT_DB_PATH, list_execution_log  # noqa: E402
from nero_core.truth_ledger.macro_reads import (  # noqa: E402
    get_latest_macro_read_before,
    has_flag_for_entry,
    insert_macro_conflict_flag,
    insert_macro_read,
)

BELLWETHER_TIMEOUT_SECONDS = 60.0
CONFLICT_AGREEMENT_THRESHOLD = 0.6
CONFLICT_COVERAGE_THRESHOLD = 0.15
OPPOSING_BEARISH = {"BEARISH", "STRONG_BEARISH"}
OPPOSING_BULLISH = {"BULLISH", "STRONG_BULLISH"}
NTFY_URL = "https://ntfy.sh/Terminal3039"  # same public topic notify_ntfy.py already uses
SITE_DATA_DIR = _REPO_ROOT / "docs" / "site_data"


class BellwetherCircuitBreakerOpen(Exception):
    """Raised internally when Bellwether errors, times out, or returns a
    synthetic-only read -- caught by run_overlay_once, never propagated past it.
    Named/raised explicitly (rather than just returning None) so the reason is
    always logged, never silently swallowed."""


async def _run_bellwether_live() -> object:
    settings = Settings(data_mode="live", seed=int(datetime.now(timezone.utc).timestamp()))
    orch = Orchestrator(settings)
    return await asyncio.wait_for(orch.analyze(events=[], persist=False), timeout=BELLWETHER_TIMEOUT_SECONDS)


def run_bellwether_with_circuit_breaker() -> object:
    """Fails silent and open: any exception, timeout, or an output whose
    bitcoin_analysis provenance is SYNTHETIC/UNAVAILABLE raises
    BellwetherCircuitBreakerOpen, caught by the caller -- Bellwether can never
    take the live system down, and a synthetic-only read is treated exactly
    like a failure for annotation purposes (it would flag nothing meaningful
    anyway, per the threshold's own provenance gate)."""
    try:
        output = asyncio.run(_run_bellwether_live())
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: ANY failure must fail open, not just known types
        raise BellwetherCircuitBreakerOpen(f"{exc.__class__.__name__}: {exc}") from exc
    btc_provenance = output.provenance_breakdown.get("bitcoin_analysis")
    if btc_provenance is None or btc_provenance.value in ("synthetic", "unavailable"):
        raise BellwetherCircuitBreakerOpen(f"bitcoin_analysis provenance is {btc_provenance}")
    return output


def persist_macro_reads(output: object, run_id: str, db_path=DEFAULT_DB_PATH) -> dict[str, int | None]:
    """Persists BOTH GOLD and BITCOIN reads for transparency (Part E's future
    history view wants both, regardless of which one is currently used for
    flagging) -- returns the inserted row ids (or None if this run_id/asset
    pair was already recorded)."""
    provenance_breakdown = {k: v.value for k, v in output.provenance_breakdown.items()}
    ids: dict[str, int | None] = {}
    for asset_name, bias, agreement, coverage, prob_up in (
        ("GOLD", output.gold_bias.value, output.gold_agreement, output.gold_coverage, output.probability_up_gold),
        ("BITCOIN", output.bitcoin_bias.value, output.bitcoin_agreement, output.bitcoin_coverage,
         output.probability_up_bitcoin),
    ):
        row = insert_macro_read(
            run_id=run_id, asset=asset_name, bias=bias, confidence=output.confidence,
            agreement=agreement, coverage=coverage, probability_up=prob_up,
            provenance_breakdown=provenance_breakdown, reasoning=output.reasoning,
            risks=output.risks, alternative_scenarios=[s.model_dump() for s in output.alternative_scenarios],
            data_mode="live", timestamp=output.timestamp, db_path=db_path,
        )
        ids[asset_name] = row.id if row else None
    return ids


def _evaluate_entry(entry, macro_read) -> tuple[bool, str, str | None]:
    """Returns (conflicted, reason, entry_direction). Pure function, no I/O --
    the whole threshold rule lives here so it's independently testable."""
    match = _ORDERFLOW_DIRECTION_PATTERN.search(entry.reasoning)
    direction = match.group(1) if match else None
    if direction is None:
        return False, "entry direction not parseable from reasoning text", None

    if macro_read is None:
        return False, "no macro read exists prior to this entry's timestamp", direction

    provenance_breakdown = json.loads(macro_read.provenance_breakdown) if isinstance(
        macro_read.provenance_breakdown, str) else macro_read.provenance_breakdown
    btc_provenance = provenance_breakdown.get("bitcoin_analysis")
    if btc_provenance in ("synthetic", "unavailable", None):
        return False, f"macro read's own bitcoin_analysis provenance is {btc_provenance}", direction

    opposing = OPPOSING_BEARISH if direction == "LONG" else OPPOSING_BULLISH
    if macro_read.bias not in opposing:
        return False, f"BTC bias {macro_read.bias} does not oppose a {direction} entry", direction
    if macro_read.agreement < CONFLICT_AGREEMENT_THRESHOLD:
        return False, (f"BTC bias {macro_read.bias} opposes the entry but agreement "
                       f"{macro_read.agreement:.3f} < {CONFLICT_AGREEMENT_THRESHOLD} threshold"), direction
    if macro_read.coverage < CONFLICT_COVERAGE_THRESHOLD:
        return False, (f"BTC bias {macro_read.bias} opposes the entry but coverage "
                       f"{macro_read.coverage:.3f} < {CONFLICT_COVERAGE_THRESHOLD} threshold"), direction
    return True, (f"BTC bias {macro_read.bias} (agreement {macro_read.agreement:.3f}, "
                 f"coverage {macro_read.coverage:.3f}) opposes the {direction} entry"), direction


def process_orderflow_conflicts(db_path=DEFAULT_DB_PATH) -> list[dict]:
    """Evaluates every not-yet-evaluated ORDERFLOW_IMBALANCE/BTC ENTRY row against
    the macro read that existed at (or before) its own timestamp -- never a read
    from later in time. Every entry gets exactly one flag row, ever, whether or
    not it conflicts (status='evaluated' either way) -- a full audit trail, not
    just positive hits. Returns the list of newly-inserted conflicted flags (for
    the notification step), as plain dicts."""
    entries = [
        r for r in list_execution_log(db_path=db_path, asset="BTC", strategy=ORDERFLOW_ID)
        if r.signal_type == "ENTRY" and r.strategy_version == ORDERFLOW_VERSION
    ]
    new_conflicts: list[dict] = []
    for entry in entries:
        if has_flag_for_entry(entry.id, db_path=db_path):
            continue
        macro_read = get_latest_macro_read_before("BITCOIN", entry.timestamp, db_path=db_path)
        conflicted, reason, direction = _evaluate_entry(entry, macro_read)
        status = "insufficient_data" if macro_read is None else "evaluated"
        flag = insert_macro_conflict_flag(
            execution_log_id=entry.id, strategy=ORDERFLOW_ID, asset="BTC",
            conflicted=conflicted, status=status, reason=reason,
            macro_read_id=macro_read.id if macro_read else None,
            entry_direction=direction, db_path=db_path,
        )
        if flag and conflicted:
            new_conflicts.append({
                "execution_log_id": entry.id, "entry_price": entry.entry_price,
                "entry_direction": direction, "reason": reason,
                "timestamp": entry.timestamp.isoformat(),
            })
    return new_conflicts


def send_conflict_notifications(new_conflicts: list[dict]) -> None:
    """Best-effort, never raises -- same non-fatal discipline as notify_ntfy.py's
    own send_ntfy_notification. No secrets in the message body (this data is
    already public in the Truth Ledger once exported)."""
    if not new_conflicts:
        return
    import requests

    for c in new_conflicts:
        price_text = f"{c['entry_price']:.2f}" if c["entry_price"] is not None else "n/a"
        message = (f"Vatican | BTC OrderflowImbalance (experimental) | macro_conflicted | "
                   f"{c['entry_direction']} @ {price_text} | {c['reason']}")
        try:
            response = requests.post(NTFY_URL, data=message.encode("utf-8"), timeout=10)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"ntfy conflict notification failed (non-fatal): {exc.__class__.__name__}: {exc}")


def export_macro_reads_json(db_path=DEFAULT_DB_PATH, output_dir: Path = SITE_DATA_DIR) -> Path:
    """Static JSON export, same schema_version/last_updated convention as
    nero_core.execution.export_site_data. Strictly read-only over the ledger."""
    from nero_core.truth_ledger.macro_reads import list_macro_conflict_flags, list_macro_reads

    output_dir.mkdir(parents=True, exist_ok=True)
    reads = list_macro_reads(db_path=db_path)
    flags = list_macro_conflict_flags(db_path=db_path)
    payload = {
        "schema_version": 1,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "macro_reads": [
            {
                "run_id": r.run_id, "timestamp": r.timestamp.isoformat(), "asset": r.asset,
                "bias": r.bias, "confidence": r.confidence, "agreement": r.agreement,
                "coverage": r.coverage, "probability_up": r.probability_up,
                "provenance_breakdown": r.provenance_breakdown, "reasoning": r.reasoning,
                "risks": r.risks, "alternative_scenarios": r.alternative_scenarios,
                "data_mode": r.data_mode,
            }
            for r in reads
        ],
        "conflict_flags": [
            {
                "execution_log_id": f.execution_log_id, "macro_read_id": f.macro_read_id,
                "strategy": f.strategy, "asset": f.asset, "entry_direction": f.entry_direction,
                "conflicted": f.conflicted, "status": f.status, "reason": f.reason,
                "evaluated_at": f.evaluated_at.isoformat(),
            }
            for f in flags
        ],
    }
    out_path = output_dir / "macro_reads.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    run_id = f"bellwether-overlay-{uuid.uuid4().hex[:12]}"
    try:
        output = run_bellwether_with_circuit_breaker()
    except BellwetherCircuitBreakerOpen as exc:
        print(f"Bellwether circuit breaker OPEN, failing silent and open: {exc}")
        return
    except Exception:  # noqa: BLE001 -- last-resort guard, must never crash the workflow step
        print("Bellwether overlay: unexpected failure, failing silent and open:")
        traceback.print_exc()
        return

    ids = persist_macro_reads(output, run_id)
    print(f"Persisted macro_reads: {ids}")

    new_conflicts = process_orderflow_conflicts()
    print(f"Newly evaluated conflicts this run: {len(new_conflicts)}")
    send_conflict_notifications(new_conflicts)

    out_path = export_macro_reads_json()
    print(f"Exported {out_path}")


if __name__ == "__main__":
    main()
