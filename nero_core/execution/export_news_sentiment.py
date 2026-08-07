"""Static JSON export of every real news_sentiment_log row (CC-1 overnight
directive, Part 4). Scoped previously, never built -- real, live NEWS_SENTIMENT
signals (both the keyword-based v1.0.0 and the LLM-powered v2.0.0-llm-claude
configs) have been recorded in data/truth_ledger.db since 2026-07-18 (44 real
rows as of this export's own writing) with no way for a site visitor to see
any of them; only `nero_core.truth_ledger.execution_log.list_news_sentiment_log_for_run`
existed (one run at a time), never an all-time read.

Same read-only, "never fabricate a value" discipline as
nero_core.execution.export_trial_entries: this is a pure export of what
list_news_sentiment_log() already returns, no new computation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nero_core.truth_ledger.execution_log import list_news_sentiment_log
from nero_core.truth_ledger.models import DEFAULT_DB_PATH

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "site_data" / "news_sentiment.json"


def build_news_sentiment_export(db_path: Path = DEFAULT_DB_PATH) -> list[dict]:
    rows = list_news_sentiment_log(db_path=db_path)
    return [
        {
            "id": r.id,
            "run_id": r.run_id,
            "asset": r.asset,
            "strategy_version": r.strategy_version,
            "news_timestamp": r.news_timestamp.isoformat() if r.news_timestamp else None,
            "fetch_timestamp": r.fetch_timestamp.isoformat(),
            "sentiment_score": r.sentiment_score,
            "signal_type": r.signal_type,
            "confidence": r.confidence,
            "reasoning": r.reasoning,
            "source": r.source,
        }
        for r in rows
    ]


def write_news_sentiment_export(output_path: Path = DEFAULT_OUTPUT_PATH, db_path: Path = DEFAULT_DB_PATH) -> Path:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "entries": build_news_sentiment_export(db_path=db_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    path = write_news_sentiment_export()
    print(f"Exported {path}")


if __name__ == "__main__":
    main()
