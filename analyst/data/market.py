import yfinance as yf
import pandas as pd
import ta
import logging
import os
import time

logger = logging.getLogger(__name__)

# yfinance logs "possibly delisted; no price data" at ERROR for what are just
# intermittent empty responses under concurrency — silence that misleading noise;
# fetch_historical handles real failures with retries below.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

WATCHLIST = [
    "AAPL", "TSLA", "NVDA", "MSFT", "AMD",
    "META", "GOOGL", "AMZN", "SPY", "QQQ"
]

_alpaca_client = None

def _get_alpaca_data_client():
    global _alpaca_client
    if _alpaca_client is None:
        try:
            from alpaca.data.live import StockDataStream
            from alpaca.data.historical import StockHistoricalDataClient
            key = os.getenv("ALPACA_API_KEY")
            secret = os.getenv("ALPACA_SECRET_KEY")
            if key and secret:
                _alpaca_client = StockHistoricalDataClient(key, secret)
        except Exception as e:
            logger.debug(f"Alpaca data client init failed: {e}")
    return _alpaca_client


def get_realtime_price(ticker: str) -> float | None:
    client = _get_alpaca_data_client()
    if not client:
        return None
    try:
        from alpaca.data.requests import StockLatestQuoteRequest
        req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
        quotes = client.get_stock_latest_quote(req)
        if ticker in quotes:
            q = quotes[ticker]
            mid = (float(q.ask_price) + float(q.bid_price)) / 2
            return round(mid, 2) if mid > 0 else None
    except Exception as e:
        logger.debug(f"Alpaca quote failed for {ticker}: {e}")
    return None


def fetch_historical(ticker: str, period: str = "90d", interval: str = "1d",
                     retries: int = 3) -> pd.DataFrame | None:
    """Fetch OHLCV with retry. yfinance intermittently returns an empty frame
    for a live ticker under concurrent load; a short backoff-and-retry recovers
    it, so one flaky response no longer drops the ticker for the whole scan."""
    for attempt in range(retries):
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0].lower() for col in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                return df
        except Exception as e:
            logger.warning(f"fetch {ticker} attempt {attempt + 1}/{retries}: {e}")
        if attempt < retries - 1:
            time.sleep(0.6 * (attempt + 1))  # 0.6s, 1.2s backoff
    logger.warning(f"fetch {ticker}: no data after {retries} attempts (skipping this cycle)")
    return None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()

    macd = ta.trend.MACD(close)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_diff"] = macd.macd_diff()

    bb = ta.volatility.BollingerBands(close, window=20)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_pct"] = bb.bollinger_pband()

    df["volume_sma"] = volume.rolling(window=20).mean()
    df["volume_ratio"] = volume / df["volume_sma"]

    df["ema_9"] = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    df["ema_21"] = ta.trend.EMAIndicator(close, window=21).ema_indicator()

    atr = ta.volatility.AverageTrueRange(high, low, close, window=14)
    df["atr"] = atr.average_true_range()

    return df.dropna()


def get_market_snapshot(ticker: str) -> dict | None:
    df = fetch_historical(ticker)
    if df is None or len(df) < 21:
        return None

    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    live_price = get_realtime_price(ticker)
    price = live_price if live_price else round(float(latest["close"]), 2)
    price_source = "alpaca_realtime" if live_price else "yfinance_delayed"

    atr = round(float(latest["atr"]), 4)
    atr_pct = round(atr / price * 100, 2) if price > 0 else 0

    return {
        "ticker": ticker,
        "price": price,
        "price_source": price_source,
        "rsi": round(float(latest["rsi"]), 2),
        "macd_diff": round(float(latest["macd_diff"]), 4),
        "macd_cross": "bullish" if latest["macd_diff"] > 0 > prev["macd_diff"] else
                      "bearish" if latest["macd_diff"] < 0 < prev["macd_diff"] else "neutral",
        "bb_pct": round(float(latest["bb_pct"]), 3),
        "volume_ratio": round(float(latest["volume_ratio"]), 2),
        "ema_trend": "up" if latest["ema_9"] > latest["ema_21"] else "down",
        "price_change_pct": round(
            (price - float(prev["close"])) / float(prev["close"]) * 100, 2
        ),
        "atr": atr,
        "atr_pct": atr_pct,
    }


def scan_watchlist() -> list[dict]:
    results = []
    for ticker in WATCHLIST:
        snap = get_market_snapshot(ticker)
        if snap:
            results.append(snap)
    return results
