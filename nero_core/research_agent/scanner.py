"""Task 1 -- Market Scanner.

Reads the already-exported docs/site_data/candles/, quant_metrics.json, and
quant_cross_asset.json (no network -- these are Day 1/4/5's own exports,
reused as-is, matching nero_core.execution.export_quant_metrics's own "no
network needed" convention). Produces FACTUAL, ranked scan findings only --
extreme z-scores, volatility-regime transitions, correlation breakdowns, and
assets with thin strategy coverage. No hypotheses are generated here (that is
hypothesis_gen.py's job, Task 3) and no P&L/backtest logic runs here.

Every finding carries a MEASURED (never guessed) historical frequency for that
specific condition on that specific asset/timeframe, computed directly from
the same candle file the finding was raised against -- see each scan_* / the
docstrings below for exactly how each is measured, and the measurement
window is always reported alongside the number so a reader can judge how much
to trust it (CLAUDE.md: no fabricated statistics).

Findings are grouped by TYPE and each group is sorted by its own natural
magnitude (descending) -- there is deliberately no single cross-type
"ranking score" mixing e.g. a z-score with a correlation delta, which would be
exactly the kind of uncalibrated composite score CLAUDE.md prohibits.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nero_core.quant.cross_asset import load_candle_series, rolling_correlation_matrix, volatility_regimes
from nero_core.research_agent.rule_dsl import compute_indicator_frame, count_triggers, parse_structured_rule

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDLES_DIR = REPO_ROOT / "docs" / "site_data" / "candles"
DEFAULT_QUANT_METRICS_PATH = REPO_ROOT / "docs" / "site_data" / "quant_metrics.json"
DEFAULT_QUANT_CROSS_ASSET_PATH = REPO_ROOT / "docs" / "site_data" / "quant_cross_asset.json"
DEFAULT_STRATEGIES_PATH = REPO_ROOT / "docs" / "site_data" / "strategies.json"
DEFAULT_SCANNER_STATE_PATH = REPO_ROOT / "docs" / "site_data" / "agent_scanner_state.json"

ZSCORE_EXTREME_THRESHOLD = 2.0
CORRELATION_BREAKDOWN_THRESHOLD = 0.4  # |short-window corr - long-window corr|
LONG_CORRELATION_WINDOW = 180  # long-baseline window for the breakdown check; short is the panel's own 30
GARCH_MIN_WARMUP_ROWS = 60  # build_garch_volatility_report's own floor -- see quant_intelligence.py
CALM_REGIMES = {"LOW", "NORMAL"}
TURBULENT_REGIMES = {"HIGH", "EXTREME"}


@dataclass(frozen=True)
class ScanFinding:
    finding_type: str  # "extreme_zscore" | "regime_transition" | "correlation_breakdown" | "low_strategy_coverage"
    asset: str
    timeframe: str | None
    description: str
    magnitude: float  # the natural, type-specific ranking value (e.g. |z|, |corr delta|) -- never cross-type comparable
    measured_frequency_per_year: float | None  # None only when the finding type isn't a recurring, measurable condition
    measurement_note: str
    detected_at: str


@dataclass(frozen=True)
class ScanResult:
    extreme_zscore: list[ScanFinding]
    regime_transitions: list[ScanFinding]
    correlation_breakdowns: list[ScanFinding]
    low_strategy_coverage: list[ScanFinding]
    scan_errors: list[dict[str, str]]


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _asset_series_map(
    candles_dir: Path, errors: list[dict[str, str]] | None = None
) -> dict[tuple[str, str], pd.DataFrame]:
    """(asset, timeframe) -> a candles-shaped DataFrame (close_time ms,
    close/high/low/volume) built from the raw candle JSON, reusing
    quant.cross_asset.load_candle_series for the file-loading part but
    re-attaching high/low/volume (that loader only keeps `closes`, which
    isn't enough for rule_dsl's indicator frame). A malformed individual
    candle file is skipped (never crashes the scan over one bad file) but,
    if `errors` is given, is appended to it -- previously a bare `continue`
    with zero record anywhere, meaning one corrupt file silently vanished
    from every scan that reads this map with no trace in scan_errors."""
    out: dict[tuple[str, str], pd.DataFrame] = {}
    if not candles_dir.exists():
        return out
    for path in sorted(candles_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            rows = data["candles"]
            frame = pd.DataFrame(
                {
                    "close_time": [int(c["time"]) * 1000 for c in rows],  # source `time` is unix SECONDS
                    "close": [float(c["close"]) for c in rows],
                    "high": [float(c["high"]) for c in rows],
                    "low": [float(c["low"]) for c in rows],
                    "volume": [float(c.get("volume") or 0.0) for c in rows],  # some feeds (forex) record volume: null
                }
            )
            out[(data["asset"], data["timeframe"])] = frame.sort_values("close_time").reset_index(drop=True)
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            if errors is not None:
                errors.append({"source": str(path), "message": f"{exc.__class__.__name__}: {exc}"})
            continue
    return out


def _span_years(frame: pd.DataFrame) -> float:
    if len(frame) < 2:
        return 0.0
    span_ms = float(frame["close_time"].iloc[-1] - frame["close_time"].iloc[0])
    return span_ms / (365.25 * 86_400_000.0)


def _measure_directional_frequency(frame: pd.DataFrame, field: str, op: str, threshold: float) -> tuple[int, float | None]:
    """(trigger_count, trades_per_year | None). Reuses rule_dsl's own trigger-
    counting machinery -- the SAME code path frequency_gate.py uses -- rather
    than a bespoke z-score-crossing loop."""
    indicator_frame = compute_indicator_frame(frame)
    rule = parse_structured_rule({"conditions": [{"field": field, "op": op, "value": threshold}]})
    triggers = count_triggers(indicator_frame, rule)
    span_years = _span_years(frame)
    if span_years <= 0:
        return triggers, None
    return triggers, triggers / span_years


def scan_extreme_zscore(
    quant_metrics: dict | None, candles_dir: Path, now: datetime, errors: list[dict[str, str]] | None = None
) -> list[ScanFinding]:
    """|zscore_current| > ZSCORE_EXTREME_THRESHOLD, read directly from Day 4's
    quant_metrics.json export (never recomputed here -- that IS the current
    reading). Measured frequency: how often this asset/timeframe's OWN
    rolling zscore20 (same 20-period formula, see rule_dsl.compute_indicator_
    frame) crossed above +threshold or below -threshold across the full
    available candle history, annualized over that history's own span."""
    if not quant_metrics or "metrics" not in quant_metrics:
        return []
    series_map = _asset_series_map(candles_dir, errors)
    findings: list[ScanFinding] = []
    for entry in quant_metrics["metrics"]:
        z = entry.get("zscore_current")
        if z is None or abs(z) <= ZSCORE_EXTREME_THRESHOLD:
            continue
        asset, timeframe = entry["asset"], entry["timeframe"]
        frame = series_map.get((asset, timeframe))
        if frame is None or len(frame) < 25:
            findings.append(
                ScanFinding(
                    "extreme_zscore", asset, timeframe,
                    f"{asset}/{timeframe} zscore_current={z:.2f} (|z|>{ZSCORE_EXTREME_THRESHOLD})",
                    abs(z), None, "No candle file (or too few rows) to measure historical frequency.",
                    now.isoformat(),
                )
            )
            continue
        up_count, up_rate = _measure_directional_frequency(frame, "zscore20", "gt", ZSCORE_EXTREME_THRESHOLD)
        down_count, down_rate = _measure_directional_frequency(frame, "zscore20", "lt", -ZSCORE_EXTREME_THRESHOLD)
        total_rate = None if up_rate is None or down_rate is None else up_rate + down_rate
        span_years = _span_years(frame)
        findings.append(
            ScanFinding(
                "extreme_zscore", asset, timeframe,
                f"{asset}/{timeframe} zscore_current={z:.2f} (|z|>{ZSCORE_EXTREME_THRESHOLD})",
                abs(z), total_rate,
                f"Measured {up_count + down_count} |zscore20|>{ZSCORE_EXTREME_THRESHOLD} crossings "
                f"over {span_years:.2f} years of available candle history ({len(frame)} candles).",
                now.isoformat(),
            )
        )
    return sorted(findings, key=lambda f: f.magnitude, reverse=True)


