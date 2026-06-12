import ollama
import json
import logging
import re

logger = logging.getLogger(__name__)

MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """You are Marcus Reed, a 20-year institutional trading veteran who ran a proprietary
desk at a tier-1 brokerage. You managed millions in capital, survived the 2008 crash, the 2020
COVID collapse, and every choppy market in between. You have an extraordinary discipline: you
pass on 95% of setups because you know that protecting capital is the only way to stay in the game
long-term. You only recommend a trade when the setup is so clean it practically speaks for itself.

Your rules, non-negotiable:
1. Risk/reward must be at least 2:1. If the target isn't at least 2x the stop distance, you pass.
2. Volume must confirm the move. Price action without volume is noise.
3. You never chase. If the move already happened, you wait for the next setup.
4. You know the difference between a real breakout and a false one.
5. You factor in what the broad market (SPY) is doing. Swimming against the tide kills accounts.
6. You are brutally honest. You would rather say HOLD 100 times than put someone in a bad trade.
7. You think in terms of probability and edge. No edge = no trade.

You respond ONLY with valid JSON. No prose outside the JSON block.
A confidence score above 0.75 means you would put real capital on this trade right now.
Below 0.60 is always HOLD — never force a trade.
"""

SIGNAL_PROMPT = """Analyze this trade setup and give me your honest assessment.

TICKER: {ticker}
CURRENT PRICE: ${price}
TODAY'S MOVE: {price_change_pct}% | Volume: {volume_ratio}x normal

TECHNICAL PICTURE:
- RSI (14): {rsi}  {rsi_context}
- MACD Cross: {macd_cross} | MACD Diff: {macd_diff}
- Bollinger Band position: {bb_pct_label} ({bb_pct})
- EMA 9 vs EMA 21: {ema_trend}
- Volume vs 20-day avg: {volume_ratio}x

BROAD MARKET CONTEXT:
- SPY today: {spy_change}%
- Market regime: {market_regime}

RECENT NEWS & CATALYSTS:
{news}

Give me your read. Return this exact JSON:
{{
  "action": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0 to 1.0,
  "setup_type": "breakout" or "reversal" or "momentum" or "gap_fill" or "none",
  "price_target": float,
  "stop_loss": float,
  "risk_reward": float,
  "time_horizon": "intraday" or "1-2 days" or "2-3 days",
  "reasoning": "2-3 sentences. Cite the specific indicators and why THIS setup has edge.",
  "red_flags": "Any concerns, or 'none'"
}}

Hard rules before you score above 0.75:
- risk_reward must be >= 2.0
- volume_ratio should be >= 1.3 for entries
- Do not go against SPY trend unless the setup is exceptional
- RSI > 75 = do not BUY. RSI < 25 = do not SHORT.
- If news is negative for a BUY setup, lower confidence by at least 0.10
"""


def get_spy_context() -> tuple[float, str]:
    """Get SPY's current daily change for market regime context."""
    try:
        import yfinance as yf
        spy = yf.download("SPY", period="2d", interval="1d",
                          progress=False, auto_adjust=True)
        if len(spy) >= 2:
            change = float(
                (spy["Close"].iloc[-1] - spy["Close"].iloc[-2]) / spy["Close"].iloc[-2] * 100
            )
            if change > 1.0:
                regime = "bullish — broad market trending up"
            elif change < -1.0:
                regime = "bearish — broad market under pressure"
            else:
                regime = "neutral — choppy, mixed signals"
            return round(change, 2), regime
    except Exception:
        pass
    return 0.0, "unknown"


def analyze_ticker(snapshot: dict, news_text: str) -> dict | None:
    """
    Send a ticker snapshot + news to Marcus Reed (the veteran LLM persona).
    Returns a structured signal dict, or None on failure.
    """
    rsi = snapshot["rsi"]
    bb_pct = snapshot.get("bb_pct", 0.5)
    spy_change, market_regime = get_spy_context()

    rsi_context = (
        "⚠️ OVERBOUGHT — avoid new longs" if rsi > 75 else
        "🔻 OVERSOLD — potential bounce" if rsi < 25 else
        "elevated, watch for exhaustion" if rsi > 65 else
        "depressed, watch for reversal" if rsi < 35 else
        "neutral range"
    )

    bb_pct_label = (
        "near upper band — extended" if bb_pct > 0.80 else
        "near lower band — oversold" if bb_pct < 0.20 else
        "mid-band — no edge from bands"
    )

    prompt = SIGNAL_PROMPT.format(
        ticker=snapshot["ticker"],
        price=snapshot["price"],
        price_change_pct=snapshot["price_change_pct"],
        volume_ratio=snapshot["volume_ratio"],
        rsi=rsi,
        rsi_context=rsi_context,
        macd_cross=snapshot["macd_cross"],
        macd_diff=snapshot["macd_diff"],
        bb_pct=bb_pct,
        bb_pct_label=bb_pct_label,
        ema_trend=snapshot["ema_trend"],
        spy_change=spy_change,
        market_regime=market_regime,
        news=news_text,
    )

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.05}  # Near-deterministic — veterans don't guess
        )
        raw = response["message"]["content"].strip()

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logger.warning(f"No JSON in LLM response for {snapshot['ticker']}")
            return None

        signal = json.loads(json_match.group())

        required = ["action", "confidence", "price_target", "stop_loss", "reasoning"]
        if not all(k in signal for k in required):
            logger.warning(f"Missing fields in LLM response for {snapshot['ticker']}")
            return None

        # Enforce risk/reward check — don't trust the model alone
        price = snapshot["price"]
        target = float(signal["price_target"])
        stop = float(signal["stop_loss"])
        action = signal["action"]

        if action == "BUY" and target > price and stop < price:
            rr = (target - price) / (price - stop) if (price - stop) > 0 else 0
        elif action == "SELL" and target < price and stop > price:
            rr = (price - target) / (stop - price) if (stop - price) > 0 else 0
        else:
            rr = 0

        signal["risk_reward"] = round(rr, 2)
        signal["confidence"] = max(0.0, min(1.0, float(signal["confidence"])))

        # Hard override: if R/R < 1.5, cap confidence at 0.65
        if rr < 1.5 and signal["action"] != "HOLD":
            signal["confidence"] = min(signal["confidence"], 0.65)
            signal["red_flags"] = signal.get("red_flags", "") + " | R/R below 1.5 — confidence capped"

        signal["ticker"] = snapshot["ticker"]
        signal["spy_change"] = spy_change
        return signal

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {snapshot['ticker']}: {e}")
        return None
    except Exception as e:
        logger.error(f"LLM analysis failed for {snapshot['ticker']}: {e}")
        return None
