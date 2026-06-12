import yfinance as yf
import pandas as pd
import ta
import logging

logger = logging.getLogger(__name__)

WATCHLIST = [
    "AAPL", "TSLA", "NVDA", "MSFT", "AMD",
    "META", "GOOGL", "AMZN", "SPY", "QQQ"
]


def fetch_historical(ticker: str, period: str = "30d", interval: str = "1d") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as e:
        logger.error(f"Failed to fetch {ticker}: {e}")
        return None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI, MACD, Bollinger Bands, and volume trend to dataframe."""
    df = df.copy()
    close = df["close"]
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

    return df.dropna()


def get_market_snapshot(ticker: str) -> dict | None:
    """Returns latest technical indicators for a ticker."""
    df = fetch_historical(ticker)
    if df is None or len(df) < 21:
        return None

    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "ticker": ticker,
        "price": round(float(latest["close"]), 2),
        "rsi": round(float(latest["rsi"]), 2),
        "macd_diff": round(float(latest["macd_diff"]), 4),
        "macd_cross": "bullish" if latest["macd_diff"] > 0 > prev["macd_diff"] else
                      "bearish" if latest["macd_diff"] < 0 < prev["macd_diff"] else "neutral",
        "bb_pct": round(float(latest["bb_pct"]), 3),
        "volume_ratio": round(float(latest["volume_ratio"]), 2),
        "ema_trend": "up" if latest["ema_9"] > latest["ema_21"] else "down",
        "price_change_pct": round(
            (float(latest["close"]) - float(prev["close"])) / float(prev["close"]) * 100, 2
        ),
    }


def scan_watchlist() -> list[dict]:
    """Scan all tickers and return snapshots."""
    results = []
    for ticker in WATCHLIST:
        snap = get_market_snapshot(ticker)
        if snap:
            results.append(snap)
    return results