def _regime_category(regime: str) -> str | None:
    if regime in CALM_REGIMES:
        return "CALM"
    if regime in TURBULENT_REGIMES:
        return "TURBULENT"
    return None  # NO_DATA or unrecognized -- never guessed into a category


def _measure_regime_transition_frequency(frame: pd.DataFrame) -> tuple[int, float | None, str]:
    """Rebuilds an EXPANDING-WINDOW regime timeline by calling
    quant_intelligence.build_garch_volatility_report (the exact function Day 5's
    own volatility_regimes() uses) on every prefix frame.iloc[:i+1] for i from
    GARCH_MIN_WARMUP_ROWS to the end, then counts how many times the resulting
    CALM/TURBULENT category actually changes. No lookahead: prefix i+1 only
    ever sees candles 0..i, never a future one."""
    from nero_core.quant.quant_intelligence import build_garch_volatility_report

    if len(frame) <= GARCH_MIN_WARMUP_ROWS:
        return 0, None, f"Only {len(frame)} candles available (need > {GARCH_MIN_WARMUP_ROWS}) -- cannot build a regime timeline."

    transitions = 0
    previous_category: str | None = None
    for i in range(GARCH_MIN_WARMUP_ROWS, len(frame)):
        prefix = frame.iloc[: i + 1][["close"]]
        report = build_garch_volatility_report(prefix, asset="_scan_internal")
        category = _regime_category(report.regime.replace("VOL_COMPRESSED", "LOW").replace("VOL_NORMAL", "NORMAL").replace("VOL_ELEVATED", "HIGH").replace("VOL_STRESS", "EXTREME"))
        if category is not None and previous_category is not None and category != previous_category:
            transitions += 1
        if category is not None:
            previous_category = category

    span_years = _span_years(frame.iloc[GARCH_MIN_WARMUP_ROWS:])
    if span_years <= 0:
        return transitions, None, f"Measured {transitions} CALM<->TURBULENT transitions but span is zero -- cannot annualize."
    return (
        transitions, transitions / span_years,
        f"Measured {transitions} CALM<->TURBULENT regime transitions over {span_years:.2f} years "
        f"(expanding-window replay of build_garch_volatility_report from row {GARCH_MIN_WARMUP_ROWS} onward).",
    )


