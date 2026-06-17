import logging
import secrets
import threading
import time as time_module
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from shared.config import config
from shared.database import init_db, get_todays_signals
from analyst.signals.scorer import run_scan, run_extended_scan, is_market_hours, is_premarket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    t = threading.Thread(target=scan_loop, daemon=True)
    t.start()
    yield


app = FastAPI(title="Argus Analyst Agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

_bearer = HTTPBearer()

def _require_internal(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    if not secrets.compare_digest(credentials.credentials, config.MASTER_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")


_ET = ZoneInfo("America/New_York")


def scan_loop():
    """
    Argus never sleeps. Scans run 24/7 — stocks, crypto, forex, metals.

    Frequencies by session (ET):
    - Pre-market  07:00–09:30  →  stocks (full universe) + extended, every 30 min
    - Market      09:30–16:00  →  stocks (core universe) + extended, every 15 min
    - After-hours 16:00–20:00  →  stocks (core) + extended, every 30 min
    - Overnight   20:00–07:00  →  extended only (crypto/forex/metals), every 60 min

    Dedup: stocks skip if scored within 4 h; crypto/forex/metals skip if within 2 h.
    Execution stays gated to market hours in the executor.
    """
    while True:
        try:
            now = datetime.now(_ET)
            hour = now.hour
            weekday = now.weekday()  # 0=Mon … 6=Sun

            if 7 <= hour < 9 or (hour == 9 and now.minute < 30):
                # Pre-market
                session = "pre-market"
                run_scan(full_universe=True)
                run_extended_scan()
                interval = 1800

            elif is_market_hours():
                # Core trading session
                session = "market"
                run_scan(full_universe=False)
                run_extended_scan()
                interval = 900

            elif 16 <= hour < 20 and weekday < 5:
                # After-hours (stocks still have extended quotes)
                session = "after-hours"
                run_scan(full_universe=False)
                run_extended_scan()
                interval = 1800

            else:
                # Overnight — crypto and forex never close
                session = "overnight"
                run_extended_scan()
                interval = 3600

            logger.info(f"[{session}] scan cycle complete — next in {interval//60} min")

        except Exception as e:
            logger.error(f"Scan loop error: {e}")
            interval = 120

        time_module.sleep(interval)


@app.get("/status", dependencies=[Depends(_require_internal)])
def status():
    signals = get_todays_signals(min_confidence=0.60)
    actionable = [s for s in signals if s["confidence"] >= config.CONFIDENCE_THRESHOLD]
    return {
        "market_hours": is_market_hours(),
        "premarket": is_premarket(),
        "signals_today": len(signals),
        "actionable": len(actionable),
        "pending_signals": [
            {
                "ticker": s["ticker"],
                "action": s["action"],
                "confidence": round(s["confidence"], 3),
                "price_target": s["price_target"],
                "stop_loss": s["stop_loss"],
                "reasoning": s["reasoning"],
                "executed": bool(s["executed"]),
            }
            for s in signals
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "analyst.main:app",
        host="127.0.0.1",
        port=config.ANALYST_PORT,
        reload=False,
        log_level="info"
    )
