import logging
from analyst.data.market import scan_watchlist
from analyst.data.news import fetch_news, format_news_for_prompt
from analyst.sentiment.analyzer import analyze_ticker
from shared.database import save_signal, get_todays_signals, get_conn
from notifications.bot import send_sync_notification
from datetime import datetime, date

logger = logging.getLogger(__name__)


def is_market_hours() -> bool:
    """Returns True if current time is during US market hours (9:30AM - 4:00PM ET weekdays)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def already_analyzed_today(ticker: str) -> bool:
    """Avoid re-analyzing the same ticker multiple times in one day."""
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM signals WHERE ticker=? AND date(generated_at)=?",
            (ticker, today)
        ).fetchone()
    return row is not None


def run_scan() -> list[dict]:
    """
    Full scan cycle:
    1. Get technical snapshots for all watchlist tickers
    2. Fetch recent news
    3. Send to LLM for analysis
    4. Save all signals >= 0.60 confidence to database
    5. Notify owner of any signals >= threshold
    """
    logger.info("Starting market scan...")
    snapshots = scan_watchlist()
    new_signals = []
    trade_date = date.today().isoformat()

    for snap in snapshots:
        ticker = snap["ticker"]

        if already_analyzed_today(ticker):
            continue

        news = fetch_news(ticker)
        news_text = format_news_for_prompt(news)
        signal = analyze_ticker(snap, news_text)

        if signal is None:
            continue

        # Update signals analyzed count
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO daily_stats (trade_date, signals_analyzed)
                VALUES (?, 1)
                ON CONFLICT(trade_date) DO UPDATE SET signals_analyzed = signals_analyzed + 1
            """, (trade_date,))

        action = signal.get("action", "HOLD")
        confidence = signal.get("confidence", 0.0)

        if action == "HOLD" or confidence < 0.60:
            with get_conn() as conn:
                conn.execute("""
                    INSERT INTO daily_stats (trade_date, signals_rejected)
                    VALUES (?, 1)
                    ON CONFLICT(trade_date) DO UPDATE SET signals_rejected = signals_rejected + 1
                """, (trade_date,))
            continue

        save_signal(
            ticker=ticker,
            action=action,
            confidence=confidence,
            price_target=signal.get("price_target", snap["price"]),
            stop_loss=signal.get("stop_loss", snap["price"] * 0.98),
            reasoning=signal.get("reasoning", ""),
        )
        new_signals.append(signal)
        logger.info(f"Signal saved: {ticker} {action} {confidence:.0%}")

    # Notify owner of actionable signals
    actionable = [s for s in new_signals if s["confidence"] >= 0.75]
    if actionable:
        lines = ["🔵 *New signals above threshold:*\n"]
        for s in actionable:
            lines.append(
                f"• *{s['ticker']}* {s['action']} — {s['confidence']:.0%} confidence\n"
                f"  _{s['reasoning'][:100]}_"
            )
        send_sync_notification("\n".join(lines))

    logger.info(f"Scan complete: {len(new_signals)} signals saved, {len(actionable)} actionable")
    return new_signals
