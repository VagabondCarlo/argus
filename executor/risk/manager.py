import logging
from datetime import date, datetime, timedelta, timezone
from shared.config import config
from shared.database import get_conn

logger = logging.getLogger(__name__)


def get_weekly_trade_count() -> int:
    """Count trades executed since Monday of current week (UTC)."""
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE date(executed_at) >= ?",
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


def calculate_position_size(account_cash: float, price: float) -> float:
    """How many shares to buy, respecting max position size rule."""
    max_dollars = account_cash * config.MAX_POSITION_SIZE
    qty = max_dollars / price
    return round(qty, 6)


def calculate_stop_loss(entry_price: float, side: str) -> float:
    """Hard stop-loss price based on config percentage."""
    if side == "BUY":
        return round(entry_price * (1 - config.STOP_LOSS_PCT), 2)
    return round(entry_price * (1 + config.STOP_LOSS_PCT), 2)


def check_trade_allowed(account_cash: float) -> tuple[bool, str]:
    """
    Returns (allowed, reason). Enforces all hard limits before a trade executes.
    """
    weekly_count = get_weekly_trade_count()
    if weekly_count >= config.MAX_TRADES_PER_WEEK:
        return False, f"Weekly trade limit reached ({weekly_count}/{config.MAX_TRADES_PER_WEEK})"

    weekly_pnl = get_weekly_pnl()
    loss_limit = config.ACCOUNT_CAPITAL * config.WEEKLY_LOSS_LIMIT
    if weekly_pnl <= -loss_limit:
        return False, f"Weekly loss kill switch triggered (${weekly_pnl:.2f} loss)"

    if account_cash < 10:
        return False, f"Insufficient cash (${account_cash:.2f})"

    return True, "ok"
