"""Ported from the original NERO nero_app/core/white_house_sources.py — the link
extraction / relevance filtering logic is unchanged. Import path and default snapshot
path are adapted to this repo's layout only.

AUDIT NOTE (see docs/white_house_audit.md): every fetch here is a plain unauthenticated
GET to a public government/academic URL — no API key is required for anything in this
file. `fetch_source_snapshot` makes ONE live HTTP request per source; it is intentionally
never called from this module's test suite (tests mock `requests.get`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import re
from pathlib import Path

import pandas as pd
import requests

from nero_core.macro_policy.white_house_impact import classify_white_house_text


DEFAULT_SOURCE_SNAPSHOT_PATH = Path("data/white_house_source_snapshot.csv")


@dataclass(frozen=True)
class OfficialSource:
    name: str
    url: str
    authority: str
    notes: str


OFFICIAL_SOURCES = [
    OfficialSource(
        name="White House Briefing Room",
        url="https://www.whitehouse.gov/briefing-room/",
        authority="official_white_house",
        notes="Current White House statements, remarks, presidential actions and briefing-room posts.",
    ),
    OfficialSource(
        name="GovInfo Presidential Documents",
        url="https://www.govinfo.gov/app/collection/CPD",
        authority="official_govinfo_nara",
        notes="Daily Compilation of Presidential Documents: speeches, press conferences, statements, orders and releases.",
    ),
    OfficialSource(
        name="American Presidency Project",
        url="https://www.presidency.ucsb.edu/",
        authority="academic_archive",
        notes="Searchable archive of presidential remarks, press conferences, orders and White House press secretary material.",
    ),
    OfficialSource(
        name="Biden White House Archive",
        url="https://bidenwhitehouse.archives.gov/briefing-room/",
        authority="official_archived_white_house",
        notes="Archived Biden administration briefing-room records.",
    ),
]


def list_official_sources() -> list[OfficialSource]:
    return list(OFFICIAL_SOURCES)


def fetch_source_snapshot(timeout_seconds: int = 12, max_links_per_source: int = 25) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source in OFFICIAL_SOURCES:
        try:
            response = requests.get(source.url, timeout=timeout_seconds, headers={"User-Agent": "ProjectNero/0.1"})
            response.raise_for_status()
            html = response.text
            links = _extract_links(html, source.url, limit=max_links_per_source)
            relevant = [link for link in links if classify_white_house_text(link["text"])]
            rows.append(
                {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "source": source.name,
                    "url": source.url,
                    "authority": source.authority,
                    "status": "ok",
                    "links_found": len(links),
                    "relevant_links": len(relevant),
                    "sample_relevant_text": " | ".join(link["text"] for link in relevant[:3]),
                    "error": "",
                }
            )
        except requests.RequestException as exc:
            rows.append(
                {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "source": source.name,
                    "url": source.url,
                    "authority": source.authority,
                    "status": "error",
                    "links_found": 0,
                    "relevant_links": 0,
                    "sample_relevant_text": "",
                    "error": exc.__class__.__name__,
                }
            )
    return pd.DataFrame(rows)


def write_source_snapshot(frame: pd.DataFrame, path: Path = DEFAULT_SOURCE_SNAPSHOT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def _extract_links(html: str, base_url: str, limit: int) -> list[dict[str, str]]:
    pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, raw_text in pattern.findall(html):
        text = _clean_html(raw_text)
        if not text:
            continue
        url = _absolute_url(href, base_url)
        key = f"{url}|{text}"
        if key in seen:
            continue
        seen.add(key)
        links.append({"url": url, "text": text})
        if len(links) >= limit:
            break
    return links


def _clean_html(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    collapsed = re.sub(r"\s+", " ", unescape(no_tags)).strip()
    return collapsed


def _absolute_url(href: str, base_url: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        domain = re.match(r"(https?://[^/]+)", base_url)
        return f"{domain.group(1)}{href}" if domain else href
    return f"{base_url.rstrip('/')}/{href}"
