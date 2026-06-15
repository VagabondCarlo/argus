import yfinance as yf
import pandas as pd
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# ── Screening thresholds ───────────────────────────────────────────────────────
MIN_PRICE = 5.0          # Avoid penny stocks
MAX_PRICE = 1000.0       # Avoid extremely thin fractional setups
MIN_AVG_VOLUME = 500_000 # Minimum daily liquidity
VOLUME_SPIKE = 1.5       # Today's volume must be 1.5x 20-day average
MIN_PRICE_MOVE = 1.5     # At least 1.5% move today (something is happening)
RSI_OVERSOLD = 35        # Below = potential bounce
RSI_OVERBOUGHT = 65      # Above = potential continuation or short
MAX_CANDIDATES = 25      # Max tickers to pass to deep analysis


def _quick_screen(ticker: str) -> dict | None:
    """
    Fast pre-screen for a single ticker.
    Downloads 30 days of data, checks basic criteria.
    Returns a scored dict if the ticker passes, None if it fails.
    """
    try:
        df = yf.download(ticker, period="90d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 20:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        price = float(latest["close"])
        volume_today = float(latest["volume"])
        avg_volume = float(df["volume"].tail(20).mean())

        # Hard filters
        if not (MIN_PRICE <= price <= MAX_PRICE):
            return None
        if avg_volume < MIN_AVG_VOLUME:
            return None

        volume_ratio = volume_today / avg_volume if avg_volume > 0 else 0
        price_change_pct = ((price - float(prev["close"])) / float(prev["close"])) * 100

        # Must have activity
        if volume_ratio < VOLUME_SPIKE and abs(price_change_pct) < MIN_PRICE_MOVE:
            return None

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        # Score: higher = more interesting
        score = 0
        score += min(volume_ratio * 20, 40)         # Volume spike up to 40pts
        score += min(abs(price_change_pct) * 5, 30) # Price move up to 30pts
        if rsi < RSI_OVERSOLD:
            score += 20  # Oversold bounce opportunity
        if rsi > RSI_OVERBOUGHT:
            score += 15  # Momentum continuation
        if volume_ratio > 3:
            score += 10  # Unusual volume bonus

        return {
            "ticker": ticker,
            "price": round(price, 2),
            "price_change_pct": round(price_change_pct, 2),
            "volume_ratio": round(volume_ratio, 2),
            "rsi": round(rsi, 2),
            "score": round(score, 2),
        }

    except Exception:
        return None


def run_prescreen(tickers: list[str], max_workers: int = 20) -> list[dict]:
    """
    Screens the full universe concurrently.
    Returns top MAX_CANDIDATES tickers sorted by score.
    """
    logger.info(f"Pre-screening {len(tickers)} tickers...")
    passed = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_quick_screen, t): t for t in tickers}
        for future in as_completed(futures):
            result = future.result()
            if result:
                passed.append(result)

    passed.sort(key=lambda x: x["score"], reverse=True)
    candidates = passed[:MAX_CANDIDATES]

    logger.info(f"Pre-screen complete: {len(passed)} passed filters, "
                f"top {len(candidates)} selected for deep analysis")
    return candidates


def filter_by_market_regime(candidates: list[dict], spy_change: float) -> list[dict]:
    """
    Adjusts candidate list based on overall market direction.
    In a down market, bias toward short/bearish setups and vice versa.
    """
    if spy_change < -1.5:
        # Bear day: prefer candidates that are down (short setups or bear ETFs)
        logger.info(f"Bear market day (SPY {spy_change:.1f}%) — biasing toward short setups")
        candidates = sorted(candidates, key=lambda x: x["price_change_pct"])
    elif spy_change > 1.5:
        # Bull day: prefer candidates that are up (momentum)
        logger.info(f"Bull market day (SPY {spy_change:.1f}%) — biasing toward long setups")
        candidates = sorted(candidates, key=lambda x: x["price_change_pct"], reverse=True)

    return candidates
