import requests
import logging
from datetime import datetime, timedelta, timezone
from shared.config import config

logger = logging.getLogger(__name__)


def fetch_news(ticker: str, max_articles: int = 5) -> list[dict]:
    """Fetch recent news headlines for a ticker via NewsAPI."""
    if not config.NEWS_API_KEY or config.NEWS_API_KEY == "your_news_api_key_here":
        return _fallback_news(ticker)

    try:
        from_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": ticker,
                "from": from_date,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": max_articles,
                "apiKey": config.NEWS_API_KEY,
            },
            timeout=10
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [
            {
                "title": a["title"],
                "description": a.get("description", ""),
                "published": a.get("publishedAt", ""),
                "source": a.get("source", {}).get("name", ""),
            }
            for a in articles if a.get("title")
        ]
    except Exception as e:
        logger.warning(f"News fetch failed for {ticker}: {e}")
        return _fallback_news(ticker)


def _fallback_news(ticker: str) -> list[dict]:
    """Returns empty list when news API is unavailable. LLM will rely on technicals only."""
    return []


def format_news_for_prompt(articles: list[dict]) -> str:
    if not articles:
        return "No recent news available. Base analysis on technical indicators only."
    lines = []
    for a in articles:
        lines.append(f"- [{a['source']}] {a['title']}")
        if a.get("description"):
            lines.append(f"  {a['description'][:150]}")
    return "\n".join(lines)
