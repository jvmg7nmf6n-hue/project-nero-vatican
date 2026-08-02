"""CLI entrypoint / orchestrator for Eve: kill-switch check -> one session
-> score every hypothesis it produced -> FDR correction -> contamination
tags -> persist scored results back into the same three allowlisted files.
Mirrors nero_core.research_agent.pipeline's own conventions (kill-switch
checked first, ANTHROPIC_API_KEY read exactly once via os.getenv and passed
explicitly thereafter, never printed/logged).

ISOLATION: imports nero_core.eve.* plus
nero_core.execution.export_candle_data.candle_filename -- NOT under
nero_core/research_agent/ (Adam's own pipeline.py already reuses this exact
same helper for its own default candle provider; it is this codebase's
established, neutral place candle-file naming lives, not a
research_agent-specific convention). No nero_core.research_agent import
anywhere in this file -- test_eve_no_auto_wire.py confirms this file has
zero such imports (unlike nero_core.eve.scoring, this module's own dynamic
call INTO scoring.score_all is where the one documented exception actually
lives, not here)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from nero_core.execution.export_candle_data import candle_filename
from nero_core.eve import context as eve_context
from nero_core.eve import scoring, session, storage
from nero_core.eve.config import is_enabled

REPO_ROOT = storage.REPO_ROOT
DEFAULT_CANDLES_DIR = REPO_ROOT / "docs" / "site_data" / "candles"
# Full-history research export (nero_core.execution.export_candle_data.
# export_research_candle_data) -- a SEPARATE, larger export than the
# website's own 200-row display export above. Checked FIRST: scoring needs
# real backtest history, not a chart-sized slice (see
# docs/investigations/eve_engine_v1_report.md's own finding that 200 candles
# left ma200 NaN everywhere but the last row, and zero of 200 random
# baseline hypotheses ever reached MIN_SAMPLE_SIZE out-of-sample trades).
# NOT every (asset, timeframe) pair has a research export yet (BTC/4h only,
# "to start") -- falls back to DEFAULT_CANDLES_DIR below for any pair
# without one, so a missing research file never silently produces
# no-candle-data where the site export would have worked.
DEFAULT_RESEARCH_CANDLES_DIR = REPO_ROOT / "docs" / "research_data" / "candles"

CandlesProvider = Callable[[str, str], "pd.DataFrame | None"]


def _read_candles_file(path: Path) -> "pd.DataFrame | None":
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        rows = data["candles"]
        return pd.DataFrame({
            "close_time": [int(c["time"]) * 1000 for c in rows],
            "close": [float(c["close"]) for c in rows],
            "high": [float(c["high"]) for c in rows],
            "low": [float(c["low"]) for c in rows],
            "volume": [float(c.get("volume") or 0.0) for c in rows],
        })
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"ERROR: {path} is malformed ({exc.__class__.__name__}: {exc}) -- treating as no candle data available.", file=sys.stderr)
        return None


def default_candles_provider(
    asset: str,
    timeframe: str,
    candles_dir: Path = DEFAULT_CANDLES_DIR,
    research_candles_dir: Path = DEFAULT_RESEARCH_CANDLES_DIR,
) -> "pd.DataFrame | None":
    """Research export FIRST (full history, where one exists), falling back
    to the website's own 200-row display export otherwise -- see the
    DEFAULT_RESEARCH_CANDLES_DIR comment above for why. This is Eve's own
    default provider only; nero_core.research_agent.pipeline's own
    default_candles_provider is UNCHANGED (still reads only the 200-row
    site export) -- deliberately not touched here, flagged for separate
    confirmation before Adam's own production data source is changed."""
    research_frame = _read_candles_file(research_candles_dir / candle_filename(asset, timeframe))
    if research_frame is not None:
        return research_frame
    return _read_candles_file(candles_dir / candle_filename(asset, timeframe))


def _compute_backtest_window_start(scored_hypotheses: list[dict], candles_provider: CandlesProvider) -> datetime | None:
    """The earliest close_time across every distinct (asset, timeframe) pair
    this session's scored hypotheses actually touched -- the LOOKAHEAD_RISK
    check's own window-start reference point (spec 3.5). None if no real
    candle data was available for anything scored this session (nothing to
    check against)."""
    earliest: datetime | None = None
    seen_pairs: set[tuple[str, str]] = set()
    for h in scored_hypotheses:
        raw = h.get("raw_hypothesis") if isinstance(h.get("raw_hypothesis"), dict) else {}
        asset, timeframe = raw.get("asset"), raw.get("timeframe")
        if not asset or not timeframe or (asset, timeframe) in seen_pairs:
            continue
        seen_pairs.add((asset, timeframe))
        candles = candles_provider(asset, timeframe)
        if candles is None or len(candles) == 0:
            continue
        first_close_time_ms = int(candles["close_time"].min())
        candidate = datetime.fromtimestamp(first_close_time_ms / 1000.0, tz=timezone.utc)
        if earliest is None or candidate < earliest:
            earliest = candidate
    return earliest


