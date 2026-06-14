"""
Web scraper layer — pulls data unavailable via standard APIs.

Sources:
  yfinance extended:  earnings calendar, insider transactions, analyst recommendations
  Finviz HTML:        analyst ratings detail, short interest, price targets, news enrichment

Results are cached per ticker per day so we don't hammer any site
during a full market scan.
"""

import logging
import time
import random
import requests
import yfinance as yf
from datetime import date, datetime, timedelta
from functools import lru_cache
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)

# Simple in-process daily cache — key: (ticker, date)
_CACHE: dict[tuple, dict] = {}


def _cached(ticker: str) -> dict | None:
    return _CACHE.get((ticker, date.today().isoformat()))


def _store(ticker: str, data: dict):
    _CACHE[(ticker, date.today().isoformat())] = data


# ── Earnings proximity ────────────────────────────────────────────────────────

def get_earnings_proximity(ticker: str) -> dict:
    """
    Returns days until next earnings and whether to flag it as a risk.
    If earnings are within 7 days, confidence should be capped — earnings
    create binary volatility that technicals cannot predict.
    """
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None or cal.empty:
            return {"days_to_earnings": None, "earnings_risk": False, "earnings_date": None}

        # calendar index contains 'Earnings Date' etc.
        if "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"]
            # May be a Series with multiple dates
            if hasattr(raw, "__iter__") and not isinstance(raw, str):
                dates = [d for d in raw if d is not None]
                next_date = min(dates) if dates else None
            else:
                next_date = raw
        else:
            next_date = None

        if next_date is None:
            return {"days_to_earnings": None, "earnings_risk": False, "earnings_date": None}

        if hasattr(next_date, "date"):
            next_date = next_date.date()
        elif isinstance(next_date, str):
            next_date = datetime.strptime(next_date[:10], "%Y-%m-%d").date()

        days = (next_date - date.today()).days
        return {
            "days_to_earnings": days,
            "earnings_risk": 0 <= days <= 7,
            "earnings_date": str(next_date),
        }
    except Exception as e:
        logger.debug(f"Earnings proximity failed for {ticker}: {e}")
        return {"days_to_earnings": None, "earnings_risk": False, "earnings_date": None}


# ── Insider activity (yfinance) ───────────────────────────────────────────────

def get_insider_activity(ticker: str) -> dict:
    """
    Returns recent insider buying vs selling in the past 90 days.
    Net buying is a strong fundamental signal — insiders know their company best.
    """
    try:
        t = yf.Ticker(ticker)
        txns = t.insider_transactions
        if txns is None or txns.empty:
            return {"insider_buys": 0, "insider_sells": 0, "net_insider_bias": "neutral", "summary": "No insider data available."}

        # Filter to last 90 days
        cutoff = date.today() - timedelta(days=90)
        txns = txns.copy()
        txns["Date"] = txns["Start Date"] if "Start Date" in txns.columns else txns.index
        txns["Date"] = txns["Date"].apply(
            lambda x: x.date() if hasattr(x, "date") else date.today()
        )
        recent = txns[txns["Date"] >= cutoff]

        if recent.empty:
            return {"insider_buys": 0, "insider_sells": 0, "net_insider_bias": "neutral", "summary": "No recent insider transactions."}

        text_col = next((c for c in recent.columns if "text" in c.lower() or "transaction" in c.lower()), None)

        buys = 0
        sells = 0
        if text_col:
            buys = recent[text_col].str.contains("Purchase|Buy|Acquisition", case=False, na=False).sum()
            sells = recent[text_col].str.contains("Sale|Sell|Disposition", case=False, na=False).sum()
        else:
            buys = len(recent)

        bias = "bullish" if buys > sells * 1.5 else ("bearish" if sells > buys * 1.5 else "neutral")

        summary = (
            f"{buys} insider purchase(s), {sells} insider sale(s) in last 90 days. "
            f"Net bias: {bias}."
        )

        return {
            "insider_buys": int(buys),
            "insider_sells": int(sells),
            "net_insider_bias": bias,
            "summary": summary,
        }
    except Exception as e:
        logger.debug(f"Insider activity failed for {ticker}: {e}")
        return {"insider_buys": 0, "insider_sells": 0, "net_insider_bias": "neutral", "summary": "Insider data unavailable."}


# ── Analyst consensus (yfinance) ──────────────────────────────────────────────

