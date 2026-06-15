"""
Reddit social sentiment scraper.
Pulls trending ticker mentions from key trading subreddits and scores them
for sentiment and community conviction. No auth required — uses the public
Reddit JSON API.

Subreddits tracked:
  r/wallstreetbets   — high-energy momentum plays, short squeezes
  r/stocks           — broader retail discussion
  r/investing        — more measured, longer-term
  r/options          — options flow and strategy talk
  r/pennystocks      — speculative small caps

Results cached per day to avoid rate limits.
"""

import re
import time
import logging
import requests
from datetime import date
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────

_CACHE: dict[tuple, dict] = {}

def _cached(key: str) -> dict | None:
    return _CACHE.get((key, date.today().isoformat()))

def _store(key: str, data: dict):
    _CACHE[(key, date.today().isoformat())] = data


# ── Ticker extraction ─────────────────────────────────────────────────────────

# Common words that look like tickers but aren't
_STOPWORDS = {
    "A", "I", "AM", "AT", "BE", "BY", "DO", "GO", "IN", "IS", "IT",
    "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE",
    "ALL", "AND", "ARE", "BUT", "CAN", "CEO", "DID", "END", "FOR",
    "GET", "GOT", "HAS", "HAD", "HIM", "HIS", "HOW", "ITS", "LET",
    "LOL", "LOW", "MAN", "NEW", "NOT", "NOW", "OFF", "OLD", "ONE",
    "OUR", "OUT", "OWN", "PUT", "RUN", "SAY", "SEE", "SET", "SHE",
    "THE", "TOO", "TOP", "TRY", "TWO", "USE", "WAY", "WHO", "WHY",
    "WIN", "YES", "YET", "YOU", "ANY", "APE", "BIG", "DAY", "DUE",
    "EPS", "ETF", "FED", "FYI", "GDP", "GME", "HIGH", "IMO", "IPO",
    "IRA", "IRS", "ITM", "JUST", "KEEP", "LONG", "LOSS", "MAKE",
    "MANY", "MUCH", "NEED", "NEXT", "ONLY", "OPEN", "OVER", "PAST",
    "PLAY", "PLUS", "RATE", "REAL", "RISK", "SAME", "SELL", "SIDE",
    "SOME", "SOON", "STAY", "STOP", "SUCH", "TAKE", "THAN", "THAT",
    "THEM", "THEN", "THEY", "THIS", "TIME", "VERY", "WANT", "WELL",
    "WERE", "WHAT", "WHEN", "WITH", "WORD", "WORK", "YEAR", "YOUR",
    "ALSO", "BACK", "BEEN", "BOTH", "CALL", "CASH", "COST", "DAYS",
    "DEAL", "DOWN", "EACH", "EARN", "EASY", "EVEN", "EVER", "FEEL",
    "FULL", "FUND", "GIVE", "GOES", "GOOD", "HAVE", "HELP", "HERE",
    "HOME", "INTO", "KNOW", "LAST", "LIFE", "LIKE", "LINE", "LINK",
    "LIVE", "LOOK", "LOVE", "MADE", "MEAN", "MEET", "MIND", "MINE",
    "MISS", "MOVE", "MUCH", "MUST", "NICE", "NONE", "PART", "PASS",
    "PLAN", "POST", "PRICE", "PUTS", "SAID", "SAYS", "SEEN", "SENT",
    "SHIT", "SHOW", "SURE", "TELL", "TOLD", "TOOK", "TURN", "USED",
    "WAIT", "WALK", "WEEK", "WENT", "WILL", "WISH", "BULL", "BEAR",
    "BOOM", "BUY", "SELL", "HOLD", "YOLO", "MOON", "DUMP", "PUMP",
    "GAIN", "PAIN", "LOSS", "FOMO", "DYOR", "HODL", "REKT", "CHAD",
    "APES", "WSBT", "MODS", "EDIT", "TLDR", "INFO", "DATA", "NEWS",
    "WEEK", "MONTH", "YEAR", "TODAY", "STOCK", "SHARE", "TRADE",
    "MARKET", "OPTION", "CALLS", "SHORTS", "PUTS", "THETA", "DELTA",
    "ALPHA", "BETA", "GAMMA", "VEGA", "IV", "OTM", "ATM", "ITM",
    "EPS", "PE", "PEG", "ROE", "ROI", "EBITDA", "GAAP",
}

