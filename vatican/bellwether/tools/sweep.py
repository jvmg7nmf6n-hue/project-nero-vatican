"""Bellwether real-vs-mock sweep tool (Stage 2, Parts A/B).

Runs N seeds x M headline scenarios through the Orchestrator (persist=False)
and reports confidence/agreement/coverage/NEUTRAL-rate statistics. Matches
the "30 seeds x 6 headline scenarios, n=180" methodology described in
docs/bellwether_audit.md and docs/bellwether_stage2_report.md.

HONESTY NOTE: the original Stage 0/Stage 2 sweeps were run ad hoc and never
committed as a script -- this tool is newly authored to match the same
METHODOLOGY (30 seeds x 6 headlines = 180 cycles), but the exact headline
text used previously is not preserved anywhere in this repo. Numbers from
this tool are comparable to prior runs in aggregate shape (same seed range,
same cycle count) but not guaranteed byte-identical, since headline content
has some influence on individual cycle outcomes (see the audit's own
"headline content barely moves the outcome" finding, which bounds how much
this matters).

REAL NEWS/GEOPOLITICAL PATH (CC-1 directive, 2026-08-07, "fix sweep.py to
measure the real RSS path"): this file predates real RSS wiring entirely
(committed 2026-08-07 07:42, before nero_core.execution.bellwether_overlay
.build_real_macro_events existed) -- each cycle's HEADLINE_SCENARIOS entry
was, and remains, a hand-authored SYNTHETIC-provenance event testing how
the pipeline reacts to a specific macro narrative, never a stand-in for a
live feed by deliberate design (no comment or reasoning to that effect
exists anywhere in this file's own history). In `--mode live`, this tool
now ALSO fetches build_real_macro_events() ONCE per run (not once per
cycle) and adds those REAL-provenance events to every one of the 180
cycles alongside that cycle's own scenario headline -- the SAME
"fetch-once, reuse for the whole run" process-lifetime-cache pattern every
other real field in this tool already uses (dxy/vix/real_yield/funding/
stablecoin all cache their own real fetch for the run's lifetime; see
bellwether/data/providers.py's own _DXY_CACHE/_VIX_CACHE/
_BTC_FUNDING_CACHE/_STABLECOIN_CACHE). This is "recorded-real," not "live
per-cycle": one real, current RSS snapshot, reused across all 30 seeds x 6
headlines for reproducible within-run comparison -- NOT the same thing as
a continuously live feed (a real snapshot from THIS run's own start time,
not from whenever each individual cycle happens to execute), disclosed
here rather than implied. `--mode mock` is completely unaffected --
mock mode stays fully synthetic across every field, as it always has.

Usage:
    python tools/sweep.py --mode mock
    python tools/sweep.py --mode live
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

_BELLWETHER_ROOT = Path(__file__).resolve().parents[1]
_VATICAN_ROOT = _BELLWETHER_ROOT.parents[1]  # repo root, so nero_core is importable for the real-data path
sys.path.insert(0, str(_BELLWETHER_ROOT))
sys.path.insert(0, str(_VATICAN_ROOT))

from bellwether.config import Settings
from bellwether.orchestrator import Orchestrator
from bellwether.schemas import MacroEvent

HEADLINE_SCENARIOS = [
    "Fed signals rate cut amid cooling inflation",
    "Hot CPI print reignites hawkish Fed repricing",
    "Record Bitcoin spot ETF inflows reported",
    "Geopolitical tension escalates, safe-haven demand rises",
    "Dollar rallies on stronger-than-expected payrolls",
    "Risk-on rally as global growth data surprises higher",
]

N_SEEDS = 30


def _fetch_real_news_events_once(mode: str) -> list[MacroEvent]:
    """`--mode live` only -- fetches the SAME real RSS pipeline production
    uses, exactly once per sweep run (never per-cycle), matching every
    other real field's own process-lifetime-cache convention in this tool.
    Returns [] (never guesses/fabricates) on any failure -- import failure,
    network error, or a genuine no-real-match RSS cycle -- so a sweep can
    still run start to finish even when the real feed is unreachable,
    degrading exactly like every other real fetch in this codebase."""
    if mode != "live":
        return []
    try:
        from nero_core.execution.bellwether_overlay import build_real_macro_events

        return build_real_macro_events()
    except Exception:  # noqa: BLE001 -- a sweep run must never crash on this
        return []


async def run_sweep(mode: str) -> list[dict]:
    real_news_events = _fetch_real_news_events_once(mode)
    rows = []
    for seed in range(N_SEEDS):
        for headline in HEADLINE_SCENARIOS:
            settings = Settings(data_mode=mode, seed=seed)
            orch = Orchestrator(settings)
            cycle_events = [MacroEvent(headline=headline)] + real_news_events
            out = await orch.analyze(events=cycle_events, persist=False)
            rows.append({
                "seed": seed,
                "headline": headline,
                "confidence": out.confidence,
                "gold_bias": out.gold_bias.value,
                "bitcoin_bias": out.bitcoin_bias.value,
                "gold_agreement": out.gold_agreement,
                "gold_coverage": out.gold_coverage,
                "bitcoin_agreement": out.bitcoin_agreement,
                "bitcoin_coverage": out.bitcoin_coverage,
                "provenance_breakdown": {k: v.value for k, v in out.provenance_breakdown.items()},
                "real_news_event_count": len(real_news_events),
            })
    return rows


def summarize(rows: list[dict]) -> dict:
    conf = [r["confidence"] for r in rows]
    g_agree = [r["gold_agreement"] for r in rows]
    g_cov = [r["gold_coverage"] for r in rows]
    b_agree = [r["bitcoin_agreement"] for r in rows]
    b_cov = [r["bitcoin_coverage"] for r in rows]
    n = len(rows)
    return {
        "n": n,
        "mean_confidence": round(statistics.mean(conf), 3),
        "median_confidence": round(statistics.median(conf), 3),
        "min_confidence": round(min(conf), 3),
        "max_confidence": round(max(conf), 3),
        "stdev_confidence": round(statistics.stdev(conf), 3) if n > 1 else 0.0,
        "pct_below_035": round(100 * sum(1 for c in conf if c < 0.35) / n, 1),
        "pct_gold_neutral": round(100 * sum(1 for r in rows if r["gold_bias"] == "NEUTRAL") / n, 1),
        "pct_bitcoin_neutral": round(100 * sum(1 for r in rows if r["bitcoin_bias"] == "NEUTRAL") / n, 1),
        "mean_gold_agreement": round(statistics.mean(g_agree), 3),
        "mean_gold_coverage": round(statistics.mean(g_cov), 3),
        "mean_bitcoin_agreement": round(statistics.mean(b_agree), 3),
        "mean_bitcoin_coverage": round(statistics.mean(b_cov), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    args = parser.parse_args()
    rows = asyncio.run(run_sweep(args.mode))
    summary = summarize(rows)
    print(f"mode={args.mode} n={summary['n']}")
    for k, v in summary.items():
        if k != "n":
            print(f"  {k}: {v}")
    # Which agents actually contributed real/mixed provenance this sweep, from the last cycle
    # (provenance doesn't vary cycle-to-cycle within one sweep -- same providers, same session).
    last_breakdown = rows[-1]["provenance_breakdown"]
    print(f"  provenance_breakdown (last cycle): {last_breakdown}")
    # CC-1 directive (2026-08-07, "fix sweep.py to measure the real RSS
    # path"): disclose how many real RSS events were actually fetched and
    # reused across this whole run -- 0 in --mode mock always, and 0 in
    # --mode live too if the real feed happened to be unreachable this run
    # (never silently implied to be nonzero).
    print(f"  real_news_event_count (fetched once, reused across all {summary['n']} cycles): "
          f"{rows[-1]['real_news_event_count']}")


if __name__ == "__main__":
    main()