def scan_regime_transitions(
    volatility_regimes_current: list[dict] | None,
    candles_dir: Path,
    now: datetime,
    state_path: Path = DEFAULT_SCANNER_STATE_PATH,
    errors: list[dict[str, str]] | None = None,
) -> list[ScanFinding]:
    """Flags a CALM<->TURBULENT transition by comparing TODAY's regime (Day
    5's own quant_cross_asset.json export) against the last regime this
    scanner itself observed for that (asset, timeframe), persisted in
    `state_path`. On the very first run for a given (asset, timeframe) there
    is nothing to compare against -- no finding is raised (honest: a single
    snapshot cannot show a transition), not a fabricated one. `state_path` is
    updated with every observed regime on every call, transition or not."""
    if not volatility_regimes_current:
        return []
    series_map = _asset_series_map(candles_dir, errors)
    previous_state: dict = _load_json(state_path) or {}
    previous_regimes: dict[str, str] = previous_state.get("last_regime", {})
    new_regimes: dict[str, str] = dict(previous_regimes)

    findings: list[ScanFinding] = []
    for entry in volatility_regimes_current:
        asset, timeframe, regime = entry["asset"], entry["timeframe"], entry["regime"]
        key = f"{asset}|{timeframe}"
        current_category = _regime_category(regime)
        previous_regime = previous_regimes.get(key)
        new_regimes[key] = regime

        if current_category is None or previous_regime is None:
            continue
        previous_category = _regime_category(previous_regime)
        if previous_category is None or previous_category == current_category:
            continue

        frame = series_map.get((asset, timeframe))
        if frame is None:
            transitions, rate, note = 0, None, "No candle file to measure historical transition frequency."
        else:
            transitions, rate, note = _measure_regime_transition_frequency(frame)

        findings.append(
            ScanFinding(
                "regime_transition", asset, timeframe,
                f"{asset}/{timeframe} regime {previous_regime} ({previous_category}) -> {regime} ({current_category})",
                1.0,  # every observed transition is an equally real, discrete event -- no magnitude to rank within type
                rate, note, now.isoformat(),
            )
        )

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"schema_version": 1, "last_updated": now.isoformat(), "last_regime": new_regimes}, indent=2) + "\n")
    return findings