# Match $TICKER or standalone 1-5 uppercase letters
_DOLLAR_RE  = re.compile(r'\$([A-Z]{1,5})\b')
_CAPS_RE    = re.compile(r'\b([A-Z]{2,5})\b')


def _extract_tickers(text: str) -> list[str]:
    """Pull all probable ticker symbols from a block of text."""
    found = set()
    # $TICKER format — high confidence
    for m in _DOLLAR_RE.finditer(text):
        t = m.group(1)
        if t not in _STOPWORDS:
            found.add(t)
    # ALL-CAPS words — lower confidence, filter stopwords
    for m in _CAPS_RE.finditer(text):
        t = m.group(1)
        if t not in _STOPWORDS and len(t) >= 2:
            found.add(t)
    return list(found)


# ── Sentiment scoring ─────────────────────────────────────────────────────────

_BULLISH_WORDS = [
    "moon", "mooning", "rocket", "bull", "bullish", "calls", "buy", "buying",
    "long", "breakout", "squeeze", "short squeeze", "undervalued", "cheap",
    "strong", "beat", "earnings beat", "upgrade", "all time high", "ath",
    "green", "gains", "tendies", "yolo", "to the moon", "hodl", "accumulate",
    "catalyst", "explosive", "huge", "massive", "surge", "rally", "pop",
]

_BEARISH_WORDS = [
    "puts", "short", "shorting", "bear", "bearish", "sell", "dump", "dumping",
    "overvalued", "bubble", "crash", "correction", "tank", "tanking", "red",
    "loss", "rekt", "down", "downside", "miss", "earnings miss", "downgrade",
    "avoid", "stay away", "bad", "terrible", "terrible", "disaster",
]


def _sentiment_score(text: str) -> float:
    """
    Returns a score from -1.0 (very bearish) to +1.0 (very bullish).
    """
    lower = text.lower()
    bull = sum(1 for w in _BULLISH_WORDS if w in lower)
    bear = sum(1 for w in _BEARISH_WORDS if w in lower)
    total = bull + bear
    if total == 0:
        return 0.0
    return (bull - bear) / total


# ── Reddit fetch ──────────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Argus/1.0 autonomous trading research (educational use)"}

SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "options",
    "pennystocks",
    "StockMarket",
]

# Weight each subreddit — WSB gets highest weight since it most directly moves prices
_SUB_WEIGHT = {
    "wallstreetbets": 2.0,
    "options":        1.5,
    "stocks":         1.2,
    "StockMarket":    1.2,
    "investing":      1.0,
    "pennystocks":    0.8,
}


