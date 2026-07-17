"""Public track-record feed — radical transparency as the product.

Every closed trade posts a card to the track-record channel: entry, exit,
P&L in dollars, and the running record. Wins and losses, no exceptions.
A daily recap posts after the close.

Posts go to TRACK_RECORD_CHANNEL_ID; if unset, they fall back to the owner's
chat tagged [PREVIEW] so formatting can be judged before going public.

Telegram design rules used here: card width fits a phone (<= 30 chars),
numbers live in monospace backticks so they align, one emoji as the state
glyph, the running record on every card so no single post can cherry-pick.
"""
import logging
from datetime import datetime

import requests

from shared.config import config
from shared.database import get_win_rate, get_todays_stats, get_conn

logger = logging.getLogger(__name__)


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.2f}"
    return f"{p:.4f}"


def _fmt_money(v: float, signed: bool = True) -> str:
    sign = "+" if v >= 0 else "-"
    return f"{sign if signed else ''}${abs(v):,.2f}"


def _fmt_duration(start_iso: str, end_iso: str) -> str:
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        mins = int((end - start).total_seconds() // 60)
        if mins < 60:
            return f"{mins}m"
        if mins < 60 * 24:
            return f"{mins // 60}h {mins % 60:02d}m"
        return f"{mins // (60 * 24)}d {(mins % (60 * 24)) // 60}h"
    except (ValueError, TypeError):
        return "—"


def get_last_closed_trade(ticker: str) -> dict | None:
    """Most recently closed trade for a ticker, joined with its signal."""
    norm = ticker.replace("-", "").replace("/", "").upper()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT s.ticker, s.confidence, t.fill_price, t.close_price,
                   t.quantity, t.pnl, t.executed_at, t.closed_at
            FROM trades t JOIN signals s ON t.signal_id = s.id
            WHERE REPLACE(REPLACE(UPPER(s.ticker), '-', ''), '/', '') = ?
            AND t.status = 'closed'
            ORDER BY t.closed_at DESC LIMIT 1
        """, (norm,)).fetchone()
    return dict(row) if row else None


def format_trade_close(t: dict, record: dict) -> str:
    pnl = t["pnl"] or 0.0
    is_win = pnl >= 0
    head = f"{'✅ WIN' if is_win else '❌ LOSS'} — {t['ticker']}"
    cost = (t["fill_price"] or 0) * (t["quantity"] or 0)
    pct = (pnl / cost * 100) if cost else 0.0
    held = _fmt_duration(t["executed_at"], t["closed_at"])

    lines = [
        head,
        f"`in  ${_fmt_price(t['fill_price'])}`",
        f"`out ${_fmt_price(t['close_price'])}`",
        f"`p&l {_fmt_money(pnl)}  ({pct:+.1f}%)`",
        f"`sig {t['confidence']:.0%} · held {held}`",
        "",
        _record_line(record),
        "_paper trading · every trade posted_",
    ]
    return "\n".join(lines)


def _record_line(record: dict) -> str:
    total = record["total_trades"]
    if not total:
        return "📊 Record: first trade on the books"
    return (
        f"📊 Record: {record['wins']}W-{record['losses']}L "
        f"({record['win_rate']:.0%}) · {_fmt_money(record['total_pnl'])}"
    )


def format_daily_recap() -> str:
    stats = get_todays_stats()
    record = get_win_rate()
    with get_conn() as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM trades WHERE status='open'"
        ).fetchone()["c"]

    day = datetime.now().strftime("%b %d")
    day_trades = stats["wins"] + stats["losses"]
    lines = [
        f"📊 *Argus Daily — {day}*",
        f"`closed {day_trades}  ({stats['wins']}W-{stats['losses']}L)`",
        f"`day    {_fmt_money(stats['total_pnl'])}`",
        f"`open   {open_count} position{'s' if open_count != 1 else ''}`",
        "",
        _record_line(record).replace("📊 Record", "All-time"),
        "_paper trading · every trade posted_",
    ]
    return "\n".join(lines)


def send_channel_post(text: str):
    """Post to the track-record channel, or preview to the owner if unset."""
    chat_id = config.TRACK_RECORD_CHANNEL_ID or config.TELEGRAM_CHAT_ID
    if not config.TRACK_RECORD_CHANNEL_ID:
        text = "[PREVIEW — set TRACK_RECORD_CHANNEL_ID to go public]\n\n" + text
    if not chat_id:
        logger.warning("No chat configured for track-record post")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Track-record post failed: {e}")


def post_trade_close(ticker: str):
    """Called by the executor after any position close. Never raises —
    a feed hiccup must not break the trading loop."""
    try:
        t = get_last_closed_trade(ticker)
        if not t:
            logger.warning(f"No closed trade found for track-record post: {ticker}")
            return
        send_channel_post(format_trade_close(t, get_win_rate()))
    except Exception as e:
        logger.error(f"post_trade_close failed for {ticker}: {e}")
