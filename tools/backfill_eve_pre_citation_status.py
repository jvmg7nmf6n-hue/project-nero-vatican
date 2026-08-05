"""CC-1 directive (2026-08-05), item 5 -- ONE-TIME backfill.

Every hypothesis record persisted to docs/site_data/eve_hypotheses.json
before this same directive's item 1 (supporting_source_urls /
citation_status) shipped predates that mechanism entirely -- nobody ever
asked Eve to cite a source for these, so they carry no `supporting_source_
urls` / `citation_status` key at all.

Left alone, such a record would read identically to one that WAS asked and
genuinely cited nothing (nero_core.eve.scoring.CITATION_STATUS_NO_SOURCES_
CLAIMED) -- a false pass, indistinguishable from "checked, found clean."
Item 5's own words: "they must not read as clean."

This script marks every such record explicitly with
`citation_status: "unscoreable_pre_citation"`
(nero_core.eve.scoring.CITATION_STATUS_UNSCOREABLE_PRE_CITATION) -- a status
classify_citation_status itself never produces; it exists only for this
backfill. Nothing is fabricated: no retroactive `supporting_source_urls` is
invented for any record (item 5's own explicit prohibition), and
raw_hypothesis is never touched at all.

IDEMPOTENT: a record that already carries a `citation_status` key (of any
value, including from a prior run of this same script) is left untouched --
safe to re-run.

Run once, directly:
    python tools/backfill_eve_pre_citation_status.py
"""
from __future__ import annotations

from nero_core.eve import scoring, storage


def backfill(path=storage.DEFAULT_HYPOTHESES_PATH) -> int:
    records = storage.read_json_list(path)
    n_marked = 0
    updated = []
    for r in records:
        if isinstance(r, dict) and "citation_status" not in r:
            r = {
                **r,
                "supporting_source_urls_validated": None,
                "supporting_source_urls_invalid": None,
                "citation_status": scoring.CITATION_STATUS_UNSCOREABLE_PRE_CITATION,
                "per_hypothesis_freshness": {
                    "result": scoring.PER_HYPOTHESIS_FRESHNESS_UNSCOREABLE_PRE_CITATION,
                    "hypothesis_name": (r.get("raw_hypothesis") or {}).get("hypothesis_name"),
                },
            }
            n_marked += 1
        updated.append(r)
    if n_marked:
        storage.atomic_write_json_list(path, updated)
    return n_marked


def main() -> None:
    n_marked = backfill()
    print(f"backfill_eve_pre_citation_status: marked {n_marked} pre-citation record(s) as "
          f"citation_status={scoring.CITATION_STATUS_UNSCOREABLE_PRE_CITATION!r} in {storage.DEFAULT_HYPOTHESES_PATH}")


if __name__ == "__main__":
    main()
