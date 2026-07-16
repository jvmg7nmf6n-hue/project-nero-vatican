"""Ported from the original NERO nero_app/core/white_house_dataset_builder.py — the
forward-return / impact-score enrichment logic is unchanged. Import path and default
data paths are adapted to this repo's layout only.

AUDIT NOTE (see docs/white_house_audit.md): `_price_on_or_after` picks the first price
row with `date >= event_date`, i.e. it assumes the event's `date` column IS the moment
the market could first react — no time-of-day is modeled, and no distinction is made
between "when the event happened" and "when it became public knowledge." See the audit
doc for why this matters for lookahead-bias risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DEFAULT_INPUT_PATH = Path("data/white_house_market_events.csv")
DEFAULT_OUTPUT_PATH = Path("data/white_house_market_events_enriched.csv")
DEFAULT_SUMMARY_PATH = Path("data/white_house_impact_summary.csv")
HORIZONS = (1, 7, 30)


@dataclass(frozen=True)
class DatasetBuildResult:
    enriched_path: Path
    summary_path: Path
    events: int
    btc_enriched: int
    gold_enriched: int


def load_event_memory(path: Path = DEFAULT_INPUT_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path).fillna("")
    except (OSError, UnicodeDecodeError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def load_price_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"date", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Price CSV missing columns: {', '.join(sorted(missing))}")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def enrich_events_with_returns(events: pd.DataFrame, btc_prices: pd.DataFrame | None = None, gold_prices: pd.DataFrame | None = None) -> pd.DataFrame:
    enriched = events.copy()
    if enriched.empty:
        return enriched
    enriched["date"] = pd.to_datetime(enriched["date"], errors="coerce")
    if btc_prices is not None and not btc_prices.empty:
        enriched = _attach_asset_returns(enriched, btc_prices, "btc")
    if gold_prices is not None and not gold_prices.empty:
        enriched = _attach_asset_returns(enriched, gold_prices, "gold")
    enriched["date"] = enriched["date"].dt.date.astype(str)
    return enriched


def build_impact_summary(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["group", "events", "btc_avg_7d", "gold_avg_7d", "btc_hit_rate", "gold_hit_rate", "avg_confidence"])
    rows: list[dict[str, object]] = []
    for tag in sorted(_all_tags(events)):
        group = events[events["tags"].astype(str).str.contains(fr"(?:^|\|){tag}(?:\||$)", regex=True, na=False)]
        rows.append(_summary_row(tag, group))
    if "event_type" in events:
        for event_type, group in events.groupby("event_type", dropna=False):
            rows.append(_summary_row(f"event_type:{event_type}", group))
    return pd.DataFrame(rows).sort_values(["events", "group"], ascending=[False, True]).reset_index(drop=True)


def build_white_house_dataset(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    btc_price_path: Path | None = None,
    gold_price_path: Path | None = None,
) -> DatasetBuildResult:
    events = load_event_memory(input_path)
    btc_prices = load_price_csv(btc_price_path) if btc_price_path else None
    gold_prices = load_price_csv(gold_price_path) if gold_price_path else None
    enriched = enrich_events_with_returns(events, btc_prices=btc_prices, gold_prices=gold_prices)
    summary = build_impact_summary(enriched)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_path, index=False)
    summary.to_csv(summary_path, index=False)

    return DatasetBuildResult(
        enriched_path=output_path,
        summary_path=summary_path,
        events=int(len(enriched)),
        btc_enriched=_count_numeric(enriched, "btc_return_7d"),
        gold_enriched=_count_numeric(enriched, "gold_return_7d"),
    )


def _attach_asset_returns(events: pd.DataFrame, prices: pd.DataFrame, prefix: str) -> pd.DataFrame:
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    if prices.empty:
        return events

    enriched = events.copy()
    for index, row in enriched.iterrows():
        event_date = row.get("date")
        if pd.isna(event_date):
            continue
        base_price = _price_on_or_after(prices, pd.Timestamp(event_date))
        if base_price is None:
            continue
        enriched.at[index, f"{prefix}_price_at_event"] = round(base_price, 8)
        for horizon in HORIZONS:
            future_price = _price_on_or_after(prices, pd.Timestamp(event_date) + pd.Timedelta(days=horizon))
            if future_price is None or base_price == 0:
                continue
            enriched.at[index, f"{prefix}_return_{horizon}d"] = round((future_price - base_price) / base_price, 8)
        score = _impact_score(prices, pd.Timestamp(event_date), base_price, days=7)
        if score is not None:
            enriched.at[index, f"{prefix}_impact_score"] = round(score, 2)
    return enriched


def _price_on_or_after(prices: pd.DataFrame, date: pd.Timestamp) -> float | None:
    rows = prices[prices["date"] >= date]
    if rows.empty:
        return None
    return float(rows.iloc[0]["close"])


def _impact_score(prices: pd.DataFrame, event_date: pd.Timestamp, base_price: float, days: int) -> float | None:
    future_price = _price_on_or_after(prices, event_date + pd.Timedelta(days=days))
    if future_price is None or base_price == 0:
        return None
    returns = prices["close"].pct_change().dropna()
    daily_vol = float(returns.std()) if not returns.empty else 0.0
    expected_move = max(0.01, daily_vol * (days ** 0.5))
    actual_move = abs((future_price - base_price) / base_price)
    return min(100.0, (actual_move / expected_move) * 50.0)


def _all_tags(events: pd.DataFrame) -> set[str]:
    tags: set[str] = set()
    if "tags" not in events:
        return tags
    for value in events["tags"].astype(str):
        tags.update(item.strip() for item in value.split("|") if item.strip())
    return tags


def _summary_row(group_name: str, group: pd.DataFrame) -> dict[str, object]:
    btc_returns = pd.to_numeric(group.get("btc_return_7d", pd.Series(dtype=float)), errors="coerce").dropna()
    gold_returns = pd.to_numeric(group.get("gold_return_7d", pd.Series(dtype=float)), errors="coerce").dropna()
    confidence = pd.to_numeric(group.get("confidence", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "group": group_name,
        "events": int(len(group)),
        "btc_avg_7d": round(float(btc_returns.mean()), 6) if not btc_returns.empty else 0.0,
        "gold_avg_7d": round(float(gold_returns.mean()), 6) if not gold_returns.empty else 0.0,
        "btc_hit_rate": round(float((btc_returns > 0).mean()), 4) if not btc_returns.empty else 0.0,
        "gold_hit_rate": round(float((gold_returns > 0).mean()), 4) if not gold_returns.empty else 0.0,
        "avg_confidence": round(float(confidence.mean()), 4) if not confidence.empty else 0.0,
    }


def _count_numeric(frame: pd.DataFrame, column: str) -> int:
    if column not in frame:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").notna().sum())