def scan_correlation_breakdowns(candles_dir: Path, now: datetime) -> list[ScanFinding]:
    """Compares the panel's own short-window (30) rolling_correlation_matrix
    reading against a long-window (LONG_CORRELATION_WINDOW) reading for the
    SAME pair, both computed by the exact same reused function
    (nero_core.quant.cross_asset.rolling_correlation_matrix) -- only the
    `window` argument differs. A large gap between the two means the
    recently-observed relationship has materially diverged from the pair's
    own longer-run behavior. Both readings come from real candle data; no
    correlation is fabricated or interpolated."""
    short = rolling_correlation_matrix(candles_dir, window=30)
    long = rolling_correlation_matrix(candles_dir, window=LONG_CORRELATION_WINDOW)
    long_by_key = {(p["asset_a"], p["asset_b"], p["timeframe"]): p for p in long["pairs"]}

    findings: list[ScanFinding] = []
    for pair in short["pairs"]:
        key = (pair["asset_a"], pair["asset_b"], pair["timeframe"])
        long_pair = long_by_key.get(key)
        if pair["correlation"] is None or long_pair is None or long_pair["correlation"] is None:
            continue
        delta = abs(pair["correlation"] - long_pair["correlation"])
        if delta <= CORRELATION_BREAKDOWN_THRESHOLD:
            continue
        findings.append(
            ScanFinding(
                "correlation_breakdown", f"{pair['asset_a']}-{pair['asset_b']}", pair["timeframe"],
                f"{pair['asset_a']}-{pair['asset_b']}/{pair['timeframe']}: {pair['window_used']}-candle corr="
                f"{pair['correlation']:.2f} vs {long_pair['window_used']}-candle corr={long_pair['correlation']:.2f}",
                delta, None,
                "Correlation breakdown is a point-in-time divergence, not a recurring per-year event -- "
                "no annualized frequency applies to this finding type.",
                now.isoformat(),
            )
        )
    return sorted(findings, key=lambda f: f.magnitude, reverse=True)


def scan_low_strategy_coverage(strategies_export: dict | None, quant_metrics: dict | None, now: datetime) -> list[ScanFinding]:
    """Assets present in the quant metrics universe (i.e. this project already
    tracks their candles) but with zero registered live strategy configs in
    strategies.json. A standing structural gap, not a recurring event -- no
    per-year frequency applies (honest None, not a fabricated rate)."""
    if not quant_metrics or "metrics" not in quant_metrics:
        return []
    covered_assets = {s["asset"] for s in (strategies_export or {}).get("strategies", [])}
    tracked_assets = {(m["asset"], m["timeframe"]) for m in quant_metrics["metrics"]}

    findings: list[ScanFinding] = []
    for asset, timeframe in sorted(tracked_assets):
        if asset in covered_assets:
            continue
        findings.append(
            ScanFinding(
                "low_strategy_coverage", asset, timeframe,
                f"{asset}/{timeframe} has tracked market data but zero registered live strategy configs",
                0.0, None,
                "Coverage gap is a standing state, not a recurring per-year event -- no frequency applies.",
                now.isoformat(),
            )
        )
    return findings


def run_scan(
    candles_dir: Path = DEFAULT_CANDLES_DIR,
    quant_metrics_path: Path = DEFAULT_QUANT_METRICS_PATH,
    quant_cross_asset_path: Path = DEFAULT_QUANT_CROSS_ASSET_PATH,
    strategies_path: Path = DEFAULT_STRATEGIES_PATH,
    state_path: Path = DEFAULT_SCANNER_STATE_PATH,
    now: datetime | None = None,
) -> ScanResult:
    now = now or datetime.now(timezone.utc)
    quant_metrics = _load_json(quant_metrics_path)
    quant_cross_asset = _load_json(quant_cross_asset_path)
    strategies_export = _load_json(strategies_path)

    errors: list[dict[str, str]] = []
    if quant_metrics is None:
        errors.append({"source": str(quant_metrics_path), "message": "missing or unparseable"})
    if quant_cross_asset is None:
        errors.append({"source": str(quant_cross_asset_path), "message": "missing or unparseable"})

    return ScanResult(
        extreme_zscore=scan_extreme_zscore(quant_metrics, candles_dir, now, errors),
        regime_transitions=scan_regime_transitions(
            (quant_cross_asset or {}).get("volatility_regimes"), candles_dir, now, state_path, errors
        ),
        correlation_breakdowns=scan_correlation_breakdowns(candles_dir, now) if quant_cross_asset else [],
        low_strategy_coverage=scan_low_strategy_coverage(strategies_export, quant_metrics, now),
        scan_errors=errors,
    )
