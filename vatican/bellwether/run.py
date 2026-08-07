"""CLI entrypoint: run a single analysis cycle and print the spec JSON.

Usage:
    python run.py                              # synthesis over mock market only
    python run.py "Fed signals rate cut; CPI cools to 3.1%"   # with a headline
"""
from __future__ import annotations

import asyncio
import json
import sys

from bellwether import MacroEvent, Orchestrator
from bellwether.schemas import Category, Region


async def main() -> None:
    events = []
    if len(sys.argv) > 1:
        for raw in sys.argv[1:]:
            for headline in [h.strip() for h in raw.split(";") if h.strip()]:
                events.append(MacroEvent(headline=headline, source="cli",
                                         region=Region.USA, category=Category.OTHER))

    orch = Orchestrator()
    output = await orch.analyze(events)
    print(json.dumps(output.headline_json(), indent=2, default=str))

    print("\n--- Agent confidence map ---", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
