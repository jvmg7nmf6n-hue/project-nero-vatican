"""RSS news feed client — ported near-verbatim from the original NERO codebase
(nero_app/core/news_feed.py at C:\\Users\\HP\\Documents\\Codex\\2026-07-06\\tu, read-only
source, not modified). No secrets involved (public RSS feeds only); logic and keyword
lists are unchanged from the original.

`NewsItem.published` is the feed's own RFC822 `pubDate` string, kept as raw text here —
parsing it into a real timestamp (and enforcing the lookahead buffer against it) is
nero_core.strategies.news_sentiment's job, not this client's.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import xml.etree.ElementTree as ET

import requests

RSS_FEEDS = {
    "Reuters": "https://feeds.reuters.com/reuters/businessNews",
    "CNBC": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "MarketWatch Economy": "https://feeds.marketwatch.com/marketwatch/economy",
}

FALLBACK_HEADLINES = [
    "Fed officials signal caution as markets reassess rate cut timing.",
    "Oil prices rise as supply risk grows around key shipping routes.",
    "Gold holds firm as investors hedge inflation and geopolitical uncertainty.",
    "Crypto risk appetite improves as liquidity expectations stabilize.",
    "Transport shares weaken as investors question forward economic demand.",
]

GOLD_KEYWORDS = ["gold", "xau", "xauusd", "bullion", "precious metal", "gold price", "gold futures", "spot gold", "safe haven", "gold reserve", "gold mining", "gold etf", "comex"]
CRYPTO_KEYWORDS = ["crypto", "bitcoin", "btc", "ethereum", "eth", "blockchain", "altcoin", "solana", "binance"]
MACRO_KEYWORDS = ["economy", "economic", "gdp", "cpi", "ppi", "inflation", "deflation", "stagflation", "consumer spending", "consumer confidence", "retail sales", "manufacturing", "services pmi", "pmi", "employment", "jobless", "nonfarm payroll", "nfp", "payroll", "unemployment", "wages", "housing", "real estate"]
CENTRAL_BANK_KEYWORDS = ["fed", "federal reserve", "fomc", "powell", "jerome powell", "ecb", "lagarde", "bank of england", "boe", "boj", "bank of japan", "pboc", "people's bank of china", "rba", "rbi", "interest rate", "rate hike", "rate cut", "monetary policy", "quantitative easing", "qe", "tightening"]
STOCK_KEYWORDS = ["stock", "stocks", "equity", "share", "shares", "nasdaq", "dow", "dow jones", "s&p", "s&p500", "russell", "wall street", "earnings", "revenue", "profit", "ipo", "market cap"]
FOREX_KEYWORDS = ["forex", "currency", "dollar", "usd", "eur", "euro", "gbp", "sterling", "yen", "jpy", "yuan", "cny", "cad", "aud", "nzd", "swiss franc", "chf", "exchange rate", "dxy"]
COMPANY_KEYWORDS = ["apple", "microsoft", "google", "alphabet", "amazon", "meta", "tesla", "nvidia", "amd", "intel", "tsmc", "openai", "oracle", "blackrock", "microstrategy", "coinbase", "paypal", "visa", "mastercard", "fedex"]
COMMODITY_KEYWORDS = ["oil", "brent", "wti", "natural gas", "lng", "gas", "copper", "nickel", "iron ore", "lithium", "uranium", "commodity"]
GEO_KEYWORDS = ["war", "conflict", "missile", "attack", "sanctions", "tariff", "trade war", "iran", "israel", "ukraine", "russia", "china", "taiwan", "north korea", "middle east", "nato", "opec", "opec+"]
SENTIMENT_WORDS = ["surge", "jump", "rise", "gain", "record high", "breakout", "rally", "selloff", "crash", "drop", "collapse", "weak", "strong", "bullish", "bearish", "volatility"]

TARGET_KEYWORDS = {
    "Gold": GOLD_KEYWORDS,
    "Crypto": CRYPTO_KEYWORDS,
    "Macro": MACRO_KEYWORDS,
    "Stocks": STOCK_KEYWORDS,
    "Companies": COMPANY_KEYWORDS,
    "Commodities": COMMODITY_KEYWORDS,
    "Forex": FOREX_KEYWORDS,
    "Central Banks": CENTRAL_BANK_KEYWORDS,
    "Geopolitics": GEO_KEYWORDS,
    "Sentiment": SENTIMENT_WORDS,
}

KEYWORDS = {
    "BTC": CRYPTO_KEYWORDS + CENTRAL_BANK_KEYWORDS + MACRO_KEYWORDS + SENTIMENT_WORDS,
    "ETH": CRYPTO_KEYWORDS + CENTRAL_BANK_KEYWORDS + MACRO_KEYWORDS + SENTIMENT_WORDS,
    "GOLD": GOLD_KEYWORDS + FOREX_KEYWORDS + CENTRAL_BANK_KEYWORDS + GEO_KEYWORDS + MACRO_KEYWORDS,
    "OIL": COMMODITY_KEYWORDS + GEO_KEYWORDS + MACRO_KEYWORDS + SENTIMENT_WORDS,
    "FDX": ["fedex", "transport", "shipping", "consumer", "growth", "economy"] + STOCK_KEYWORDS + MACRO_KEYWORDS,
    "SPY": STOCK_KEYWORDS + CENTRAL_BANK_KEYWORDS + MACRO_KEYWORDS + SENTIMENT_WORDS,
}


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    link: str
    published: str
    tags: list[str]


@dataclass(frozen=True)
class NewsFeedResult:
    headlines: list[NewsItem]
    status: str


class NewsFeedClient:
    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def load(self, asset: str, limit: int = 12) -> NewsFeedResult:
        items: list[NewsItem] = []
        errors: list[str] = []
        for source, url in RSS_FEEDS.items():
            try:
                items.extend(self._load_feed(source, url))
            except requests.RequestException as exc:
                errors.append(f"{source}: {exc.__class__.__name__}")
            except ET.ParseError:
                errors.append(f"{source}: ParseError")

        filtered = _rank_for_asset(items, asset)
        if filtered:
            return NewsFeedResult(headlines=filtered[:limit], status=f"live ({len(filtered)} matched)")

        fallback = [
            NewsItem(
                title=headline,
                source="Sample Macro Feed",
                link="",
                published=datetime.now().isoformat(),
                tags=categorize_headline(headline),
            )
            for headline in FALLBACK_HEADLINES
        ]
        status = "fallback: no matching headlines"
        if errors:
            status = f"fallback: {'; '.join(errors[:2])}"
        return NewsFeedResult(headlines=fallback[:limit], status=status)

    def _load_feed(self, source: str, url: str) -> list[NewsItem]:
        response = requests.get(url, timeout=self.timeout_seconds, headers={"User-Agent": "ProjectVatican/0.1"})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = []
        for item in root.findall(".//item"):
            title = _text(item, "title")
            if not title:
                continue
            items.append(
                NewsItem(
                    title=title,
                    source=source,
                    link=_text(item, "link"),
                    published=_text(item, "pubDate"),
                    tags=categorize_headline(title),
                )
            )
        return items


def categorize_headline(title: str) -> list[str]:
    title_lower = title.lower()
    categories = []
    for category, keywords in TARGET_KEYWORDS.items():
        if any(keyword in title_lower for keyword in keywords):
            categories.append(category)
    return categories


def _rank_for_asset(items: list[NewsItem], asset: str) -> list[NewsItem]:
    keywords = KEYWORDS.get(asset, [])
    scored: list[tuple[int, NewsItem]] = []
    for item in items:
        title = item.title.lower()
        score = sum(1 for keyword in keywords if keyword in title)
        score += len(item.tags)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


def _text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""
