import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from shared.config import config
from shared.database import init_db, get_todays_signals, get_todays_trades, get_trade_history, get_conn
from executor.gateway.alpaca import (
    get_account, get_latest_price, place_order, close_position,
    close_all_positions, get_open_positions
)
from executor.risk.manager import (
    check_trade_allowed, calculate_position_size, calculate_stop_loss, get_weekly_trade_count
)
from executor.audit.auditor import run_audit
from notifications.bot import send_sync_notification
from analyst.data.market import get_market_snapshot
from analyst.sentiment.analyzer import get_spy_context
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time as time_module
import secrets

_ET = ZoneInfo("America/New_York")

def _is_market_hours() -> bool:
    now = datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now <= close_t

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_state_lock = threading.Lock()
_paused = False
_stopped = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    t = threading.Thread(target=signal_watcher_loop, daemon=True)
    t.start()
    yield


app = FastAPI(title="Argus Executor", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

_bearer = HTTPBearer()

def _require_internal(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    """All control endpoints require the master key as a Bearer token."""
    if not secrets.compare_digest(credentials.credentials, config.MASTER_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Signal watcher ─────────────────────────────────────────────────────────────

def signal_watcher_loop():
    """Checks for pending signals every 60s during market hours, 5min otherwise."""
    while True:
        with _state_lock:
            stopped = _stopped
            paused = _paused
        if stopped:
            break
        if not paused:
            try:
                process_pending_signals()
            except Exception as e:
                logger.error(f"Signal watcher error: {e}")
        interval = 60 if _is_market_hours() else 300
        time_module.sleep(interval)


def process_pending_signals():
    if not _is_market_hours():
        logger.debug("Market closed — skipping signal processing")
        return

    # Only execute stock signals — crypto/forex/metals use different brokers
    signals = get_todays_signals(min_confidence=0.70, asset_type="stock")
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

    spy_change, market_regime = get_spy_context()
    weekly_trades = get_weekly_trade_count()

    for signal in actionable:
        conf = signal["confidence"]

        # Signals already above threshold skip the audit and execute directly
        if conf >= config.CONFIDENCE_THRESHOLD:
            traded = execute_signal(signal, account)
            if traded:
                return  # Real trade placed — one trade per cycle
            continue  # Signal was skipped — move to next in queue

        # Signals in the 70-75% zone go through the executor's independent audit
        logger.info(f"Sending {signal['ticker']} to audit — analyst conf={conf:.0%}")
        snapshot = get_market_snapshot(signal["ticker"])
        if not snapshot:
            logger.warning(f"No snapshot for audit: {signal['ticker']}")
            continue

        audit = run_audit(signal, snapshot, account, weekly_trades, spy_change, market_regime)

        send_sync_notification(
            f"🔍 *Audit Complete: {signal['ticker']}*\n\n"
            f"Analyst: {conf:.0%} → Executor: {audit['audit_confidence']:.0%}\n"
            f"Verdict: {'✅ APPROVED' if audit['approved'] else '❌ VETOED'}\n"
            f"Timing: {audit.get('timing_verdict','—')}\n"
            f"Counter-thesis: _{audit.get('counter_thesis','—')}_\n"
            f"Notes: _{audit.get('audit_notes','—')[:120]}_"
        )

        if audit["approved"] and audit["audit_confidence"] >= config.CONFIDENCE_THRESHOLD:
            signal["confidence"] = audit["audit_confidence"]
            execute_signal(signal, account)
            return
        else:
            logger.info(f"Audit blocked {signal['ticker']}: {audit.get('veto_reason','low confidence')}")


def execute_signal(signal: dict, account: dict) -> bool:
    """Returns True if a real trade was placed, False if signal was skipped."""
    ticker = signal["ticker"]
    side = signal["action"]

    open_positions = get_open_positions()
    existing = next((p for p in open_positions if p["ticker"] == ticker), None)

    if side == "BUY" and existing:
        logger.info(f"Already holding {ticker} — skipping duplicate BUY")
        with get_conn() as conn:
            conn.execute("UPDATE signals SET executed=1 WHERE id=?", (signal["id"],))
        return False

    if side == "SELL" and not existing:
        logger.info(f"No position in {ticker} — skipping SELL (no short selling)")
        with get_conn() as conn:
            conn.execute("UPDATE signals SET executed=1 WHERE id=?", (signal["id"],))
        return False

    if side == "SELL" and existing:
        logger.info(f"Closing position: {ticker} at ~${existing['current_price']:.2f}")
        result = close_position(ticker)
        if "error" in result:
            logger.error(f"Close failed {ticker}: {result['error']}")
            send_sync_notification(f"❌ *Close failed*: {ticker}\n_{result['error']}_")
            return False
        with get_conn() as conn:
            conn.execute("UPDATE signals SET executed=1 WHERE id=?", (signal["id"],))
            conn.execute("""
                INSERT INTO trades (signal_id, order_id, fill_price, quantity, executed_at, status)
                VALUES (?, ?, ?, ?, ?, 'closed')
            """, (signal["id"], "close", existing["current_price"], existing["qty"],
                  datetime.now(timezone.utc).isoformat()))
        send_sync_notification(
            f"✅ *Position closed*: {ticker}\n"
            f"Exit: ~${existing['current_price']:.2f} | P&L: ${existing['unrealized_pnl']:.2f}"
        )
        return True

    # BUY on unowned stock — enter position
    price = get_latest_price(ticker)
    if not price:
        logger.error(f"Cannot get price for {ticker}")
        return False

    qty = calculate_position_size(account["cash"], price)
    stop_price = calculate_stop_loss(price, side)

    if qty < 0.001:
        logger.warning(f"Position size too small for {ticker} at ${price}")
        return False

    result = place_order(ticker, side, qty, stop_price)

    if "error" in result:
        logger.error(f"Order failed: {result['error']}")
        send_sync_notification(f"❌ *Trade failed*: {ticker} {side}\n_{result['error']}_")
        return False

    # Mark signal as executed in database
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET executed=1 WHERE id=?",
            (signal["id"],)
        )
        conn.execute("""
            INSERT INTO trades (signal_id, order_id, fill_price, quantity, executed_at, status)
            VALUES (?, ?, ?, ?, ?, 'open')
        """, (signal["id"], result["order_id"], price, qty, datetime.now(timezone.utc).isoformat()))

        # Update daily stats
        trade_date = datetime.now(timezone.utc).date().isoformat()
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
    return True


# ── REST endpoints ─────────────────────────────────────────────────────────────

class AuditRequest(BaseModel):
    ticker: str
    action: str
    confidence: float
    price_target: float
    stop_loss: float
    risk_reward: float
    setup_type: str = "unknown"
    reasoning: str = ""
    red_flags: str = "none"


@app.post("/audit", dependencies=[Depends(_require_internal)])
def audit_signal(body: AuditRequest):
    """Receive a signal from the Analyst and run the independent Risk Desk audit."""
    signal = body.model_dump()
    snapshot = get_market_snapshot(body.ticker)
    if not snapshot:
        return {"approved": False, "veto_reason": "Could not fetch market data"}

    account = get_account() or {"cash": 0}
    weekly_trades = get_weekly_trade_count()
    spy_change, market_regime = get_spy_context()

    result = run_audit(signal, snapshot, account, weekly_trades, spy_change, market_regime)

    if result["approved"] and result["audit_confidence"] >= config.CONFIDENCE_THRESHOLD:
        allowed, reason = check_trade_allowed(account.get("cash", 0))
        if allowed:
            signal["confidence"] = result["audit_confidence"]
            execute_signal(signal, account)
            result["executed"] = True
        else:
            result["executed"] = False
            result["veto_reason"] = reason
    else:
        result["executed"] = False

    return result


@app.get("/status", dependencies=[Depends(_require_internal)])
def status():
    account = get_account()
    with _state_lock:
        paused, stopped = _paused, _stopped
    return {
        "paused": paused,
        "stopped": stopped,
        "trades_this_week": get_weekly_trade_count(),
        "account": account,
        "daily_report": _build_daily_report(),
        "trade_history": get_trade_history(limit=10),
    }


@app.post("/control/pause", dependencies=[Depends(_require_internal)])
def pause():
    global _paused
    with _state_lock:
        _paused = True
    send_sync_notification("⏸ *Argus paused* — no trades will execute until resumed.")
    return {"paused": True}


@app.post("/control/resume", dependencies=[Depends(_require_internal)])
def resume():
    global _paused
    with _state_lock:
        _paused = False
    send_sync_notification("▶️ *Argus resumed* — monitoring signals.")
    return {"paused": False}


@app.post("/control/stop", dependencies=[Depends(_require_internal)])
def emergency_stop():
    global _stopped, _paused
    with _state_lock:
        _stopped = True
        _paused = True
    result = close_all_positions()
    send_sync_notification("🛑 *Emergency stop executed.* All positions closed. Argus halted.")
    return {"stopped": True, "positions_closed": result}


class ThresholdUpdate(BaseModel):
    value: float


@app.post("/control/threshold", dependencies=[Depends(_require_internal)])
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
    uvicorn.run("executor.main:app", host="127.0.0.1", port=config.EXECUTOR_PORT, reload=False)
