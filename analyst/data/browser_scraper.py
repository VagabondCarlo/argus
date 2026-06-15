"""
Playwright-based browser scraper for JS-rendered financial pages.
Handles sites that block requests-based scraping or require JavaScript.

Targets:
  - Barchart unusual options activity
  - StockTwits social sentiment
  - Reddit r/wallstreetbets/r/investing mentions
  - CoinGecko on-chain sentiment (crypto)
  - Any page the OpenClaw research agent flags

Results cached per ticker per day.
"""

import logging
import asyncio
import re
from datetime import date
from functools import lru_cache

logger = logging.getLogger(__name__)

_CACHE: dict[tuple, dict] = {}


def _cached(key: str) -> dict | None:
    return _CACHE.get((key, date.today().isoformat()))


def _store(key: str, data: dict):
    _CACHE[(key, date.today().isoformat())] = data


async def _fetch_page(url: str, wait_selector: str = "body", timeout: int = 15000) -> str:
    """Launch headless Chromium, load the page, return the text content."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            try:
                await page.wait_for_selector(wait_selector, timeout=8000)
            except Exception:
                pass
            content = await page.inner_text("body")
            await browser.close()
            return content
    except Exception as e:
        logger.debug(f"Browser fetch failed for {url}: {e}")
        return ""


def _run(coro):
    """Run an async function from sync context safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=30)
        return loop.run_until_complete(coro)
    except Exception as e:
        logger.debug(f"Async runner error: {e}")
        return ""


# ── StockTwits sentiment ──────────────────────────────────────────────────────

def get_stocktwits_sentiment(ticker: str) -> dict:
    """
    Fetches StockTwits social sentiment for a stock or crypto ticker.
    Returns bullish/bearish counts and the top 3 recent messages.
    """
    cache_key = f"stocktwits_{ticker}"
    cached = _cached(cache_key)
    if cached:
        return cached

    try:
        import requests
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {"sentiment": "unknown", "summary": "StockTwits data unavailable."}

        data = resp.json()
        messages = data.get("messages", [])

        bullish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
        bearish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")
        total = bullish + bearish

        if total == 0:
            sentiment = "neutral"
        elif bullish / total > 0.65:
            sentiment = "bullish"
        elif bearish / total > 0.65:
            sentiment = "bearish"
        else:
            sentiment = "mixed"

        # Top 3 message snippets
        snippets = []
        for m in messages[:3]:
            body = m.get("body", "").strip()
            if body:
                snippets.append(body[:120])

        summary = (
            f"StockTwits: {bullish} bullish, {bearish} bearish out of {len(messages)} recent posts. "
            f"Sentiment: {sentiment.upper()}."
        )

        result = {
            "sentiment": sentiment,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "total_posts": len(messages),
            "snippets": snippets,
            "summary": summary,
        }
        _store(cache_key, result)
        return result

    except Exception as e:
        logger.debug(f"StockTwits failed for {ticker}: {e}")
        return {"sentiment": "unknown", "summary": "StockTwits data unavailable."}


# ── Barchart unusual options activity ────────────────────────────────────────

def get_unusual_options(ticker: str) -> dict:
    """
    Scrapes Barchart for unusual options activity on a stock.
    Unusual large options bets = institutional positioning signal.
    """
    cache_key = f"options_{ticker}"
    cached = _cached(cache_key)
    if cached:
        return cached

    try:
        url = f"https://www.barchart.com/stocks/quotes/{ticker}/options"
        content = _run(_fetch_page(url, timeout=20000))

        if not content:
            return {"unusual_activity": False, "summary": "Options data unavailable."}

        # Look for volume/OI anomalies in the text
        unusual_patterns = [
            r"unusual", r"sweep", r"block", r"call.*\$\d+[KM]",
            r"put.*\$\d+[KM]", r"vol.*OI.*[2-9]\d{1,2}x",
        ]
        flags = []
        for p in unusual_patterns:
            if re.search(p, content, re.IGNORECASE):
                flags.append(p.split("\\")[0])

        has_unusual = len(flags) > 0
        summary = (
            f"Unusual options activity detected on {ticker} — potential institutional positioning."
            if has_unusual else
            f"No unusual options activity flagged on {ticker}."
        )

        result = {
            "unusual_activity": has_unusual,
            "flags": flags,
            "summary": summary,
        }
        _store(cache_key, result)
        return result

    except Exception as e:
        logger.debug(f"Barchart options failed for {ticker}: {e}")
        return {"unusual_activity": False, "summary": "Options data unavailable."}


