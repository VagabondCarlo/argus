import logging
from datetime import datetime, timedelta, timezone
from shared.config import config
from shared.database import get_conn

logger = logging.getLogger(__name__)


def get_weekly_trade_count() -> int:
    """Count trade ENTRIES since Monday of current week (UTC).

    Close rows (order_id='close') are excluded — a round trip is one trade,
    not two, so 25/week means 25 actual entries.
    """
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE date(executed_at) >= ? AND order_id != 'close'",
            (monday.isoformat(),)
        ).fetchone()
    return row["cnt"] if row else 0


def get_weekly_pnl() -> float:
    """Sum of P&L for closed trades since Monday (UTC)."""
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE date(closed_at) >= ? AND status='closed'",
            (monday.isoformat(),)
        ).fetchone()
    return float(row["total"]) if row else 0.0


def calculate_position_size(price: float) -> float:
    """
    How many shares to buy.

    Always sized against ACCOUNT_CAPITAL, not the broker cash balance.
    Paper accounts start with $100K but we only risk ACCOUNT_CAPITAL ($500).
    Using account_cash would create positions 200x too large on paper accounts.
    """
    risk_dollars = config.ACCOUNT_CAPITAL * config.MAX_POSITION_SIZE
    qty = risk_dollars / price
    return round(qty, 6)


def calculate_stop_loss(entry_price: float, side: str) -> float:
    """Hard stop-loss price based on config percentage."""
    if side == "BUY":
        return round(entry_price * (1 - config.STOP_LOSS_PCT), 2)
    return round(entry_price * (1 + config.STOP_LOSS_PCT), 2)


def check_trade_allowed(
    account_cash: float,
    unrealized_pnl: float = 0.0,
    daily_pnl: float = 0.0,
) -> tuple[bool, str]:
    """
    Returns (allowed, reason). Enforces all hard limits before a trade executes.

    unrealized_pnl: sum of open position unrealized P&L from Alpaca (negative = losing)
    daily_pnl:      today's equity change from Alpaca account (negative = losing today)
    """
    # Weekly trade count
    weekly_count = get_weekly_trade_count()
    if weekly_count >= config.MAX_TRADES_PER_WEEK:
        return False, f"Weekly trade limit reached ({weekly_count}/{config.MAX_TRADES_PER_WEEK})"

    # Daily loss limit — uses live Alpaca equity change, catches intraday swings
    daily_limit = config.ACCOUNT_CAPITAL * config.DAILY_LOSS_LIMIT
    if daily_pnl <= -daily_limit:
        return False, f"Daily loss limit hit (${daily_pnl:.2f} today / limit -${daily_limit:.2f})"

    # Weekly loss limit — realized closed trade P&L + current open position losses
    # Previously only checked closed trades, so open positions were invisible to the kill switch
    realized = get_weekly_pnl()
    total_pnl = realized + unrealized_pnl
    weekly_limit = config.ACCOUNT_CAPITAL * config.WEEKLY_LOSS_LIMIT
    if total_pnl <= -weekly_limit:
        return False, (
            f"Weekly loss limit hit — "
            f"realized ${realized:.2f} + unrealized ${unrealized_pnl:.2f} = ${total_pnl:.2f} "
            f"(limit -${weekly_limit:.2f})"
        )

    if account_cash < 10:
        return False, f"Insufficient cash (${account_cash:.2f})"

    return True, "ok"
