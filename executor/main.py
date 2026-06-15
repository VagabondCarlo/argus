import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
from executor.audit.auditor import run_audit
from notifications.bot import send_sync_notification
from analyst.data.market import get_market_snapshot
from analyst.sentiment.analyzer import get_spy_context
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

_bearer = HTTPBearer()

def _require_internal(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    """All control endpoints require the master key as a Bearer token."""
    if credentials.credentials != config.MASTER_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


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
    # Pull signals in the 70-100% range — both audit candidates and direct executes
    signals = get_todays_signals(min_confidence=0.70)
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
            execute_signal(signal, account)
            return

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


@app.post("/control/pause", dependencies=[Depends(_require_internal)])
def pause():
    global _paused
    _paused = True
    send_sync_notification("⏸ *Argus paused* — no trades will execute until resumed.")
    return {"paused": True}


@app.post("/control/resume", dependencies=[Depends(_require_internal)])
def resume():
    global _paused
    _paused = False
    send_sync_notification("▶️ *Argus resumed* — monitoring signals.")
    return {"paused": False}


@app.post("/control/stop", dependencies=[Depends(_require_internal)])
def emergency_stop():
    global _stopped, _paused
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
