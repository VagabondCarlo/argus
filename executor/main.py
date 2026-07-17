import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from shared.config import config
from shared import database as shared_db
from shared.database import (
    init_db, get_todays_signals, get_todays_trades, get_trade_history, get_conn,
    get_recent_signals, record_position_close, get_signal_levels_for_position,
)
from executor.gateway.alpaca import (
    get_account, get_latest_price, place_order, close_position,
    close_all_positions, get_open_positions, cancel_open_orders,
    is_crypto_tradable, normalize_symbol,
)
from executor.risk.manager import (
    check_trade_allowed, calculate_position_size, calculate_stop_loss, get_weekly_trade_count
)
from executor.audit.auditor import run_audit
from notifications.bot import send_sync_notification
from analyst.data.market import get_market_snapshot
from analyst.sentiment.analyzer import get_spy_context
from datetime import datetime, timedelta, timezone
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
    m = threading.Thread(target=position_monitor_loop, daemon=True)
    m.start()
    yield


app = FastAPI(title="Argus Executor", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

_bearer = HTTPBearer()

def _require_internal(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    """All control endpoints require the master key as a Bearer token."""
    if not secrets.compare_digest(credentials.credentials, config.MASTER_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Signal watcher ─────────────────────────────────────────────────────────────

_breakeven_moved: set[str] = set()
_close_fail_notified: set[str] = set()   # tickers whose failing close was already reported
_notified_failures: set[int] = set()     # signal ids whose failure was already reported
_risk_block_reason: str | None = None    # last risk-limit reason sent to Telegram
_exec_lock = threading.Lock()            # serializes watcher-loop and /audit executions


def _breakeven_path() -> str:
    return os.path.join(os.path.dirname(shared_db.DB_PATH), "breakeven_armed.json")


def _breakeven_load():
    """Armed-breakeven flags survive executor restarts via a JSON sidecar."""
    global _breakeven_moved
    try:
        with open(_breakeven_path()) as f:
            _breakeven_moved = set(json.load(f))
    except FileNotFoundError:
        _breakeven_moved = set()
    except Exception as e:
        logger.warning(f"Could not load breakeven state: {e}")
        _breakeven_moved = set()


def _breakeven_save():
    try:
        with open(_breakeven_path(), "w") as f:
            json.dump(sorted(_breakeven_moved), f)
    except Exception as e:
        logger.warning(f"Could not persist breakeven state: {e}")


def _monitor_close(p: dict) -> tuple[bool, float, float]:
    """Close a position from the monitor. Returns (ok, close_price, pnl).

    Cancels resting stop/take-profit orders first — they hold the shares, and
    Alpaca rejects the close with 'insufficient qty available' otherwise (why
    v1's hard cut never actually closed the June 17 positions). A failing close
    keeps retrying every cycle but only notifies once per ticker.
    """
    ticker = p["ticker"]
    cancelled = cancel_open_orders(ticker)
    if cancelled:
        logger.info(f"Cancelled {cancelled} resting orders for {ticker} before close")
    result = close_position(ticker)
    if "error" in result:
        logger.error(f"Monitor close failed {ticker}: {result['error']}")
        if ticker not in _close_fail_notified:
            _close_fail_notified.add(ticker)
            send_sync_notification(f"❌ *Monitor close failed*: {ticker}\n_{result['error']}_")
        return False, 0.0, 0.0
    _close_fail_notified.discard(ticker)
    close_price = result.get("fill_price") or p["current_price"]
    pnl = (close_price - p["avg_entry"]) * p["qty"]
    record_position_close(ticker, close_price, pnl)
    _breakeven_moved.discard(ticker)
    _breakeven_save()
    return True, close_price, pnl


def _evaluate_position(p: dict, market_open: bool):
    """Apply exit rules to one open position.

    Exit priority: signal stop → signal target → -3% hard cut → breakeven exit.
    The signal's stop/target are enforced HERE in software because most
    positions have no broker-side protection: Alpaca doesn't support stop or
    limit legs on crypto, and fractional stock orders (any stock over $100 a
    share at our $100 position cap) can't carry whole-share legs either. These
    software exits are what make live behavior match the replayed edge.
    """
    if p.get("asset_class", "stock") != "crypto" and not market_open:
        return  # stock exits can only fill while the market is open
    ticker = p["ticker"]
    entry = p["avg_entry"]
    current = p["current_price"]
    pnl_pct = (current - entry) / entry * 100

    levels = get_signal_levels_for_position(ticker) or {}
    stop = levels.get("stop_loss")
    target = levels.get("price_target")

    if stop and current <= stop:
        logger.info(f"STOP HIT: {ticker} ${current:.2f} <= stop ${stop:.2f} — closing")
        ok, close_price, pnl = _monitor_close(p)
        if ok:
            send_sync_notification(
                f"🔴 *Stop hit* — {ticker} closed at ${close_price:.2f}\n"
                f"Entry: ${entry:.2f} | Stop: ${stop:.2f} | P&L: ${pnl:+.2f}"
            )
        return

    if target and current >= target:
        logger.info(f"TARGET HIT: {ticker} ${current:.2f} >= target ${target:.2f} — closing")
        ok, close_price, pnl = _monitor_close(p)
        if ok:
            send_sync_notification(
                f"✅ *Target hit* — {ticker} closed at ${close_price:.2f}\n"
                f"Entry: ${entry:.2f} | Target: ${target:.2f} | P&L: ${pnl:+.2f}"
            )
        return

    # Hard cut backstop: positions with no signal levels, or gaps past the stop
    if pnl_pct <= -3.0:
        logger.info(f"HARD CUT: {ticker} down {pnl_pct:.1f}% — closing")
        ok, close_price, pnl = _monitor_close(p)
        if ok:
            send_sync_notification(
                f"🔴 *Hard cut* — {ticker} closed at {pnl_pct:.1f}%\n"
                f"Entry: ${entry:.2f} → ${close_price:.2f} (P&L ${pnl:+.2f})"
            )
        return

    # Breakeven exit: armed at +1%, closes if price falls back to entry
    if ticker in _breakeven_moved and pnl_pct <= 0:
        logger.info(f"BREAKEVEN EXIT: {ticker} fell back to entry — closing")
        ok, close_price, pnl = _monitor_close(p)
        if ok:
            send_sync_notification(
                f"🟡 *Breakeven exit* — {ticker} closed near entry\n"
                f"Entry: ${entry:.2f} → ${close_price:.2f} (P&L ${pnl:+.2f})"
            )
        return

    if pnl_pct >= 1.0 and ticker not in _breakeven_moved:
        logger.info(f"BREAKEVEN ARMED: {ticker} up {pnl_pct:.1f}% — locking in")
        _breakeven_moved.add(ticker)
        _breakeven_save()
        send_sync_notification(
            f"🟡 *Breakeven armed* — {ticker} up {pnl_pct:.1f}%\n"
            f"Will close if price falls back to entry ${entry:.2f}"
        )


def position_monitor_loop():
    """Watch open positions every 30s, 24/7. Exit rules live in _evaluate_position.

    For crypto and fractional-stock positions this loop IS the stop-loss —
    its cadence is the stop's granularity.
    """
    _breakeven_load()
    while True:
        market_open = _is_market_hours()
        try:
            for p in get_open_positions():
                _evaluate_position(p, market_open)
        except Exception as e:
            logger.error(f"Position monitor error: {e}")
        time_module.sleep(30)


def signal_watcher_loop():
    """Checks for pending signals every 30s, 24/7 — crypto never closes.

    Idle cycles cost one local SQLite query; broker APIs are only touched
    when there's an actionable candidate.
    """
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
        time_module.sleep(30)


def _stock_window_minutes() -> int:
    """Stock signal freshness window, in minutes.

    For the first 15 minutes after the open, reach back through the whole
    pre-market session (7:00 on) so pre-market signals get their shot at the
    bell instead of expiring unexecutable — the drift guard rejects any whose
    price already gapped away overnight.
    """
    now = datetime.now(_ET)
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if timedelta(seconds=0) <= now - open_t <= timedelta(minutes=15):
        return 165  # 7:00 pre-market start → 9:45
    return config.SIGNAL_MAX_AGE_MINUTES


def _rank_key(signal: dict) -> tuple:
    """Sort key: confidence first, reward-to-risk as tiebreak."""
    entry = signal.get("entry_price") or 0.0
    stop = signal.get("stop_loss") or 0.0
    target = signal.get("price_target") or 0.0
    risk = abs(entry - stop)
    rr = abs(target - entry) / risk if risk > 0 else 0.0
    return (signal["confidence"], rr)


def process_pending_signals():
    """Rank the current signal batch and fill open slots best-first.

    v1 walked today's signals in arrival order and took the first one over
    threshold. v2 pulls every fresh candidate (30-min window), ranks by
    confidence then R/R, and fills however many position slots are open —
    the 3 best, not the 3 first.

    Stocks are only processed during market hours; crypto executes 24/7 via
    Alpaca. Forex/metals signals are analytics-only (no broker route).
    """
    candidates = []
    if _is_market_hours():
        candidates += get_recent_signals(
            min_confidence=config.CONFIDENCE_THRESHOLD,
            asset_types=["stock"],
            max_age_minutes=_stock_window_minutes(),
        )
    if config.CRYPTO_ENABLED:
        candidates += get_recent_signals(
            min_confidence=config.CONFIDENCE_THRESHOLD,
            asset_types=["crypto"],
            max_age_minutes=config.SIGNAL_MAX_AGE_MINUTES,
        )
    # WATCH signals are informational — in v1 a high-confidence WATCH could
    # fall through execute_signal's branches and place a live order
    actionable = [s for s in candidates if s["action"] in ("BUY", "SELL")]
    if not actionable:
        return

    account = get_account()
    if not account:
        logger.warning("Cannot process signals — account unreachable")
        return

    # Pull live position state once — used for risk checks and position limit
    open_positions = get_open_positions()
    unrealized_pnl = sum(p["unrealized_pnl"] for p in open_positions)
    open_count = len(open_positions)
    daily_pnl = account.get("pnl_today", 0.0)

    global _risk_block_reason
    allowed, reason = check_trade_allowed(
        account["cash"],
        unrealized_pnl=unrealized_pnl,
        daily_pnl=daily_pnl,
    )
    if not allowed:
        logger.info(f"Trade blocked: {reason}")
        # Notify once per distinct reason, not every 30s while the limit holds
        if reason != _risk_block_reason:
            _risk_block_reason = reason
            send_sync_notification(f"🛡 *Risk limit active — no new trades*\n_{reason}_")
        return
    _risk_block_reason = None

    # Rank the whole batch, best first; keep only the strongest signal per ticker
    ranked, seen = [], set()
    for s in sorted(actionable, key=_rank_key, reverse=True):
        key = normalize_symbol(s["ticker"])
        if key not in seen:
            seen.add(key)
            ranked.append(s)

    slots = max(config.MAX_OPEN_POSITIONS - open_count, 0)
    for signal in ranked:
        # SELLs always run — they close positions and free a slot
        if signal["action"] == "SELL":
            if execute_signal(signal, account):
                slots = min(slots + 1, config.MAX_OPEN_POSITIONS)
            continue
        if slots <= 0:
            logger.info(
                f"Position limit: {config.MAX_OPEN_POSITIONS} slots full — "
                f"skipping BUY {signal['ticker']} (conf {signal['confidence']:.0%})"
            )
            continue
        if execute_signal(signal, account):
            slots -= 1


def execute_signal(signal: dict, account: dict) -> bool:
    """Returns True if a real trade was placed, False if signal was skipped.

    Serialized by _exec_lock — the watcher loop and the /audit endpoint can
    both land here, and without the lock they could race past the position
    limit together.
    """
    with _exec_lock:
        return _execute_signal_locked(signal, account)


def _execute_signal_locked(signal: dict, account: dict) -> bool:
    ticker = signal["ticker"]
    side = signal["action"]
    asset_type = signal.get("asset_type", "stock")

    if asset_type == "crypto" and not is_crypto_tradable(ticker):
        logger.info(f"{ticker} not tradable on Alpaca crypto — skipping")
        with get_conn() as conn:
            conn.execute("UPDATE signals SET executed=1 WHERE id=?", (signal["id"],))
        return False

    open_positions = get_open_positions()
    existing = next(
        (p for p in open_positions if normalize_symbol(p["ticker"]) == normalize_symbol(ticker)),
        None,
    )

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
        cancel_open_orders(existing["ticker"])  # resting stop/target legs hold the shares
        result = close_position(existing["ticker"])
        if "error" in result:
            logger.error(f"Close failed {ticker}: {result['error']}")
            # Keep retrying every cycle (we WANT the close to happen) but only
            # ping Telegram once per signal
            if signal["id"] not in _notified_failures:
                _notified_failures.add(signal["id"])
                send_sync_notification(f"❌ *Close failed*: {ticker}\n_{result['error']}_")
            return False

        close_price = result.get("fill_price") or existing["current_price"]
        pnl = (close_price - existing["avg_entry"]) * existing["qty"]
        is_win = pnl >= 0
        now_utc = datetime.now(timezone.utc).isoformat()
        trade_date = datetime.now(timezone.utc).date().isoformat()

        with get_conn() as conn:
            conn.execute("UPDATE signals SET executed=1 WHERE id=?", (signal["id"],))
            conn.execute("""
                INSERT INTO trades
                  (signal_id, order_id, fill_price, quantity, executed_at, closed_at, close_price, pnl, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'closed')
            """, (signal["id"], "close", existing["avg_entry"], existing["qty"],
                  now_utc, now_utc, close_price, pnl))
            conn.execute("""
                INSERT INTO daily_stats (trade_date, wins, losses, total_pnl)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    wins      = wins      + excluded.wins,
                    losses    = losses    + excluded.losses,
                    total_pnl = total_pnl + excluded.total_pnl
            """, (trade_date, 1 if is_win else 0, 0 if is_win else 1, pnl))

        outcome = "✅ WIN" if is_win else "❌ LOSS"
        send_sync_notification(
            f"{outcome} *{ticker}* position closed\n"
            f"Entry: ${existing['avg_entry']:.2f} → Exit: ${close_price:.2f}\n"
            f"P&L: ${pnl:+.2f} on {existing['qty']:.4f} shares"
        )
        return True

    # BUY on unowned asset — stocks get bracket legs, crypto gets a bare GTC
    # market order with the position monitor as its stop
    price = get_latest_price(ticker, asset_type)
    if not price:
        logger.error(f"Cannot get price for {ticker}")
        return False

    stop_price = signal.get("stop_loss") or price * 0.98
    target_price = signal.get("price_target") or price * 1.02

    # Entry drift guard: the signal priced this trade at entry_price. If the
    # market has already run toward the target — or through the stop — the
    # planned R/R no longer exists. Skip and mark handled; the next scan
    # re-issues the setup if it still holds.
    entry_ref = signal.get("entry_price")
    if entry_ref:
        risk_dist = abs(entry_ref - stop_price)
        if risk_dist > 0:
            drift_reason = None
            if price <= stop_price:
                drift_reason = f"price ${price:.2f} already through stop ${stop_price:.2f}"
            elif price - entry_ref > 0.5 * risk_dist:
                drift_reason = (
                    f"price ran +${price - entry_ref:.2f} from planned entry "
                    f"${entry_ref:.2f} (max chase: half the ${risk_dist:.2f} risk distance)"
                )
            if drift_reason:
                logger.info(f"Drift guard: skipping {ticker} — {drift_reason}")
                with get_conn() as conn:
                    conn.execute("UPDATE signals SET executed=1 WHERE id=?", (signal["id"],))
                return False

    from executor.gateway.alpaca import calculate_position_size as alpaca_size
    qty = alpaca_size(price, stop_price, asset_type)

    if qty <= 0:
        logger.warning(f"Position size too small for {ticker} at ${price}")
        return False

    result = place_order(ticker, side, qty, stop_price, take_profit_price=target_price,
                         asset_type=asset_type)

    if "error" in result:
        logger.error(f"Order failed: {result['error']}")
        # Mark handled — a rejected order retrying every 30s until expiry means
        # ~30 Telegram pings for one failure. The next scan re-issues the setup.
        with get_conn() as conn:
            conn.execute("UPDATE signals SET executed=1 WHERE id=?", (signal["id"],))
        send_sync_notification(f"❌ *Trade failed*: {ticker} {side}\n_{result['error']}_")
        return False

    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET executed=1 WHERE id=?",
            (signal["id"],)
        )
        conn.execute("""
            INSERT INTO trades (signal_id, order_id, fill_price, quantity, executed_at, status)
            VALUES (?, ?, ?, ?, ?, 'open')
        """, (signal["id"], result["order_id"], price, qty, datetime.now(timezone.utc).isoformat()))

        trade_date = datetime.now(timezone.utc).date().isoformat()
        conn.execute("""
            INSERT INTO daily_stats (trade_date, signals_executed)
            VALUES (?, 1)
            ON CONFLICT(trade_date) DO UPDATE SET signals_executed = signals_executed + 1
        """, (trade_date,))

    trades_left = config.MAX_TRADES_PER_WEEK - get_weekly_trade_count()
    send_sync_notification(
        f"✅ *Trade Executed*\n\n"
        f"{side} {qty:.2f} shares of *{ticker}*\n"
        f"Entry: ${price:.2f} | Stop: ${stop_price:.2f} | Target: ${target_price:.2f}\n"
        f"Confidence: {signal['confidence']:.0%}\n"
        f"Trades remaining this week: {trades_left}\n\n"
        f"_{signal['reasoning'][:120]}_"
    )
    logger.info(f"Executed: {side} {qty} {ticker} @ ${price} stop=${stop_price:.2f} target=${target_price:.2f}")
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
        open_positions = get_open_positions()
        unrealized_pnl = sum(p["unrealized_pnl"] for p in open_positions)
        daily_pnl = account.get("pnl_today", 0.0)
        allowed, reason = check_trade_allowed(account.get("cash", 0), unrealized_pnl=unrealized_pnl, daily_pnl=daily_pnl)
        if allowed:
            if signal.get("action") == "BUY" and len(open_positions) >= config.MAX_OPEN_POSITIONS:
                result["executed"] = False
                result["veto_reason"] = f"Position limit: {len(open_positions)}/{config.MAX_OPEN_POSITIONS} open"
            else:
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
