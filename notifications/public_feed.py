"""Public feed — the ONE place that decides what leaves the building.

Everything shown on the public terminal comes through build_public_payload().
It emits only public-safe fields. The hard rules, enforced here and guarded by
tests/test_public_feed.py:

  • LIVE signals expose direction + probability + suggested STOP only.
    Never entry, never target — those are the Pro gate.
  • CLOSED trades (the track record) may show historical entry/exit — they are
    settled history, not an actionable instruction.
  • No secrets, keys, tokens, IPs, or internal fields ever appear.
  • Degenerate signals (stop == entry, e.g. sub-dollar rounding collapse) are
    dropped rather than shown as garbage.

If a field isn't explicitly built into the payload below, it does not go out.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

from shared.config import config
from shared.database import get_conn, get_win_rate

logger = logging.getLogger(__name__)

DISPLAY_MIN_CONF = 0.62          # watchlist floor
DISPLAY_WINDOW_HOURS = 12        # how far back live signals stay on the board
HIGH_CONVICTION = config.CONFIDENCE_THRESHOLD  # 0.72 — the trade line
MAX_SIGNALS = 8


def _norm(t: str) -> str:
    return t.replace("-", "").replace("/", "").upper()


def _fmt_price(p: float) -> str:
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.2f}"
    return f"{p:.4f}"


def _held(a: str, b: str) -> str:
    try:
        mins = int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() // 60)
        if mins < 60:
            return f"{mins}m"
        if mins < 1440:
            return f"{mins // 60}h {mins % 60:02d}m"
        return f"{mins // 1440}d {(mins % 1440) // 60}h"
    except (ValueError, TypeError):
        return "—"


# Only asset classes Argus actually executes appear on the public board, so
# every card is a trade the system would take — and the board matches the
# track record. Metals/forex are signal-only (no broker route) and are excluded
# to avoid implying a 77%-conviction pick the system never trades.
TRADEABLE_ASSETS = ("stock", "crypto")


def _live_signals(conn) -> list[dict]:
    cutoff = f"datetime('now','-{DISPLAY_WINDOW_HOURS} hours')"
    placeholders = ",".join("?" * len(TRADEABLE_ASSETS))
    rows = conn.execute(f"""
        SELECT ticker, action, confidence, asset_type, entry_price, stop_loss, price_target
        FROM signals
        WHERE action IN ('BUY','SELL')
          AND confidence >= ?
          AND executed = 0
          AND asset_type IN ({placeholders})
          AND generated_at >= {cutoff}
        ORDER BY confidence DESC
    """, (DISPLAY_MIN_CONF, *TRADEABLE_ASSETS)).fetchall()

    out, seen = [], set()
    for r in rows:
        key = _norm(r["ticker"])
        if key in seen:
            continue
        entry, stop, target = r["entry_price"], r["stop_loss"], r["price_target"]
        # Drop degenerate signals: missing/zero levels, or collapsed to one value
        if not entry or not stop or entry == stop:
            continue
        if target and entry == target:
            continue
        seen.add(key)
        out.append({
            "ticker": r["ticker"],
            "action": r["action"],
            "confidence": round(r["confidence"], 2),
            "asset_type": r["asset_type"],
            "stop": _fmt_price(stop),                       # shown
            "high_conviction": r["confidence"] >= HIGH_CONVICTION,
            # NOTE: entry_price and price_target deliberately NOT included
        })
        if len(out) >= MAX_SIGNALS:
            break
    return out


def _closed_trades(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT s.ticker, s.action, s.confidence, t.fill_price, t.close_price,
               t.pnl, t.executed_at, t.closed_at
        FROM trades t JOIN signals s ON t.signal_id = s.id
        WHERE t.status = 'closed'
        ORDER BY t.closed_at DESC LIMIT 12
    """).fetchall()
    return [{
        "ticker": r["ticker"],
        "action": r["action"],
        "confidence": round(r["confidence"], 2),
        "entry": _fmt_price(r["fill_price"]),               # historical — ok
        "exit": _fmt_price(r["close_price"]),
        "pnl": round(r["pnl"] or 0.0, 2),
        "won": (r["pnl"] or 0) >= 0,
        "held": _held(r["executed_at"], r["closed_at"]),
        "when": (r["closed_at"] or "")[:10],
    } for r in rows]


def _calibration(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT CASE WHEN confidence >= 0.72 THEN '0.72 +'
                    WHEN confidence >= 0.66 THEN '0.66 – 0.72'
                    ELSE '0.62 – 0.66' END band,
               COUNT(*) n,
               SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) wins,
               ROUND(SUM(r_multiple), 1) total_r
        FROM virtual_outcomes GROUP BY band
    """).fetchall()
    shadow = {r["band"]: dict(r) for r in rows}
    out = [{"band": "0.72 +", "n": None, "wins": None, "total_r": None, "status": "traded"}]
    for b in ("0.66 – 0.72", "0.62 – 0.66"):
        r = shadow.get(b)
        out.append({
            "band": b,
            "n": r["n"] if r else 0,
            "wins": r["wins"] if r else 0,
            "total_r": r["total_r"] if r else 0.0,
            "status": "shadow",
        })
    return out


# Futures/metals symbols collide with unrelated words ("SI" → Sports
# Illustrated), so map them to unambiguous commodity names.
_FUTURES_NAMES = {
    "GC=F": "gold price", "SI=F": "silver price", "HG=F": "copper price",
    "PL=F": "platinum price", "PA=F": "palladium price",
    "CL=F": "crude oil price", "NG=F": "natural gas price",
}


def _news_query(tk: str) -> str:
    """Human search query for a ticker. Commodity/crypto/forex get topical
    terms so the base symbol doesn't collide with unrelated tickers."""
    if tk in _FUTURES_NAMES:
        return _FUTURES_NAMES[tk]
    base = tk.split("-")[0].split("=")[0]
    if tk.endswith("-USD"):
        return f"{base} crypto"
    if tk.endswith("=X"):
        return f"{base[:3]}/{base[3:]} forex rate"
    return f"{base} stock"


