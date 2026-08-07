"""Static JSON export of genuine Forward Trial ENTRY events (CC-1 Part D6).

D6a's precise ENTRY-event definition, confirmed against real code before writing
anything here: a Forward Trial ENTRY is an `execution_log` row (in
`data/repair_lab_forward_tracking.db` -- a SEPARATE database file from
`data/truth_ledger.db`, confirmed via `nero_core.research_agent.repair_forward_
tracker.DEFAULT_FORWARD_TRACKING_DB_PATH`) whose `strategy` column matches
`TRIAL:<trial_id>` (the exact key `nero_core.research_agent.trial.run_forward_tick`
uses, via `repair_forward_tracker._strategy_key(trial_id, "TRIAL")`) and whose
`signal_type` is `"ENTRY"`. `evaluate_forward_tick` only ever logs `"ENTRY"` when
it reconstructs NO existing open position from that trial's own prior log rows --
so every such row is, by construction, a genuine transition from flat to open,
never re-derived or inferred here.

THIS IS NOT THE SAME as `forward_trial.json`'s `status == "OPEN"` /
`opened_at` fields -- those reflect TRIAL ADMISSION lifecycle (a hypothesis
being accepted into the Trial queue), which can and often does precede the
first real market ENTRY by hours or days. Confirmed directly: as of this
export, `docs/site_data/forward_trial.json` lists 10 OPEN Trial records
sharing one identical `opened_at` batch timestamp, but `data/
repair_lab_forward_tracking.db`'s execution_log has exactly ONE real ENTRY
row (`TRIAL:7f7c5980-...`, ETH, matching ETH_BIDIRECTIONAL_ZSCORE_FADE) --
9 of the 10 "OPEN" Trial admissions have never actually opened a position.

STRICTLY READ-ONLY over both ledgers and every hypothesis source file, same
discipline as nero_core.execution.export_site_data.

KNOWN, PRE-EXISTING, OUT-OF-SCOPE FINDING (not fixed here -- a nero_core
export-script change unrelated to Part D/E's own scope): `forward_trial.json`
already publicly exports each record's `forward_tracking_db_ref` as a full
local absolute filesystem path (e.g. "C:\\Users\\<name>\\...\\data\\
repair_lab_forward_tracking.db"), leaking the machine's local username and
directory layout onto the public site. This export deliberately does NOT
repeat that mistake -- no local path of any kind is included in this file's
output. Flagging for a future, separately-scoped fix.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.research_agent.repair_forward_tracker import DEFAULT_FORWARD_TRACKING_DB_PATH
from nero_core.research_agent.trial import TRIAL_STRATEGY_PREFIX, load_trial_records
from nero_core.truth_ledger.execution_log import list_execution_log

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "site_data" / "trial_entries.json"
AGENT_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_hypotheses.json"
EVE_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "eve_hypotheses.json"


def _load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _build_asset_timeframe_lookup(
    agent_hypotheses_path: Path = AGENT_HYPOTHESES_PATH, eve_hypotheses_path: Path = EVE_HYPOTHESES_PATH
) -> dict[str, dict[str, str]]:
    """hypothesis_name -> {"asset":..., "timeframe":...}, merged from both
    Adam's (flat) and Eve's (nested under raw_hypothesis) export shapes --
    read-only over already-exported site data, never the raw internal
    session files directly."""
    lookup: dict[str, dict[str, str]] = {}
    for record in _load_json_list(agent_hypotheses_path):
        name = record.get("hypothesis_name")
        if name and "asset" in record and "timeframe" in record:
            lookup[name] = {"asset": record["asset"], "timeframe": record["timeframe"]}
    for record in _load_json_list(eve_hypotheses_path):
        raw = record.get("raw_hypothesis", {})
        name = raw.get("hypothesis_name")
        if name and "asset" in raw and "timeframe" in raw:
            lookup[name] = {"asset": raw["asset"], "timeframe": raw["timeframe"]}
    return lookup


def _trial_context_by_id(trial_records_path: Path | None = None) -> dict[str, dict]:
    context: dict[str, dict] = {}
    records = load_trial_records(trial_records_path) if trial_records_path else load_trial_records()
    for record in records:
        trial_id = record.get("trial_id")
        ref = record.get("source_hypothesis_ref", {})
        if trial_id:
            context[trial_id] = {
                "hypothesis_name": ref.get("hypothesis_name"),
                "origin_agent": ref.get("origin_agent"),
            }
    return context


def build_trial_entries(
    db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH,
    trial_records_path: Path | None = None,
    agent_hypotheses_path: Path = AGENT_HYPOTHESES_PATH,
    eve_hypotheses_path: Path = EVE_HYPOTHESES_PATH,
) -> list[dict]:
    trial_context = _trial_context_by_id(trial_records_path)
    asset_timeframe = _build_asset_timeframe_lookup(agent_hypotheses_path, eve_hypotheses_path)
    rows = list_execution_log(db_path=db_path)

    entries: list[dict] = []
    prefix = f"{TRIAL_STRATEGY_PREFIX}:"
    for row in rows:
        if not row.strategy.startswith(prefix) or row.signal_type != "ENTRY":
            continue
        trial_id = row.strategy[len(prefix):]
        context = trial_context.get(trial_id, {})
        hypothesis_name = context.get("hypothesis_name")
        timeframe_info = asset_timeframe.get(hypothesis_name, {}) if hypothesis_name else {}

        direction = None
        stop_loss = None
        target = None
        try:
            reasoning = json.loads(row.reasoning)
            direction = reasoning.get("direction")
            stop_loss = reasoning.get("stop_loss")
            target = reasoning.get("target")
        except (json.JSONDecodeError, TypeError):
            pass

        entries.append({
            "execution_log_id": row.id,
            "trial_id": trial_id,
            "hypothesis_name": hypothesis_name,
            "origin_agent": context.get("origin_agent"),
            "asset": row.asset,
            "timeframe": timeframe_info.get("timeframe"),
            "direction": direction,
            "entry_price": row.entry_price,
            "stop_loss": stop_loss,
            "target": target,
            "timestamp": row.timestamp.isoformat(),
            "candle_timestamp": row.candle_timestamp,
        })

    entries.sort(key=lambda e: e["timestamp"])
    return entries


def write_trial_entries(output_path: Path = DEFAULT_OUTPUT_PATH, **kwargs) -> Path:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "entries": build_trial_entries(**kwargs),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    path = write_trial_entries()
    print(f"Exported {path}")


if __name__ == "__main__":
    main()
