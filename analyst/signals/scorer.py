import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from analyst.data.universe import get_core_universe, get_full_universe
from analyst.data.screener import run_prescreen, filter_by_market_regime
from analyst.data.market import get_market_snapshot
from analyst.data.news import fetch_news, format_news_for_prompt
from analyst.sentiment.analyzer import analyze_ticker, get_spy_context
from shared.database import save_signal, get_todays_signals, get_conn
from shared.config import config
from notifications.bot import send_sync_notification

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_time <= now <= close_time


def is_premarket() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return now.replace(hour=7, minute=0) <= now < now.replace(hour=9, minute=30)


def already_analyzed_today(ticker: str) -> bool:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM signals WHERE ticker=? AND date(generated_at)=?",
            (ticker, today)
        ).fetchone()
    return row is not None


def get_weekly_signal_count() -> int:
    """How many signals have we already committed to this week."""
    from datetime import timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM signals WHERE executed=1 AND date(generated_at)>=?",
            (monday.isoformat(),)
        ).fetchone()
    return row["cnt"] if row else 0


def run_scan(full_universe: bool = False) -> list[dict]:
    """
    Full scan pipeline:
    1. Load universe (core or full)
    2. Pre-screen for activity (fast, rule-based)
    3. Adjust for market regime (SPY direction)
    4. Deep technical analysis on candidates
    5. LLM veteran scoring
    6. Save and notify on actionable signals

    Only analyzes tickers not already seen today.
    Stops early if weekly trade limit is reached.
    """
    weekly_count = get_weekly_signal_count()
    if weekly_count >= config.MAX_TRADES_PER_WEEK:
        logger.info(f"Weekly trade limit reached ({weekly_count}). No new signals needed.")
        return []

    # Step 1: Universe
    tickers = get_full_universe() if full_universe else get_core_universe()
    tickers = [t for t in tickers if not already_analyzed_today(t)]

    if not tickers:
        logger.info("All tickers already analyzed today.")
        return []

    # Step 2: Pre-screen
    candidates = run_prescreen(tickers)
    if not candidates:
        logger.info("No candidates passed pre-screen.")
        return []

    # Step 3: Fetch SPY context once — used for regime filter AND passed into every LLM call
    spy_change, market_regime = get_spy_context()
    candidates = filter_by_market_regime(candidates, spy_change)
    logger.info(f"Analyzing {len(candidates)} candidates (SPY: {spy_change:+.1f}%)")

    new_signals = []
    trade_date = date.today().isoformat()

    # Step 4 + 5: Deep analysis + LLM scoring
    for candidate in candidates:
        ticker = candidate["ticker"]

        snapshot = get_market_snapshot(ticker)
        if snapshot is None:
            continue

        news = fetch_news(ticker)
        news_text = format_news_for_prompt(news)
        signal = analyze_ticker(snapshot, news_text, spy_change=spy_change, market_regime=market_regime)

        if signal is None:
            continue

        action = signal.get("action", "HOLD")
        confidence = signal.get("confidence", 0.0)
        risk_reward = signal.get("risk_reward", 0.0)

        # Update signals analyzed count
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO daily_stats (trade_date, signals_analyzed)
                VALUES (?, 1)
                ON CONFLICT(trade_date) DO UPDATE SET signals_analyzed = signals_analyzed + 1
            """, (trade_date,))

        if action == "HOLD" or confidence < 0.60 or risk_reward < 1.5:
            logger.info(f"PASS: {ticker} | {action} | conf={confidence:.0%} | R/R={risk_reward:.1f}")
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
            price_target=signal.get("price_target", snapshot["price"]),
            stop_loss=signal.get("stop_loss", snapshot["price"] * 0.98),
            reasoning=signal.get("reasoning", ""),
        )
        new_signals.append(signal)

        logger.info(
            f"SIGNAL: {ticker} {action} | conf={confidence:.0%} | "
            f"R/R={risk_reward:.1f} | {signal.get('setup_type','')}"
        )

    # Step 6: Notify on actionable signals
    actionable = [s for s in new_signals if s["confidence"] >= config.CONFIDENCE_THRESHOLD]

    if actionable:
        lines = [f"🔵 *{len(actionable)} trade signal(s) ready*\n"]
        for s in actionable:
            rr = s.get("risk_reward", 0)
            lines.append(
                f"*{s['ticker']}* {s['action']} — {s['confidence']:.0%} confidence\n"
                f"Target: ${s['price_target']:.2f} | Stop: ${s['stop_loss']:.2f} | R/R: {rr:.1f}x\n"
                f"Setup: {s.get('setup_type','')}\n"
                f"_{s['reasoning'][:120]}_\n"
            )
        send_sync_notification("\n".join(lines))

    logger.info(
        f"Scan done: {len(new_signals)} signals saved, "
        f"{len(actionable)} above {config.CONFIDENCE_THRESHOLD:.0%} threshold"
    )
    return new_signals