# ── CoinGecko crypto sentiment ────────────────────────────────────────────────

_COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "AVAX-USD": "avalanche-2",
    "DOGE-USD": "dogecoin",
    "LINK-USD": "chainlink",
}

def get_crypto_sentiment(ticker: str) -> dict:
    """
    Fetches CoinGecko market data including sentiment votes, developer activity,
    and community data that goes beyond price.
    """
    cache_key = f"coingecko_{ticker}"
    cached = _cached(cache_key)
    if cached:
        return cached

    coin_id = _COINGECKO_IDS.get(ticker)
    if not coin_id:
        return {"summary": f"No CoinGecko mapping for {ticker}."}

    try:
        import requests
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&market_data=true&community_data=true&developer_data=false"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return {"summary": "CoinGecko data unavailable."}

        data = resp.json()
        sentiment_up   = data.get("sentiment_votes_up_percentage", 0)
        sentiment_down = data.get("sentiment_votes_down_percentage", 0)
        market_data    = data.get("market_data", {})
        dominance_note = ""

        change_24h = market_data.get("price_change_percentage_24h", 0)
        change_7d  = market_data.get("price_change_percentage_7d", 0)
        change_30d = market_data.get("price_change_percentage_30d", 0)

        reddit_subs = data.get("community_data", {}).get("reddit_subscribers", 0)

        overall = "bullish" if sentiment_up > 60 else ("bearish" if sentiment_down > 60 else "mixed")

        summary = (
            f"CoinGecko sentiment: {sentiment_up:.0f}% bullish / {sentiment_down:.0f}% bearish. "
            f"Price change: 24h {change_24h:+.1f}%, 7d {change_7d:+.1f}%, 30d {change_30d:+.1f}%. "
            f"Reddit community: {reddit_subs:,} subscribers. Overall bias: {overall.upper()}."
        )

        result = {
            "sentiment": overall,
            "sentiment_up_pct": sentiment_up,
            "sentiment_down_pct": sentiment_down,
            "change_24h": change_24h,
            "change_7d": change_7d,
            "change_30d": change_30d,
            "summary": summary,
        }
        _store(cache_key, result)
        return result

    except Exception as e:
        logger.debug(f"CoinGecko failed for {ticker}: {e}")
        return {"summary": "CoinGecko data unavailable."}


# ── On-demand browser fetch (for OpenClaw integration) ───────────────────────

def browse_url(url: str, question: str = "") -> str:
    """
    Browse any URL with headless Chromium and return the page text.
    Used when OpenClaw or the Telegram bot requests a live page lookup.
    """
    content = _run(_fetch_page(url, timeout=20000))
    if not content:
        return "Could not load the page."

    # Trim to a reasonable size for the LLM
    content = content.strip()
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content[:4000]


# ── Master function ───────────────────────────────────────────────────────────

def get_browser_enrichment(ticker: str, asset_type: str = "stock") -> dict:
    """
    Pulls browser-based enrichment for a ticker.
    Returns a dict with a pre-formatted LLM context string.
    """
    cached = _cached(f"browser_{ticker}")
    if cached:
        return cached

    lines = []

    if asset_type == "stock":
        # StockTwits sentiment
        st = get_stocktwits_sentiment(ticker)
        if st.get("summary"):
            lines.append(st["summary"])

        # Unusual options
        opts = get_unusual_options(ticker)
        if opts.get("summary"):
            lines.append(opts["summary"])

    elif asset_type == "crypto":
        cg = get_crypto_sentiment(ticker)
        if cg.get("summary"):
            lines.append(cg["summary"])

        # StockTwits for crypto too (BTC, ETH are on there)
        st = get_stocktwits_sentiment(ticker.replace("-USD", "").replace("-", ""))
        if st.get("summary") and st.get("sentiment") != "unknown":
            lines.append(st["summary"])

    result = {
        "llm_context": "\n".join(lines) if lines else "No browser enrichment available.",
        "raw": {
            "stocktwits": locals().get("st"),
            "options": locals().get("opts"),
            "coingecko": locals().get("cg"),
        }
    }
    _store(f"browser_{ticker}", result)
    return result
