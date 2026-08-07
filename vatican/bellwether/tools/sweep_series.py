"""Runs the same 180-cycle sweep across a SERIES of wiring configurations
(mock, 1 real agent, 2 real-ish, current full wiring) by monkeypatching the
real-fetch functions to fail for fields not in that configuration -- lets
docs/bellwether_stage2_report.md report a directly comparable series in one
run, matching the format of the 2026-08-07 update's own table.

This is a REPORTING tool, not part of the engine -- it monkeypatches
bellwether.data.providers' module-level fetch functions for the duration of
each configuration's sweep, then restores them.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BELLWETHER_ROOT = Path(__file__).resolve().parents[1]
_VATICAN_ROOT = _BELLWETHER_ROOT.parents[1]
sys.path.insert(0, str(_BELLWETHER_ROOT))
sys.path.insert(0, str(_VATICAN_ROOT))

import asyncio

import bellwether.data.providers as providers_mod

from sweep import run_sweep, summarize  # noqa: E402


def _fail(*_a, **_k):
    raise RuntimeError("disabled for this sweep configuration")


# Each entry: which real fields stay ENABLED (everything else force-fails
# to synthetic). real_yield_10y (DFII10) has no toggle here -- it's real in
# every "live" configuration, matching monetary_policy's original priority-1
# wiring order (it was real before dxy/vix/funding ever were).
CONFIGS = {
    "mock": None,
    "live_1_real (real_yield_10y only)": [],
    "live_2_real_ish (+liquidity via vix)": ["vix"],
    "live_current (+dxy, +derivatives via funding)": ["dxy", "vix", "funding"],
}


async def run_config(name: str, enabled: list[str] | None) -> dict:
    providers_mod._DXY_CACHE.clear()
    providers_mod._VIX_CACHE.clear()
    providers_mod._BTC_FUNDING_CACHE.clear()

    if enabled is None:  # mock
        rows = await run_sweep("mock")
        return summarize(rows)

    orig_dxy = providers_mod._fetch_real_dxy_level_cached
    orig_vix = providers_mod._fetch_real_vix_level_cached
    orig_funding = providers_mod._fetch_real_btc_funding_bps_cached
    if "dxy" not in enabled:
        providers_mod._fetch_real_dxy_level_cached = _fail
    if "vix" not in enabled:
        providers_mod._fetch_real_vix_level_cached = _fail
    if "funding" not in enabled:
        providers_mod._fetch_real_btc_funding_bps_cached = _fail
    try:
        rows = await run_sweep("live")
        return summarize(rows)
    finally:
        providers_mod._fetch_real_dxy_level_cached = orig_dxy
        providers_mod._fetch_real_vix_level_cached = orig_vix
        providers_mod._fetch_real_btc_funding_bps_cached = orig_funding


async def main() -> None:
    for name, enabled in CONFIGS.items():
        summary = await run_config(name, enabled)
        print(f"\n=== {name} ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
