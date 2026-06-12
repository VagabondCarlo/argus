import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from shared.config import config
from shared.database import init_db, get_todays_signals, get_todays_trades, get_trade_history, get_conn
from executor.gateway.alpaca import (
    get_account, get_latest_price, place_order,
    close_all_positions, trades_this_week
)
from executor.risk.manager import (
    check_trade_allowed, calculate_position_size, calculate_stop_loss, get_weekly_trade_count
)
from notifications.bot import send_sync_notification
from datetime import datetime
import time as time_module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_paused = False
_stopped = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    t = threading.Thread(target=signal_watcher_loop, daemon=True)
    t.start()
    yield


app = FastAPI(title="Argus Executor", lifespan=lifespan)


# ── Signal watcher ─────────────────────────────────────────────────────────────

def signal_watcher_loop():
    """Checks for pending high-confidence signals every 5 minutes."""
    while not _stopped:
        if not _paused:
            try:
                process_pending_signals()
            except Exception as e:
                logger.error(f"Signal watcher error: {e}")
        time_module.sleep(300)


def process_pending_signals():
    signals = get_todays_signals(min_confidence=config.CONFIDENCE_THRESHOLD)
    actionable = [s for s in signals if not s["executed"]]

    if not actionable:
        return

    account = get_account()
    if not account:
        logger.warning("Cannot process signals — account unreachable")
        return

    allowed, reason = check_trade_allowed(account["cash"])
    if not allowed:
        logger.info(f"Trade blocked: {reason}")
        return

    signal = actionable[0]  # Take highest confidence signal
    execute_signal(signal, account)


def execute_signal(signal: dict, account: dict):
    ticker = signal["ticker"]
    side = signal["action"]

    price = get_latest_price(ticker)
    if not price:
        logger.error(f"Cannot get price for {ticker}")
        return

    qty = calculate_position_size(account["cash"], price)
    stop_price = calculate_stop_loss(price, side)

    if qty < 0.001:
        logger.warning(f"Position size too small for {ticker} at ${price}")
        return

    result = place_order(ticker, side, qty, stop_price)

    if "error" in result:
        logger.error(f"Order failed: {result['error']}")
        send_sync_notification(f"❌ *Trade failed*: {ticker} {side}\n_{result['error']}_")
        return

    # Mark signal as executed in database
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET executed=1 WHERE id=?",
            (signal["id"],)
        )
        conn.execute("""
            INSERT INTO trades (signal_id, order_id, fill_price, quantity, executed_at, status)
            VALUES (?, ?, ?, ?, ?, 'open')
        """, (signal["id"], result["order_id"], price, qty, datetime.utcnow().isoformat()))

        # Update daily stats
        trade_date = datetime.utcnow().date().isoformat()
        conn.execute("""
            INSERT INTO daily_stats (trade_date, signals_executed)
            VALUES (?, 1)
            ON CONFLICT(trade_date) DO UPDATE SET signals_executed = signals_executed + 1
        """, (trade_date,))

    trades_left = config.MAX_TRADES_PER_WEEK - get_weekly_trade_count()
    send_sync_notification(
        f"✅ *Trade Executed*\n\n"
        f"{side} {qty:.4f} shares of *{ticker}*\n"
        f"Entry: ${price:.2f} | Stop: ${stop_price:.2f}\n"
        f"Confidence: {signal['confidence']:.0%}\n"
        f"Trades remaining this week: {trades_left}\n\n"
        f"_{signal['reasoning'][:120]}_"
    )
    logger.info(f"Executed: {side} {qty} {ticker} @ ${price}")


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.get("/status")
def status():
    account = get_account()
    return {
        "paused": _paused,
        "stopped": _stopped,
        "trades_this_week": get_weekly_trade_count(),
        "account": account,
        "daily_report": _build_daily_report(),
        "trade_history": get_trade_history(limit=10),
    }


@app.post("/control/pause")
def pause():
    global _paused
    _paused = True
    send_sync_notification("⏸ *Argus paused* — no trades will execute until resumed.")
    return {"paused": True}


@app.post("/control/resume")
def resume():
    global _paused
    _paused = False
    send_sync_notification("▶️ *Argus resumed* — monitoring signals.")
    return {"paused": False}


@app.post("/control/stop")
def emergency_stop():
    global _stopped, _paused
    _stopped = True
    _paused = True
    result = close_all_positions()
    send_sync_notification("🛑 *Emergency stop executed.* All positions closed. Argus halted.")
    return {"stopped": True, "positions_closed": result}


class ThresholdUpdate(BaseModel):
    value: float


@app.post("/control/threshold")
def set_threshold(body: ThresholdUpdate):
    if not 0.50 <= body.value <= 1.0:
        raise HTTPException(status_code=400, detail="Threshold must be between 0.50 and 1.00")
    config.CONFIDENCE_THRESHOLD = body.value
    return {"threshold": body.value}


def _build_daily_report() -> dict:
    from shared.database import get_todays_stats
    stats = get_todays_stats()
    return {
        "trades_executed": stats["signals_executed"],
        "wins": stats["wins"],
        "losses": stats["losses"],
        "pnl": stats["total_pnl"],
        "signals_analyzed": stats["signals_analyzed"],
        "signals_rejected": stats["signals_rejected"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("executor.main:app", host="0.0.0.0", port=config.EXECUTOR_PORT, reload=False)