def get_analyst_consensus(ticker: str) -> dict:
    """
    Returns analyst buy/hold/sell distribution and average price target.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        target = info.get("targetMeanPrice") or info.get("targetPrice")
        rec = info.get("recommendationKey", "").lower()
        num_analysts = info.get("numberOfAnalystOpinions", 0)

        rec_label = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "underperform": "Underperform",
            "sell": "Sell",
        }.get(rec, rec.replace("_", " ").title() if rec else "N/A")

        summary = (
            f"{num_analysts} analyst(s) covering this. "
            f"Consensus: {rec_label}. "
            f"Avg price target: ${target:.2f}." if target else f"Consensus: {rec_label}."
        )

        return {
            "analyst_consensus": rec_label,
            "analyst_target": target,
            "analyst_count": num_analysts,
            "summary": summary,
        }
    except Exception as e:
        logger.debug(f"Analyst consensus failed for {ticker}: {e}")
        return {"analyst_consensus": "N/A", "analyst_target": None, "analyst_count": 0, "summary": "Analyst data unavailable."}


# ── Finviz scraper ────────────────────────────────────────────────────────────

def _fetch_finviz(ticker: str) -> BeautifulSoup | None:
    """Fetch and parse Finviz quote page with polite rate limiting."""
    try:
        time.sleep(random.uniform(1.5, 3.0))  # polite delay
        url = f"https://finviz.com/quote.ashx?t={ticker}&ty=c&ta=1&p=d"
        resp = _SESSION.get(url, timeout=10)
        if resp.status_code != 200:
            logger.debug(f"Finviz returned {resp.status_code} for {ticker}")
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.debug(f"Finviz fetch failed for {ticker}: {e}")
        return None


def _parse_finviz_table(soup: BeautifulSoup) -> dict:
    """Extract the key metrics table from Finviz."""
    data = {}
    try:
        rows = soup.select("table.snapshot-table2 tr")
        for row in rows:
            cells = row.find_all("td")
            for i in range(0, len(cells) - 1, 2):
                key = cells[i].get_text(strip=True)
                val = cells[i + 1].get_text(strip=True)
                data[key] = val
    except Exception:
        pass
    return data


def get_finviz_enrichment(ticker: str) -> dict:
    """
    Scrapes Finviz for short interest, detailed analyst target, and earnings date.
    Falls back gracefully on any failure.
    """
    soup = _fetch_finviz(ticker)
    if not soup:
        return {}

    table = _parse_finviz_table(soup)

    short_float = table.get("Short Float", table.get("Short Float ", "N/A"))
    short_ratio = table.get("Short Ratio", "N/A")
    target_price = table.get("Target Price", "N/A")
    earnings = table.get("Earnings", "N/A")
    recom = table.get("Recom", "N/A")

    # Recent news headlines from Finviz (different from RSS feeds)
    headlines = []
    try:
        news_rows = soup.select("table#news-table tr")
        for row in news_rows[:5]:
            link = row.find("a")
            if link:
                headlines.append(link.get_text(strip=True))
    except Exception:
        pass

    return {
        "short_float": short_float,
        "short_ratio": short_ratio,
        "finviz_target": target_price,
        "earnings_date_label": earnings,
        "analyst_recom_score": recom,
        "finviz_headlines": headlines,
    }


# ── Master enrichment function ────────────────────────────────────────────────

def get_full_enrichment(ticker: str, use_finviz: bool = True) -> dict:
    """
    Pulls all enrichment data for a ticker from all sources.
    Results cached for the day — safe to call multiple times per scan.

    Returns a dict with all enrichment fields + a pre-formatted LLM context string.
    """
    cached = _cached(ticker)
    if cached:
        return cached

    earnings  = get_earnings_proximity(ticker)
    insider   = get_insider_activity(ticker)
    analyst   = get_analyst_consensus(ticker)
    finviz    = get_finviz_enrichment(ticker) if use_finviz else {}

    result = {
        **earnings,
        **insider,
        **analyst,
        **finviz,
    }

    result["llm_context"] = _format_for_llm(ticker, result)
    _store(ticker, result)
    return result


def _format_for_llm(ticker: str, data: dict) -> str:
    """Formats enrichment data as a clean block for the LLM signal prompt."""
    lines = []

    # Earnings warning
    days = data.get("days_to_earnings")
    if days is not None:
        if data.get("earnings_risk"):
            lines.append(
                f"⚠️ EARNINGS RISK: {ticker} reports in {days} day(s) ({data.get('earnings_date', '?')}). "
                "Binary event — technicals cannot predict direction. Cap confidence accordingly."
            )
        elif 0 < days <= 21:
            lines.append(f"Earnings in {days} days ({data.get('earnings_date', '?')}) — factor in pre-earnings drift.")

    # Analyst consensus
    lines.append(data.get("summary", "") or "No analyst data.")

    # Insider activity
    insider_summary = data.get("summary", "")
    if insider_summary and "insider" in insider_summary.lower():
        lines.append(insider_summary)
    bias = data.get("net_insider_bias", "neutral")
    if bias == "bullish":
        lines.append("Insider signal: NET BUYING in last 90 days — insiders are accumulating.")
    elif bias == "bearish":
        lines.append("Insider signal: NET SELLING in last 90 days — insiders are reducing positions.")

    # Short interest
    short_float = data.get("short_float")
    short_ratio = data.get("short_ratio")
    if short_float and short_float != "N/A":
        lines.append(f"Short interest: {short_float} of float shorted, {short_ratio} days to cover.")

    # Finviz headlines (extra news beyond RSS)
    headlines = data.get("finviz_headlines", [])
    if headlines:
        lines.append("Recent headlines from Finviz:")
        for h in headlines[:3]:
            lines.append(f"  - {h}")

    return "\n".join(lines) if lines else "No enrichment data available."
