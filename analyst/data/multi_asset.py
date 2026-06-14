"""
Market snapshots for non-equity assets: forex, precious metals, crypto.
Same technical indicators as equities, with volume handling for FX pairs
where volume data is unreliable.
"""

import logging
import yfinance as yf
import pandas as pd
import ta

from analyst.data.universe_extended import FOREX_PAIRS, METALS_PAIRS, CRYPTO_PAIRS

logger = logging.getLogger(__name__)


def _fetch_ohlcv(ticker: str, period: str = "60d", interval: str = "1d") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 22:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as e:
        logger.debug(f"Failed to fetch {ticker}: {e}")
        return None


def _add_indicators(df: pd.DataFrame, has_volume: bool = True) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]

    df["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()

    macd = ta.trend.MACD(close)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_diff"] = macd.macd_diff()

    bb = ta.volatility.BollingerBands(close, window=20)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_pct"] = bb.bollinger_pband()

    df["ema_9"] = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    df["ema_21"] = ta.trend.EMAIndicator(close, window=21).ema_indicator()

    if has_volume and "volume" in df.columns:
        vol = df["volume"].replace(0, pd.NA)
        df["volume_sma"] = vol.rolling(window=20).mean()
        df["volume_ratio"] = (vol / df["volume_sma"]).fillna(1.0)
    else:
        df["volume_ratio"] = 1.0

    return df.dropna()


def get_extended_snapshot(ticker: str, display_name: str, asset_type: str) -> dict | None:
    """
    Returns a technical snapshot for forex, metals, or crypto tickers.
    asset_type: 'forex' | 'metal' | 'crypto'
    """
    has_volume = asset_type in ("metal", "crypto")
    df = _fetch_ohlcv(ticker)
    if df is None:
        return None

    df = _add_indicators(df, has_volume=has_volume)
    if len(df) < 2:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    macd_cross = (
        "bullish" if latest["macd_diff"] > 0 > prev["macd_diff"] else
        "bearish" if latest["macd_diff"] < 0 < prev["macd_diff"] else
        "neutral"
    )

    price_change_pct = round(
        (float(latest["close"]) - float(prev["close"])) / float(prev["close"]) * 100, 4
    )

    return {
        "ticker": ticker,
        "display_name": display_name,
        "asset_type": asset_type,
        "price": round(float(latest["close"]), 6 if asset_type == "forex" else 2),
        "rsi": round(float(latest["rsi"]), 2),
        "macd_diff": round(float(latest["macd_diff"]), 6),
        "macd_cross": macd_cross,
        "bb_pct": round(float(latest["bb_pct"]), 3),
        "volume_ratio": round(float(latest["volume_ratio"]), 2),
        "ema_trend": "up" if latest["ema_9"] > latest["ema_21"] else "down",
        "price_change_pct": round(price_change_pct, 4),
    }


def scan_forex() -> list[dict]:
    results = []
    for ticker, name in FOREX_PAIRS.items():
        snap = get_extended_snapshot(ticker, name, "forex")
        if snap:
            results.append(snap)
    return results


def scan_metals() -> list[dict]:
    results = []
    for ticker, name in METALS_PAIRS.items():
        snap = get_extended_snapshot(ticker, name, "metal")
        if snap:
            results.append(snap)
    return results


def scan_crypto() -> list[dict]:
    results = []
    for ticker, name in CRYPTO_PAIRS.items():
        snap = get_extended_snapshot(ticker, name, "crypto")
        if snap:
            results.append(snap)
    return results


def fetch_asset_news(ticker: str) -> str:
    """Best-effort news fetch for non-equity tickers via yfinance."""
    try:
        news = yf.Ticker(ticker).news or []
        if not news:
            return "No specific news found. Use macro context."
        lines = []
        for item in news[:3]:
            title = item.get("title", "")
            if title:
                lines.append(f"- {title}")
        return "\n".join(lines) if lines else "No specific news found."
    except Exception:
        return "News unavailable."
