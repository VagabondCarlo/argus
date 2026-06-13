import re
import html
import requests
import xml.etree.ElementTree as ET
import yfinance as yf

RSS_FEEDS = [
    ("Yahoo Finance",  "https://finance.yahoo.com/news/rssindex"),
    ("CNBC Markets",   "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069"),
    ("MarketWatch",    "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
]


def _strip_html(text: str) -> str:
    text = html.unescape(text or "")
    return re.sub(r"<[^>]+>", "", text).strip()


def _two_sentences(text: str) -> str:
    text = _strip_html(text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:2])[:280]


def get_market_news(max_articles: int = 3) -> list[dict]:
    articles = []

    for source_name, url in RSS_FEEDS:
        if len(articles) >= max_articles:
            break
        try:
            resp = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            channel = root.find("channel") or root
            for item in channel.findall("item"):
                title = _strip_html(item.findtext("title", ""))
                link = (item.findtext("link") or "").strip()
                desc = _two_sentences(item.findtext("description", ""))
                if not title or not link:
                    continue
                articles.append({
                    "title": title,
                    "summary": desc or "Click to read the full story.",
                    "publisher": source_name,
                    "url": link,
                })
                if len(articles) >= max_articles:
                    break
        except Exception:
            continue

    # Fallback: yfinance SPY news (no API key needed)
    if not articles:
        try:
            for item in (yf.Ticker("SPY").news or [])[:max_articles]:
                articles.append({
                    "title": item.get("title", ""),
                    "summary": f"Published by {item.get('publisher', 'Unknown')}. Click to read the full story.",
                    "publisher": item.get("publisher", "Unknown"),
                    "url": item.get("link", ""),
                })
        except Exception:
            pass

    return articles[:max_articles]


def format_news_report(articles: list[dict]) -> str:
    if not articles:
        return "📰 <b>Market News</b>\n\nNo market news available right now. Try again shortly."

    lines = ["📰 <b>Market Pulse — Top 3 Headlines</b>\n"]
    for i, a in enumerate(articles, 1):
        title = a["title"].replace("<", "&lt;").replace(">", "&gt;")
        summary = a["summary"].replace("<", "&lt;").replace(">", "&gt;")
        lines.append(
            f"<b>{i}. {title}</b>\n"
            f"{summary}\n"
            f'<a href="{a["url"]}">Read more → {a["publisher"]}</a>\n'
        )

    lines.append("<i>Real-time headlines. Not financial advice.</i>")
    return "\n".join(lines)