def _persist_scored_hypotheses(scored: list[dict]) -> None:
    """Rewrites eve_hypotheses.json, replacing each already-persisted
    UNSCORED record (matched by (session_id, tool_use_id) -- unique per
    propose_hypothesis call) with its scored counterpart. Atomic full-list
    rewrite (storage.atomic_write_json_list), not a second append -- scoring
    a hypothesis UPDATES its existing record, it does not duplicate it."""
    if not scored:
        return
    existing = storage.read_json_list(storage.DEFAULT_HYPOTHESES_PATH)
    by_key = {(r.get("session_id"), r.get("tool_use_id")): r for r in scored}
    updated = [by_key.get((r.get("session_id"), r.get("tool_use_id")), r) for r in existing]
    storage.atomic_write_json_list(storage.DEFAULT_HYPOTHESES_PATH, updated)


def _persist_lookahead_flags(session_record: dict, lookahead_flags: list[dict]) -> None:
    if not lookahead_flags:
        return
    updated = {**session_record, "lookahead_risk_flags": lookahead_flags}
    storage.atomic_write_json_dict(storage.session_record_path(session_record["session_id"]), updated)


@dataclass(frozen=True)
class PipelineRunResult:
    enabled: bool
    reason: str
    session_result: "session.SessionResult | None" = None
    scored_hypotheses: list = field(default_factory=list)
    lookahead_risk_flags: list = field(default_factory=list)


def run_pipeline(
    api_key: str = "",
    candles_provider: CandlesProvider = default_candles_provider,
    stub: bool | None = None,
    now: datetime | None = None,
) -> PipelineRunResult:
    """The ONE entrypoint every invocation of Eve should call. Kill-switch
    checked FIRST (nero_core.eve.config.is_enabled) -- disabled means no
    session, no LLM call, no candle fetch, no file write, anywhere, exactly
    like Adam's own pipeline.run_pipeline."""
    if not is_enabled():
        return PipelineRunResult(enabled=False, reason="EVE_ENABLED is not set to a truthy value -- no-op")

    result = session.run_session(api_key=api_key, stub=stub, now=now)

    adam_history = eve_context.load_adam_history_verdict_stripped()
    scored = scoring.score_all(result.hypothesis_records, candles_provider=candles_provider, now=now)
    scored = scoring.apply_fdr_correction(scored, field="p_value_oos")
    scored = scoring.apply_fdr_correction(scored, field="p_value_is")
    scored = scoring.apply_derivative_tags(scored, adam_history=adam_history)
    _persist_scored_hypotheses(scored)

    window_start = _compute_backtest_window_start(scored, candles_provider)
    lookahead_flags = scoring.tag_lookahead_risk(result.record, window_start) if window_start is not None else []
    _persist_lookahead_flags(result.record, lookahead_flags)

    return PipelineRunResult(
        enabled=True, reason="ok", session_result=result, scored_hypotheses=scored, lookahead_risk_flags=lookahead_flags
    )


def main() -> None:
    # The ONE place in nero_core/eve/ that reads ANTHROPIC_API_KEY from the
    # environment -- read once, passed explicitly as api_key= thereafter,
    # never printed/logged (see test_eve_secret_handling.py's ast-based
    # check, mirroring test_research_agent_secret_handling.py's own).
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    result = run_pipeline(api_key=api_key)
    if not result.enabled:
        print(f"Eve pipeline: {result.reason}")
        return
    sr = result.session_result
    print(
        f"Eve session {sr.session_id}: terminated_because={sr.terminated_because}, "
        f"n_turns={sr.n_turns}, n_searches={sr.n_searches}, n_proposed={sr.n_proposed}, "
        f"session_spent_usd=${sr.session_spent_usd:.4f}, scored={len(result.scored_hypotheses)}, "
        f"lookahead_risk_flags={len(result.lookahead_risk_flags)}"
    )


if __name__ == "__main__":
    main()
