"""
Unified social media intelligence aggregator.
Pulls ticker mentions and sentiment from every major social platform
where retail traders talk — then cross-references with professional data.

Platforms:
  Twitter/X    — finance Twitter is the fastest-moving signal (requires Bearer token)
  Reddit       — r/wallstreetbets, r/stocks, r/options, r/investing, r/pennystocks
  Bluesky      — free public AT Protocol API, no auth needed
  Truth Social — Mastodon-compatible API, public posts, no auth needed

Platform conviction weights (how much each platform moves real money):
  Twitter/X  3.0  — finance Twitter directly precedes major moves
  Reddit WSB 2.0  — WSB proved it can move markets (GME, AMC, etc.)
  Reddit Gen 1.2  — r/stocks, r/investing = broader retail consensus
  Bluesky    0.8  — growing finance community, early adopters
  Truth      0.5  — smaller pool but notable for energy/defense sectors

All sources feed a unified conviction score per ticker.
Results cached per day to stay within rate limits.
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


# ── Shared utilities ──────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Argus/1.0 autonomous trading research (educational use)"}

_STOPWORDS = {
    "A", "I", "AM", "AT", "BE", "BY", "DO", "GO", "IN", "IS", "IT",
    "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE",
    "ALL", "AND", "ARE", "BUT", "CAN", "CEO", "DID", "END", "FOR",
    "GET", "GOT", "HAS", "HAD", "HIM", "HIS", "HOW", "ITS", "LET",
    "LOL", "LOW", "MAN", "NEW", "NOT", "NOW", "OFF", "OLD", "ONE",
    "OUR", "OUT", "OWN", "PUT", "RUN", "SAY", "SEE", "SET", "SHE",
    "THE", "TOO", "TOP", "TRY", "TWO", "USE", "WAY", "WHO", "WHY",
    "WIN", "YES", "YET", "YOU", "ANY", "APE", "BIG", "DAY", "DUE",
    "EPS", "ETF", "FED", "FYI", "GDP", "HIGH", "IMO", "IPO",
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
    "MISS", "MOVE", "MUST", "NICE", "NONE", "PART", "PASS",
    "PLAN", "POST", "SAID", "SAYS", "SEEN", "SENT",
    "SHOW", "SURE", "TELL", "TOLD", "TOOK", "TURN", "USED",
    "WAIT", "WALK", "WEEK", "WENT", "WILL", "WISH", "BULL", "BEAR",
    "BOOM", "BUY", "YOLO", "MOON", "DUMP", "PUMP",
    "GAIN", "PAIN", "FOMO", "DYOR", "HODL", "REKT", "CHAD",
    "APES", "MODS", "EDIT", "TLDR", "INFO", "DATA", "NEWS",
    "STOCK", "SHARE", "TRADE", "MARKET", "OPTION", "CALLS",
    "SHORTS", "PUTS", "THETA", "DELTA", "ALPHA", "BETA", "GAMMA",
    "VEGA", "IV", "OTM", "ATM", "EPS", "PE", "PEG", "ROE", "ROI",
    "EBITDA", "GAAP", "BREAKING", "UPDATE", "WATCH", "PRICE",
    "TODAY", "AFTER", "BEFORE", "ABOUT", "THINK", "COULD", "WOULD",
    "SHOULD", "EVERY", "THESE", "THOSE", "OTHER", "WHILE", "STILL",
    "NEVER", "ALWAYS", "SINCE", "THEIR", "WHERE", "WHICH", "THERE",
    "MIGHT", "BEING", "DOING", "GOING", "COME", "FROM", "GIVE",
    "JUST", "KNOW", "LIKE", "LOOK", "MAKE", "MOST", "MOVE", "MUCH",
    "NEXT", "ONLY", "OPEN", "OVER", "SAME", "SEEM", "SHOW", "TAKE",
    "THEN", "THEY", "TIME", "TURN", "UPON", "USED", "VERY", "WELL",
    "WERE", "WHAT", "WHEN", "WITH", "YEAR", "YOUR",
}

_DOLLAR_RE = re.compile(r'\$([A-Z]{1,5})\b')
_CAPS_RE   = re.compile(r'\b([A-Z]{2,5})\b')

_BULLISH = [
    "moon", "mooning", "rocket", "bull", "bullish", "calls", "buy", "buying",
    "long", "breakout", "squeeze", "short squeeze", "undervalued", "cheap",
    "strong", "beat", "earnings beat", "upgrade", "all time high", "ath",
    "green", "gains", "tendies", "yolo", "to the moon", "hodl", "accumulate",
    "catalyst", "explosive", "huge", "massive", "surge", "rally", "pop",
    "printing", "load", "loaded", "bags", "flying", "ripping", "send it",
    "conviction", "oversold", "support", "bouncing", "recovered",
]

_BEARISH = [
    "puts", "short", "shorting", "bear", "bearish", "sell", "dump", "dumping",
    "overvalued", "bubble", "crash", "correction", "tank", "tanking", "red",
    "loss", "rekt", "down", "downside", "miss", "earnings miss", "downgrade",
    "avoid", "stay away", "bad", "terrible", "disaster", "overbought",
    "resistance", "topped", "falling", "bleeding", "dead", "bagholding",
]


def _extract_tickers(text: str) -> list[str]:
    found = set()
    for m in _DOLLAR_RE.finditer(text):
        t = m.group(1)
        if t not in _STOPWORDS:
            found.add(t)
    for m in _CAPS_RE.finditer(text):
        t = m.group(1)
        if t not in _STOPWORDS and len(t) >= 2:
            found.add(t)
    return list(found)


def _sentiment_score(text: str) -> float:
    lower = text.lower()
    bull = sum(1 for w in _BULLISH if w in lower)
    bear = sum(1 for w in _BEARISH if w in lower)
    total = bull + bear
    if total == 0:
        return 0.0
    return (bull - bear) / total


def _engagement_boost(likes: int = 0, reposts: int = 0, comments: int = 0) -> float:
    """Scale 1.0–3.0 based on engagement — high engagement = community conviction."""
    return min(1.0 + (likes / 5000) + (reposts / 1000) + (comments / 500), 3.0)


# ── Twitter / X ───────────────────────────────────────────────────────────────

def fetch_twitter(query: str, bearer_token: str, max_results: int = 100) -> list[dict]:
    """
    Pull recent tweets via Twitter API v2.
    Requires a free developer account Bearer token — sign up at developer.twitter.com.
    Free tier: 500k tweet reads/month, 1 search app.
    """
    if not bearer_token:
        return []
    try:
        resp = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {bearer_token}"},
            params={
                "query": f"{query} -is:retweet lang:en",
                "max_results": min(max_results, 100),
                "tweet.fields": "public_metrics,created_at,text",
            },
            timeout=12,
        )
        if resp.status_code == 429:
            logger.debug("Twitter API rate limit hit")
            return []
        if resp.status_code != 200:
            logger.debug(f"Twitter API returned {resp.status_code}")
            return []
        return resp.json().get("data", [])
    except Exception as e:
        logger.debug(f"Twitter fetch failed: {e}")
        return []


def scan_twitter_tickers(bearer_token: str) -> dict[str, dict]:
    """Scan cashtag trends on finance Twitter. Returns ticker → aggregate data."""
    if not bearer_token:
        return {}

    ticker_data: dict[str, dict] = defaultdict(lambda: {
        "mentions": 0, "weighted": 0.0,
        "sentiment_sum": 0.0, "sentiment_count": 0,
        "platform": "twitter",
    })

    # US finance Twitter + global market queries
    queries = [
        # US market pulse
        "$stock OR $calls OR $puts -is:retweet lang:en",
        # London / FTSE
        "FTSE OR \"London Stock Exchange\" OR LSE stocks -is:retweet lang:en",
        # Hong Kong / Asia
        "HangSeng OR \"HK stocks\" OR \"Hong Kong market\" -is:retweet lang:en",
        # Global macro that moves US markets
        "Nikkei OR \"Shanghai Composite\" OR \"Asian markets\" -is:retweet lang:en",
    ]
    weight = 3.0

    for q in queries:
        tweets = fetch_twitter(q, bearer_token, max_results=100)
        for tw in tweets:
            text    = tw.get("text", "")
            metrics = tw.get("public_metrics", {})
            likes   = metrics.get("like_count", 0)
            rts     = metrics.get("retweet_count", 0)
            replies = metrics.get("reply_count", 0)

            tickers = _extract_tickers(text)
            sent    = _sentiment_score(text)
            boost   = _engagement_boost(likes, rts, replies)

            for ticker in tickers:
                d = ticker_data[ticker]
                d["mentions"] += 1
                d["weighted"] += weight * boost
                d["sentiment_sum"] += sent
                d["sentiment_count"] += 1

        time.sleep(1.0)

    return dict(ticker_data)


# ── Reddit ────────────────────────────────────────────────────────────────────

_SUBREDDITS = [
    # US — primary signals
    ("wallstreetbets",        2.0),
    ("options",               1.5),
    ("stocks",                1.2),
    ("StockMarket",           1.2),
    ("investing",             1.0),
    ("pennystocks",           0.8),
    ("RobinHoodPennyStocks",  0.7),
    ("Daytrading",            1.3),
    ("thetagang",             1.0),
    ("SecurityAnalysis",      0.9),
    ("ValueInvesting",        0.9),
    ("algotrading",           1.1),
    # UK / Europe — London market intel
    ("UKInvesting",           1.2),
    ("UKPersonalFinance",     0.8),
    ("FIREUK",                0.7),
    ("EuropeanFIRE",          0.7),
    ("eupersonalfinance",     0.7),
    # Asia Pacific — HK, AUS, India overnight signals
    ("ASX_Bets",              1.3),   # Australia's WSB — moves fast
    ("AusFinance",            0.9),
    ("IndiaInvestments",      0.9),
    ("DalalStreetTalks",      0.8),   # Indian retail traders
    ("HKStocks",              1.1),   # Hong Kong stocks
    ("singapore",             0.7),
    # Crypto crossover (crypto sentiment bleeds into risk-on stocks)
    ("CryptoCurrency",        0.8),
    ("Bitcoin",               0.7),
    ("ethfinance",            0.6),
]


def scan_reddit_tickers() -> dict[str, dict]:
    ticker_data: dict[str, dict] = defaultdict(lambda: {
        "mentions": 0, "weighted": 0.0,
        "sentiment_sum": 0.0, "sentiment_count": 0,
        "upvotes": 0, "subreddits": set(), "sample_titles": [],
        "platform": "reddit",
    })

    for sub, weight in _SUBREDDITS:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=50",
                headers=_HEADERS,
                timeout=10,
            )
            if resp.status_code == 429:
                logger.debug(f"Reddit rate limit on r/{sub}")
                time.sleep(2)
                continue
            if resp.status_code != 200:
                continue

            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                p        = post.get("data", {})
                text     = f"{p.get('title','')} {p.get('selftext','')}"
                score    = p.get("score", 0)
                comments = p.get("num_comments", 0)
                title    = p.get("title", "")[:100]

                tickers = _extract_tickers(text)
                if not tickers:
                    continue

                sent  = _sentiment_score(text)
                boost = _engagement_boost(likes=score, comments=comments)

                for ticker in tickers:
                    d = ticker_data[ticker]
                    d["mentions"] += 1
                    d["weighted"] += weight * boost
                    d["sentiment_sum"] += sent
                    d["sentiment_count"] += 1
                    d["upvotes"] += score
                    d["subreddits"].add(f"r/{sub}")
                    if len(d["sample_titles"]) < 3 and title not in d["sample_titles"]:
                        d["sample_titles"].append(title)

            time.sleep(1.2)

        except Exception as e:
            logger.debug(f"Reddit r/{sub} failed: {e}")

    return dict(ticker_data)


# ── Bluesky ───────────────────────────────────────────────────────────────────

def scan_bluesky_tickers() -> dict[str, dict]:
    """
    Search Bluesky for cashtag mentions using the free public AT Protocol API.
    No auth required. Finance community is growing fast here — global users.
    """
    ticker_data: dict[str, dict] = defaultdict(lambda: {
        "mentions": 0, "weighted": 0.0,
        "sentiment_sum": 0.0, "sentiment_count": 0,
        "platform": "bluesky",
    })

    search_terms = [
        "stocks", "wallstreetbets", "trading", "options",
        "FTSE", "HangSeng", "investing", "daytrading",
    ]
    weight = 0.8

    for term in search_terms:
        try:
            resp = requests.get(
                "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
                params={"q": term, "limit": 50},
                timeout=10,
            )
            if resp.status_code != 200:
                continue

            posts = resp.json().get("posts", [])
            for post in posts:
                record  = post.get("record", {})
                text    = record.get("text", "")
                likes   = post.get("likeCount", 0)
                reposts = post.get("repostCount", 0)
                replies = post.get("replyCount", 0)

                tickers = _extract_tickers(text)
                if not tickers:
                    continue

                sent  = _sentiment_score(text)
                boost = _engagement_boost(likes, reposts, replies)

                for ticker in tickers:
                    d = ticker_data[ticker]
                    d["mentions"] += 1
                    d["weighted"] += weight * boost
                    d["sentiment_sum"] += sent
                    d["sentiment_count"] += 1

            time.sleep(0.5)

        except Exception as e:
            logger.debug(f"Bluesky scan failed for '{term}': {e}")

    return dict(ticker_data)


# ── Truth Social ──────────────────────────────────────────────────────────────

def scan_truth_social_tickers() -> dict[str, dict]:
    """
    Search Truth Social using its Mastodon-compatible public API.
    Particularly useful for energy, defense, and Trump-adjacent stocks.
    No auth required for public search.
    """
    ticker_data: dict[str, dict] = defaultdict(lambda: {
        "mentions": 0, "weighted": 0.0,
        "sentiment_sum": 0.0, "sentiment_count": 0,
        "platform": "truth_social",
    })

    search_terms = ["stocks", "trading", "investing", "wallstreetbets"]
    weight = 0.5

    for term in search_terms:
        try:
            resp = requests.get(
                "https://truthsocial.com/api/v2/search",
                params={"q": term, "type": "statuses", "limit": 40},
                headers={**_HEADERS, "Accept": "application/json"},
                timeout=12,
            )
            if resp.status_code != 200:
                continue

            statuses = resp.json().get("statuses", [])
            for status in statuses:
                # Strip HTML tags from content
                raw = re.sub(r'<[^>]+>', ' ', status.get("content", ""))
                text = re.sub(r'\s+', ' ', raw).strip()

                likes     = status.get("favourites_count", 0)
                reposts   = status.get("reblogs_count", 0)
                replies   = status.get("replies_count", 0)

                tickers = _extract_tickers(text)
                if not tickers:
                    continue

                sent  = _sentiment_score(text)
                boost = _engagement_boost(likes, reposts, replies)

                for ticker in tickers:
                    d = ticker_data[ticker]
                    d["mentions"] += 1
                    d["weighted"] += weight * boost
                    d["sentiment_sum"] += sent
                    d["sentiment_count"] += 1

            time.sleep(0.8)

        except Exception as e:
            logger.debug(f"Truth Social scan failed for '{term}': {e}")

    return dict(ticker_data)


# ── Aggregator ────────────────────────────────────────────────────────────────

def get_all_social_tickers(min_mentions: int = 2) -> list[dict]:
    """
    Master aggregator — pulls from all platforms, merges by ticker,
    and returns a unified ranked list sorted by conviction score.

    Each entry includes platform breakdown so you can see WHERE the signal is coming from.
    """
    cached = _cached("all_social")
    if cached:
        return cached

    from shared.config import config
    bearer_token = config.TWITTER_BEARER_TOKEN

    # Run all scanners
    twitter_data = scan_twitter_tickers(bearer_token)
    reddit_data  = scan_reddit_tickers()
    bsky_data    = scan_bluesky_tickers()
    truth_data   = scan_truth_social_tickers()

    # Merge all sources into unified per-ticker aggregates
    all_tickers: dict[str, dict] = defaultdict(lambda: {
        "total_mentions":  0,
        "conviction":      0.0,
        "sentiment_sum":   0.0,
        "sentiment_count": 0,
        "platforms":       set(),
        "subreddits":      set(),
        "sample_titles":   [],
        "twitter_score":   0.0,
        "reddit_score":    0.0,
        "bluesky_score":   0.0,
        "truth_score":     0.0,
    })

    def _merge(source: dict[str, dict], platform: str, score_key: str):
        for ticker, d in source.items():
            a = all_tickers[ticker]
            a["total_mentions"]  += d["mentions"]
            a["conviction"]      += d["weighted"]
            a["sentiment_sum"]   += d["sentiment_sum"]
            a["sentiment_count"] += d["sentiment_count"]
            a["platforms"].add(platform)
            a[score_key]         += d["weighted"]
            if "subreddits" in d:
                a["subreddits"].update(d["subreddits"])
            if "sample_titles" in d:
                for t in d["sample_titles"]:
                    if t not in a["sample_titles"] and len(a["sample_titles"]) < 3:
                        a["sample_titles"].append(t)

    _merge(twitter_data, "Twitter/X",    "twitter_score")
    _merge(reddit_data,  "Reddit",       "reddit_score")
    _merge(bsky_data,    "Bluesky",      "bluesky_score")
    _merge(truth_data,   "Truth Social", "truth_score")

    # Build final list
    results = []
    for ticker, d in all_tickers.items():
        if d["total_mentions"] < min_mentions:
            continue
        avg_sent = d["sentiment_sum"] / d["sentiment_count"] if d["sentiment_count"] else 0.0
        results.append({
            "ticker":          ticker,
            "mentions":        d["total_mentions"],
            "conviction":      round(d["conviction"], 2),
            "sentiment":       round(avg_sent, 3),
            "sentiment_label": "bullish" if avg_sent > 0.1 else ("bearish" if avg_sent < -0.1 else "neutral"),
            "platforms":       sorted(d["platforms"]),
            "platform_count":  len(d["platforms"]),
            "subreddits":      sorted(d["subreddits"]),
            "twitter_score":   round(d["twitter_score"], 1),
            "reddit_score":    round(d["reddit_score"], 1),
            "bluesky_score":   round(d["bluesky_score"], 1),
            "truth_score":     round(d["truth_score"], 1),
            "sample_titles":   d["sample_titles"],
            "cross_platform":  len(d["platforms"]) >= 2,  # trending in multiple places = stronger signal
        })

    results.sort(key=lambda x: x["conviction"], reverse=True)
    _store("all_social", results)
    return results


def get_ticker_social_context(ticker: str) -> dict:
    """
    Get full social context for one ticker across all platforms.
    Used to enrich LLM signal analysis.
    """
    cached = _cached(f"social_ctx_{ticker}")
    if cached:
        return cached

    all_tickers = get_all_social_tickers(min_mentions=1)
    match = next((t for t in all_tickers if t["ticker"] == ticker), None)

    if not match:
        result = {
            "found": False,
            "llm_context": "",
            "summary": f"No significant social media mentions found for {ticker} today.",
        }
    else:
        platforms = ", ".join(match["platforms"])
        cross = " 🔥 CROSS-PLATFORM BUZZ" if match["cross_platform"] else ""
        result = {
            "found":      True,
            "conviction": match["conviction"],
            "sentiment":  match["sentiment_label"],
            "platforms":  match["platforms"],
            "llm_context": (
                f"SOCIAL MEDIA SIGNAL — {ticker}{cross}: "
                f"{match['mentions']} mentions across {platforms}. "
                f"Community sentiment: {match['sentiment_label'].upper()}. "
                f"Conviction score: {match['conviction']:.1f} "
                f"(Twitter: {match['twitter_score']:.0f} | Reddit: {match['reddit_score']:.0f} | "
                f"Bluesky: {match['bluesky_score']:.0f} | Truth: {match['truth_score']:.0f})."
                + (f"\nSample posts: " + " | ".join(match["sample_titles"]) if match["sample_titles"] else "")
            ),
            "summary": (
                f"{match['mentions']} social mentions across {platforms}. "
                f"Sentiment: {match['sentiment_label'].upper()}. "
                f"Conviction: {match['conviction']:.1f}."
                + (" Trending on multiple platforms." if match["cross_platform"] else "")
            ),
        }

    _store(f"social_ctx_{ticker}", result)
    return result


def format_social_report(top_n: int = 15) -> str:
    """
    Formatted report for the /social Telegram command.
    Shows top picks ranked by cross-platform conviction with source breakdown.
    """
    tickers = get_all_social_tickers()
    if not tickers:
        return "No social data available right now. Try again shortly."

    lines = ["<b>📡 Social Intelligence — Top Picks Across All Platforms</b>\n"]

    for i, t in enumerate(tickers[:top_n], 1):
        sent_emoji = "🟢" if t["sentiment_label"] == "bullish" else ("🔴" if t["sentiment_label"] == "bearish" else "⚪")
        cross = " 🔥" if t["cross_platform"] else ""
        platform_str = " + ".join(t["platforms"])

        score_parts = []
        if t["twitter_score"] > 0:
            score_parts.append(f"X:{t['twitter_score']:.0f}")
        if t["reddit_score"] > 0:
            score_parts.append(f"Reddit:{t['reddit_score']:.0f}")
        if t["bluesky_score"] > 0:
            score_parts.append(f"BSky:{t['bluesky_score']:.0f}")
        if t["truth_score"] > 0:
            score_parts.append(f"Truth:{t['truth_score']:.0f}")

        lines.append(
            f"{i}. <b>${t['ticker']}</b> {sent_emoji}{cross} — "
            f"{t['mentions']} mentions | score {t['conviction']:.0f}\n"
            f"   <i>{' | '.join(score_parts)}</i>"
        )

    lines.append(
        "\n<i>🔥 = trending on 2+ platforms simultaneously — strongest social signal.\n"
        "Conviction score weighted by platform reach + post engagement.\n"
        "Social data is one input. Cross-reference with Argus fundamentals. DYOR.</i>"
    )
    return "\n".join(lines)
