"""CC-1 directive (2026-08-07, "fix sweep.py to measure the real RSS path")
-- proves tools/sweep.py's `--mode live` genuinely reaches the SAME
production code path news_intelligence.py/geopolitical.py consume
(nero_core.execution.bellwether_overlay.build_real_macro_events), not a
parallel or mocked stand-in, and that it's fetched exactly ONCE per sweep
run (not once per cycle) -- the "recorded-real," reproducible-within-a-run
design this directive chose over a live-per-cycle network call.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_BELLWETHER_ROOT = Path(__file__).resolve().parents[1]
_VATICAN_ROOT = _BELLWETHER_ROOT.parents[1]
sys.path.insert(0, str(_BELLWETHER_ROOT))
sys.path.insert(0, str(_VATICAN_ROOT))

from bellwether.schemas import DataProvenance, MacroEvent  # noqa: E402
from tools.sweep import HEADLINE_SCENARIOS, N_SEEDS, run_sweep  # noqa: E402


async def test_mock_mode_never_fetches_real_news():
    """--mode mock must stay fully synthetic, exactly as it always has --
    this fix is scoped to the news/headline path in --mode live only."""
    with patch("nero_core.execution.bellwether_overlay.build_real_macro_events") as mock_fetch:
        rows = await run_sweep("mock")
    mock_fetch.assert_not_called()
    assert all(r["real_news_event_count"] == 0 for r in rows)


async def test_live_mode_calls_the_real_production_function_exactly_once():
    """The core Item 2c requirement: this reaches the EXACT SAME function
    bellwether_overlay.py's own production _run_bellwether_live() calls,
    imported from its real module path, not a reimplementation -- and
    exactly once for the whole run (30 seeds x 6 headlines = 180 cycles),
    never once per cycle."""
    fake_event = MacroEvent(headline="A real headline for this test.", provenance=DataProvenance.REAL)
    with patch("nero_core.execution.bellwether_overlay.build_real_macro_events",
               return_value=[fake_event]) as mock_fetch:
        rows = await run_sweep("live")
    mock_fetch.assert_called_once()
    assert len(rows) == N_SEEDS * len(HEADLINE_SCENARIOS)
    assert all(r["real_news_event_count"] == 1 for r in rows)


async def test_live_mode_real_event_provenance_reaches_the_aggregate():
    """Not just "was it fetched" -- the fetched event's own REAL provenance
    must genuinely reach news_intelligence's real aggregate output,
    identically to how production's own Orchestrator.analyze() call would
    see it. A synthetic-only baseline (empty real fetch) is compared
    directly against a real-event run using the IDENTICAL seed/headline to
    isolate the real news contribution as the only variable."""
    with patch("nero_core.execution.bellwether_overlay.build_real_macro_events", return_value=[]):
        synthetic_rows = await run_sweep("live")

    fake_event = MacroEvent(headline="Real headline forcing a MIXED provenance state.",
                            provenance=DataProvenance.REAL)
    with patch("nero_core.execution.bellwether_overlay.build_real_macro_events", return_value=[fake_event]):
        real_rows = await run_sweep("live")

    synthetic_news_provenance = {r["provenance_breakdown"]["news_intelligence"] for r in synthetic_rows}
    real_news_provenance = {r["provenance_breakdown"]["news_intelligence"] for r in real_rows}
    # With zero real events, news_intelligence can never be REAL/MIXED in any
    # cycle; with one real event added to every cycle's own scenario
    # headline (synthetic), it must become MIXED in every cycle instead.
    assert "real" not in synthetic_news_provenance and "mixed" not in synthetic_news_provenance
    assert real_news_provenance == {"mixed"}


async def test_live_mode_gracefully_degrades_to_zero_real_events_on_fetch_failure():
    """Never crashes the sweep, never guesses a substitute -- a fetch
    failure this run means zero real events for the whole run, the honest
    degrade, same discipline as every other real provider in this
    codebase."""
    with patch("nero_core.execution.bellwether_overlay.build_real_macro_events",
               side_effect=RuntimeError("simulated RSS outage")):
        rows = await run_sweep("live")
    assert len(rows) == N_SEEDS * len(HEADLINE_SCENARIOS)
    assert all(r["real_news_event_count"] == 0 for r in rows)