def _fetch_subreddit(subreddit: str, sort: str = "hot", limit: int = 50) -> list[dict]:
    """Fetch posts from a subreddit using the public JSON API."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 429:
            logger.debug(f"Reddit rate limit on r/{subreddit} — skipping")
            return []
        if resp.status_code != 200:
            logger.debug(f"Reddit r/{subreddit} returned {resp.status_code}")
            return []
        data = resp.json()
        return data.get("data", {}).get("children", [])
    except Exception as e:
        logger.debug(f"Reddit fetch failed for r/{subreddit}: {e}")
        return []


def get_wsb_hot_tickers(min_mentions: int = 2) -> list[dict]:
    """
    Scan trending subreddits and return ranked tickers with mention counts,
    sentiment, and conviction score.

    Returns list of dicts sorted by conviction score (highest first):
      ticker, mentions, sentiment, conviction, subreddits, sample_titles
    """
    cached = _cached("wsb_hot")
    if cached:
        return cached

    # ticker -> accumulated data
    ticker_data: dict[str, dict] = defaultdict(lambda: {
        "mentions": 0,
        "weighted_mentions": 0.0,
        "sentiment_sum": 0.0,
        "sentiment_count": 0,
        "upvotes": 0,
        "subreddits": set(),
        "sample_titles": [],
    })

    for sub in SUBREDDITS:
        posts = _fetch_subreddit(sub, sort="hot", limit=50)
        weight = _SUB_WEIGHT.get(sub, 1.0)

        for post in posts:
            p = post.get("data", {})
            title    = p.get("title", "")
            selftext = p.get("selftext", "")
            score    = p.get("score", 0)        # upvotes
            comments = p.get("num_comments", 0)

            full_text = f"{title} {selftext}"
            tickers = _extract_tickers(full_text)
            if not tickers:
                continue

            sent = _sentiment_score(full_text)
            # Conviction boost from engagement
            engagement_boost = min(1.0 + (score / 5000) + (comments / 500), 3.0)

            for ticker in tickers:
                d = ticker_data[ticker]
                d["mentions"] += 1
                d["weighted_mentions"] += weight * engagement_boost
                d["sentiment_sum"] += sent
                d["sentiment_count"] += 1
                d["upvotes"] += score
                d["subreddits"].add(sub)
                if len(d["sample_titles"]) < 3 and title not in d["sample_titles"]:
                    d["sample_titles"].append(title[:100])

        # Polite delay between subreddits
        time.sleep(1.2)

    # Build results
    results = []
    for ticker, d in ticker_data.items():
        if d["mentions"] < min_mentions:
            continue
        avg_sentiment = d["sentiment_sum"] / d["sentiment_count"] if d["sentiment_count"] else 0
        results.append({
            "ticker":           ticker,
            "mentions":         d["mentions"],
            "weighted_score":   round(d["weighted_mentions"], 2),
            "sentiment":        round(avg_sentiment, 3),
            "sentiment_label":  "bullish" if avg_sentiment > 0.1 else ("bearish" if avg_sentiment < -0.1 else "neutral"),
            "upvotes":          d["upvotes"],
            "subreddits":       sorted(d["subreddits"]),
            "sample_titles":    d["sample_titles"],
        })

    # Sort by weighted score descending
    results.sort(key=lambda x: x["weighted_score"], reverse=True)
    _store("wsb_hot", results)
    return results


def get_ticker_social_context(ticker: str) -> dict:
    """
    Get social context for a specific ticker — mention count, sentiment,
    and sample post titles from Reddit. Used to enrich LLM analysis.
    """
    cached = _cached(f"social_{ticker}")
    if cached:
        return cached

    hot = get_wsb_hot_tickers(min_mentions=1)
    match = next((t for t in hot if t["ticker"] == ticker), None)

    if not match:
        result = {
            "found": False,
            "summary": f"No significant Reddit mentions found for {ticker} today.",
            "llm_context": "",
        }
    else:
        subs = ", ".join(f"r/{s}" for s in match["subreddits"])
        result = {
            "found": True,
            "mentions": match["mentions"],
            "sentiment": match["sentiment_label"],
            "weighted_score": match["weighted_score"],
            "subreddits": match["subreddits"],
            "sample_titles": match["sample_titles"],
            "summary": (
                f"Reddit social signal: {match['mentions']} mentions across {subs}. "
                f"Community sentiment: {match['sentiment_label'].upper()}. "
                f"Conviction score: {match['weighted_score']:.1f} (weighted by engagement + upvotes)."
            ),
            "llm_context": (
                f"REDDIT SOCIAL SIGNAL — {ticker}: "
                f"{match['mentions']} mentions across {subs}. "
                f"Sentiment: {match['sentiment_label'].upper()}. "
                f"Conviction score: {match['weighted_score']:.1f}.\n"
                + (
                    "Sample posts: " + " | ".join(match["sample_titles"])
                    if match["sample_titles"] else ""
                )
            ),
        }

    _store(f"social_{ticker}", result)
    return result


def format_wsb_report(top_n: int = 10) -> str:
    """
    Format a readable report of the top social tickers for the Telegram /wsb command.
    """
    tickers = get_wsb_hot_tickers()
    if not tickers:
        return "No Reddit data available right now. Try again shortly."

    lines = ["<b>🔥 Reddit Social Pulse — Top Mentions Today</b>\n"]
    for i, t in enumerate(tickers[:top_n], 1):
        sent_emoji = "🟢" if t["sentiment_label"] == "bullish" else ("🔴" if t["sentiment_label"] == "bearish" else "⚪")
        subs = ", ".join(f"r/{s}" for s in t["subreddits"][:2])
        lines.append(
            f"{i}. <b>${t['ticker']}</b> {sent_emoji} — {t['mentions']} mentions | "
            f"score {t['weighted_score']:.0f} | {subs}"
        )

    lines.append(
        "\n<i>Ranked by weighted engagement score. Cross-reference with Argus signals "
        "before acting. Social momentum is one input — not financial advice. DYOR.</i>"
    )
    return "\n".join(lines)
