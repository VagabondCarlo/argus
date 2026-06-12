import logging
import threading
import time as time_module
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.config import config
from shared.database import init_db, get_todays_signals
from analyst.signals.scorer import run_scan, is_market_hours, is_premarket

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


app = FastAPI(title="Argus Analyst Agent", lifespan=lifespan)


def scan_loop():
    """
    Scan schedule:
    - Pre-market (7:00-9:30 AM ET): Full universe scan once to build the day's watchlist
    - Market hours (9:30 AM-4:00 PM ET): Core universe scan every 30 minutes
    - After hours: Sleep, wait for next session
    """
    pre_market_done = False

    while True:
        try:
            if is_premarket() and not pre_market_done:
                logger.info("Pre-market session — running full universe scan")
                run_scan(full_universe=True)
                pre_market_done = True
                time_module.sleep(600)

            elif is_market_hours():
                pre_market_done = False
                logger.info("Market hours — running core universe scan")
                run_scan(full_universe=False)
                time_module.sleep(1800)  # 30 minutes

            else:
                # Outside trading hours — reset flag for next day
                pre_market_done = False
                time_module.sleep(300)

        except Exception as e:
            logger.error(f"Scan loop error: {e}")
            time_module.sleep(60)


@app.get("/status")
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
        host="0.0.0.0",
        port=config.ANALYST_PORT,
        reload=False,
        log_level="info"
    )