def _yahoo_news(tk: str) -> list[dict]:
    import yfinance as yf
    out = []
    for art in (yf.Ticker(tk).news or [])[:3]:
        c = art.get("content", art)
        title = c.get("title", "")
        url = (c.get("canonicalUrl", {}) or {}).get("url", "") or c.get("link", "")
        prov = (c.get("provider", {}) or {}).get("displayName", "") or "Yahoo Finance"
        if title and url:
            out.append({"title": title.strip()[:100], "url": url, "source": prov})
    return out


def _google_news(tk: str) -> list[dict]:
    """Google News RSS — aggregates Reuters, Bloomberg, CoinDesk, CNBC, etc.
    No API key. Each item carries its originating publisher in <source>."""
    import urllib.parse
    import urllib.request
    import xml.etree.ElementTree as ET

    q = urllib.parse.quote(_news_query(tk))
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ArgusFeed)"})
    out = []
    with urllib.request.urlopen(req, timeout=5) as r:
        root = ET.fromstring(r.read())
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        src_el = item.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text else "Google News")
        # Google prefixes " - Publisher" onto titles; strip it (source shown separately)
        if source != "Google News" and title.endswith(f"- {source}"):
            title = title[: -(len(source) + 2)].strip()
        if title and link:
            out.append({"title": title[:100], "url": link, "source": source})
        if len(out) >= 4:
            break
    return out


def _title_key(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())[:40]


def _gather_ticker(tk: str) -> dict:
    """All headlines for one ticker, deduped, source-diverse first."""
    import urllib.parse
    from concurrent.futures import ThreadPoolExecutor, as_completed

    heads = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(fn, tk): fn.__name__ for fn in (_google_news, _yahoo_news)}
        for fut in as_completed(futs):
            try:
                heads.extend(fut.result())
            except Exception as e:
                logger.warning(f"news source {futs[fut]} failed for {tk}: {e}")

    # Pass 1: one headline per distinct source (maximizes consensus breadth).
    # Pass 2: backfill remaining slots with any unseen headline.
    seen_titles, seen_sources, picked = set(), set(), []
    for h in heads:
        key = _title_key(h["title"])
        if key not in seen_titles and h["source"] not in seen_sources:
            seen_titles.add(key); seen_sources.add(h["source"]); picked.append(h)
    for h in heads:
        if len(picked) >= 4:
            break
        key = _title_key(h["title"])
        if key not in seen_titles:
            seen_titles.add(key); picked.append(h)

    more = f"https://news.google.com/search?q={urllib.parse.quote(_news_query(tk))}"
    return {"ticker": tk, "headlines": picked[:4], "more": more,
            "sources": sorted(seen_sources)}


def _news_for(tickers: list[str]) -> list[dict]:
    """Multi-source headlines per ticker (Yahoo + Google News aggregation),
    deduped and source-diverse. Tickers gathered in parallel; any source
    failure degrades to whatever succeeded — news never breaks generation."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_gather_ticker, tk): tk for tk in tickers}
        for fut in as_completed(futs):
            try:
                results[futs[fut]] = fut.result()
            except Exception as e:
                logger.warning(f"news gather failed for {futs[fut]}: {e}")
    return [results[tk] for tk in tickers if tk in results]  # preserve order


_NEWS_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "public", "news_cache.json")
_NEWS_TTL = 15 * 60  # headlines are context, not the signal — refetch every 15 min


def _cached_news(tickers: list[str]) -> list[dict]:
    """Cache headlines so the 5-min page refresh doesn't hammer news sources.
    Signals and the record are always live; only the news column is cached.
    Refetches when the cache is stale OR the displayed tickers change."""
    try:
        with open(_NEWS_CACHE) as f:
            c = json.load(f)
        if time.time() - c["ts"] < _NEWS_TTL and c["tickers"] == tickers:
            return c["news"]
    except (FileNotFoundError, KeyError, ValueError):
        pass
    news = _news_for(tickers)
    try:
        os.makedirs(os.path.dirname(_NEWS_CACHE), exist_ok=True)
        with open(_NEWS_CACHE, "w") as f:
            json.dump({"ts": time.time(), "tickers": tickers, "news": news}, f)
    except OSError as e:
        logger.warning(f"news cache write failed: {e}")
    return news


def build_public_payload(include_news: bool = True) -> dict:
    with get_conn() as conn:
        signals = _live_signals(conn)
        closed = _closed_trades(conn)
        calibration = _calibration(conn)
        open_count = conn.execute(
            "SELECT COUNT(*) c FROM trades WHERE status='open'"
        ).fetchone()["c"]
    record = get_win_rate()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "record": {
            "wins": record["wins"], "losses": record["losses"],
            "total_trades": record["total_trades"],
            "win_rate": round(record["win_rate"], 3),
            "total_pnl": round(record["total_pnl"], 2),
        },
        "open_count": open_count,
        "signals": signals,
        "high_conviction_count": sum(1 for s in signals if s["high_conviction"]),
        "closed_trades": closed,
        "calibration": calibration,
    }
    if include_news:
        display_tickers = [s["ticker"] for s in signals][:6] \
            or [c["ticker"] for c in closed][:3]
        payload["news"] = _cached_news(display_tickers)
    return payload
