import ollama
import json
import logging
import re

logger = logging.getLogger(__name__)

MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """You are Marcus Reed — a 20-year institutional trading veteran running an AI-powered
analysis desk. Before every trade decision, you run it through a three-committee framework
inspired by the greatest investment philosophies in history. All three must agree before you act.

━━━ COMMITTEE MEMBER 1: FUNDAMENTAL QUALITY FILTER ━━━
Ask: Is this a quality business or just a chart pattern on a weak company?
- Only act on businesses with durable competitive advantages (moats)
- Demand a margin of safety — enter at fear, not at greed
- If the crowd is euphoric about this stock, that is your warning sign
- Circle of competence: if the business model is unclear, the answer is HOLD
- A great technical setup on a fundamentally weak business is still a trap

━━━ COMMITTEE MEMBER 2: MACRO REGIME FILTER ━━━
Ask: Is this trade aligned with the economic cycle and the dominant macro force?
- Understand the cycle: is credit expanding or contracting? Is the Fed tightening or easing?
- Align with the machine, not against it — don't fight the tape
- If a sector is breaking down, don't catch falling knives
- Risk is highest when it feels lowest
- The broad market (SPY) is your macro proxy — respect its direction above all else
- In a bullish regime: lean into momentum. In a bearish regime: raise the bar dramatically

━━━ COMMITTEE MEMBER 3: TECHNICAL EXECUTION FILTER ━━━
Ask: Is the technical setup clean enough to execute with precision?
- Risk/reward must be at least 2:1. No exceptions.
- Volume must confirm the move — price without volume is noise, not signal
- Never chase. If the move already happened, wait for the next setup
- Know the difference between a real breakout and a bull trap
- The entry must be precise — a good idea at a bad price is a bad trade

━━━ THE THREE-COMMITTEE RULE ━━━
To score confidence above 0.75, ALL THREE must give a green light:
  ✅ Fundamental: Quality business, entry at a margin of safety, not peak greed
  ✅ Macro: Regime and cycle support this trade direction
  ✅ Technical: Setup is clean, R/R ≥ 2:1, volume confirms

If ANY ONE vetoes, confidence caps at 0.65 regardless of the other two.
If ALL THREE align in a strong bullish regime, you may push confidence toward 0.90.
This is how Autopilot works — attach to what is already working and let it run.

You respond ONLY with valid JSON. No prose outside the JSON block.
Below 0.60 is always HOLD — never force a trade.
"""

SIGNAL_PROMPT = """Run this ticker through the three-committee framework and give your verdict.

TICKER: {ticker}
CURRENT PRICE: ${price}
TODAY'S MOVE: {price_change_pct}% | Volume: {volume_ratio}x normal

TECHNICAL PICTURE:
- RSI (14): {rsi}  {rsi_context}
- MACD Cross: {macd_cross} | MACD Diff: {macd_diff}
- Bollinger Band position: {bb_pct_label} ({bb_pct})
- EMA 9 vs EMA 21: {ema_trend}
- Volume vs 20-day avg: {volume_ratio}x

MACRO CONTEXT:
- SPY today: {spy_change}%
- Market regime: {market_regime}

FUNDAMENTAL & INSIDER INTELLIGENCE:
{enrichment}

NEWS & CATALYSTS:
{news}

COMMITTEE CHECKLIST before scoring above 0.75:
  Fundamental filter — Quality business at a fair/fearful price? Insiders buying or selling?
  Macro filter      — Does the regime and SPY direction support this trade?
  Technical filter  — Is R/R ≥ 2:1 with volume confirmation and a clean entry?

Hard stops — these auto-veto a BUY signal:
- RSI > 75 (overbought — do not chase)
- Volume ratio < 1.3 (no confirmation)
- SPY down > 1% and this is a BUY (don't fight the tape)
- RSI < 25 on a SHORT (oversold — wait for confirmation)
- Negative news on a BUY reduces confidence by at least 0.10
- Earnings within 7 days — cap confidence at 0.65 (binary risk event)

Return ONLY this JSON, nothing else:
{{
  "action": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0 to 1.0,
  "setup_type": "breakout" or "reversal" or "momentum" or "gap_fill" or "value_entry" or "none",
  "price_target": float,
  "stop_loss": float,
  "risk_reward": float,
  "time_horizon": "intraday" or "1-2 days" or "2-3 days",
  "reasoning": "3 sentences: one per committee member — what Buffett, Dalio, and Reed each say about this setup.",
  "red_flags": "Any committee veto or concern, or 'none'"
}}
"""


def get_spy_context() -> tuple[float, str]:
    """Get SPY's current daily change for market regime context."""
    try:
        import yfinance as yf
        import pandas as pd
        spy = yf.download("SPY", period="2d", interval="1d",
                          progress=False, auto_adjust=True)
        if len(spy) >= 2:
            # Flatten MultiIndex if yfinance returns ("Close", "SPY") tuple columns
            close_col = spy["Close"]
            if isinstance(close_col, pd.DataFrame):
                close_col = close_col.iloc[:, 0]
            prev = float(close_col.iloc[-2])
            last = float(close_col.iloc[-1])
            change = (last - prev) / prev * 100
            if change > 1.0:
                regime = "bullish — broad market trending up"
            elif change < -1.0:
                regime = "bearish — broad market under pressure"
            else:
                regime = "neutral — choppy, mixed signals"
            return round(change, 2), regime
    except Exception:
        pass
    return 0.0, "neutral — market data unavailable"


def analyze_ticker(snapshot: dict, news_text: str, spy_change: float = 0.0, market_regime: str = "unknown", enrichment_text: str = "") -> dict | None:
    """
    Send a ticker snapshot + news + enrichment data to the three-committee LLM.
    enrichment_text contains insider activity, analyst consensus, earnings proximity, short interest.
    Returns a structured signal dict, or None on failure.
    """
    rsi = snapshot["rsi"]
    bb_pct = snapshot.get("bb_pct", 0.5)

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
        enrichment=enrichment_text or "No enrichment data available.",
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
        if signal.get("price_target") is None or signal.get("stop_loss") is None:
            logger.warning(f"LLM returned null levels for {snapshot['ticker']}, skipping")
            return None
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
