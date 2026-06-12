import logging
import threading
import time as time_module
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.config import config
from shared.database import init_db, get_todays_signals
from analyst.signals.scorer import run_scan, is_market_hours

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    t = threading.Thread(target=scan_loop, daemon=True)
    t.start()
    yield


app = FastAPI(title="Argus Analyst", lifespan=lifespan)


def scan_loop():
    """
    Runs a market scan every 30 minutes during market hours.
    Outside market hours, checks every 5 minutes and waits.
    """
    while True:
        if is_market_hours():
            try:
                run_scan()
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
            time_module.sleep(1800)  # 30 minutes
        else:
            time_module.sleep(300)   # 5 minutes outside hours


@app.get("/status")
def status():
    signals = get_todays_signals(min_confidence=0.60)
    return {
        "market_hours": is_market_hours(),
        "signals_today": len(signals),
        "pending_signals": [
            {
                "ticker": s["ticker"],
                "action": s["action"],
                "confidence": s["confidence"],
                "reasoning": s["reasoning"],
                "executed": bool(s["executed"]),
            }
            for s in signals
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("analyst.main:app", host="0.0.0.0", port=config.ANALYST_PORT, reload=False)
