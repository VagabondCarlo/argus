import ollama
import json
import logging
import re

logger = logging.getLogger(__name__)

MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """You are Argus, an expert quantitative trading analyst.
You analyze technical indicators and news to generate precise, data-driven trade signals.
You respond ONLY with valid JSON. No explanations outside the JSON block.
Be conservative — only recommend trades with genuine edge. When uncertain, return HOLD."""

SIGNAL_PROMPT = """Analyze this ticker and return a trade signal as JSON.

TICKER: {ticker}
CURRENT PRICE: ${price}

TECHNICAL INDICATORS:
- RSI (14): {rsi} {rsi_note}
- MACD Cross: {macd_cross}
- MACD Diff: {macd_diff}
- Bollinger Band %: {bb_pct} {bb_note}
- Volume vs 20d avg: {volume_ratio}x
- EMA Trend (9 vs 21): {ema_trend}
- Price change today: {price_change_pct}%

RECENT NEWS:
{news}

Return this exact JSON structure:
{{
  "action": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0 to 1.0,
  "price_target": float (realistic 1-3 day target),
  "stop_loss": float (max loss price),
  "reasoning": "2-3 sentence explanation citing specific indicators and news"
}}

Rules:
- confidence below 0.60 = HOLD
- RSI > 70 = overbought (avoid BUY)
- RSI < 30 = oversold (potential BUY)
- Volume ratio > 1.5 = strong signal confirmation
- Never target more than 3% gain or risk more than 2% loss"""


def analyze_ticker(snapshot: dict, news_text: str) -> dict | None:
    """
    Feed a ticker snapshot + news to the local LLM and return a structured signal.
    Returns None if the model fails or returns malformed output.
    """
    rsi = snapshot["rsi"]
    bb_pct = snapshot["bb_pct"]

    rsi_note = "(overbought)" if rsi > 70 else "(oversold)" if rsi < 30 else "(neutral)"
    bb_note = "(near upper band)" if bb_pct > 0.8 else "(near lower band)" if bb_pct < 0.2 else "(mid range)"

    prompt = SIGNAL_PROMPT.format(
        ticker=snapshot["ticker"],
        price=snapshot["price"],
        rsi=rsi,
        rsi_note=rsi_note,
        macd_cross=snapshot["macd_cross"],
        macd_diff=snapshot["macd_diff"],
        bb_pct=bb_pct,
        bb_note=bb_note,
        volume_ratio=snapshot["volume_ratio"],
        ema_trend=snapshot["ema_trend"],
        price_change_pct=snapshot["price_change_pct"],
        news=news_text,
    )

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.1}
        )
        raw = response["message"]["content"].strip()

        # Extract JSON from response
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logger.warning(f"No JSON found in LLM response for {snapshot['ticker']}")
            return None

        signal = json.loads(json_match.group())

        # Validate required fields
        required = ["action", "confidence", "price_target", "stop_loss", "reasoning"]
        if not all(k in signal for k in required):
            logger.warning(f"Missing fields in LLM response for {snapshot['ticker']}")
            return None

        signal["confidence"] = max(0.0, min(1.0, float(signal["confidence"])))
        signal["ticker"] = snapshot["ticker"]
        return signal

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {snapshot['ticker']}: {e}")
        return None
    except Exception as e:
        logger.error(f"LLM analysis failed for {snapshot['ticker']}: {e}")
        return None
