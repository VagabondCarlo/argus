"""
Extended three-committee analyzer for non-equity assets.
Same Buffett/Dalio/Reed framework, adapted for forex, metals, and crypto.
"""

import ollama
import json
import logging
import re

logger = logging.getLogger(__name__)
MODEL = "llama3.1:8b"


EXTENDED_SYSTEM_PROMPT = """You are Marcus Reed — a 20-year institutional trading veteran running a
multi-asset intelligence desk. Every signal goes through the three-committee framework.

━━━ COMMITTEE MEMBER 1: FUNDAMENTAL QUALITY FILTER ━━━
For CURRENCIES: Is there genuine divergence in growth, inflation, or central bank policy that justifies
  this direction? Is the market already pricing it in, or is there still a margin of safety?
For METALS: Is there a real macro case — inflation hedge, safe-haven flow, supply constraint?
  Don't chase a metal after it has already run hard — demand a fair entry.
For CRYPTO: Does this asset have real adoption, network effects, and utility?
  Separate fundamental accumulation from speculative hype. Hype alone is a red flag.
Principle: A strong fundamental thesis is required. Price action without it is gambling.

━━━ COMMITTEE MEMBER 2: MACRO REGIME FILTER ━━━
For ALL assets: What is risk appetite? Where is the dollar (DXY)? What is SPY doing?
For CURRENCIES: Interest rate and growth differentials between the two economies.
  Follow central bank policy divergence — it drives FX more than any other factor.
For METALS: Inflation regime, real yields, and risk-off vs risk-on flows.
  Rising real yields pressure metals. Risk-off demand supports them. Know which you're in.
For CRYPTO: Institutional flow and correlation to risk assets.
  Crypto is high-beta risk. If SPY is bleeding, crypto bleeds harder.
Rule: Align with the dominant macro force. Never fight the machine.

━━━ COMMITTEE MEMBER 3: TECHNICAL EXECUTION FILTER ━━━
RSI, MACD, Bollinger Bands, and EMA apply universally across all asset classes.
Risk/reward must be at least 2:1. No exceptions anywhere.
Volume (where available) must confirm the move.
The entry point must be precise — the right direction at the wrong price is still a loss.

━━━ THE THREE-COMMITTEE RULE ━━━
All three must give green lights for confidence above 0.75.
If any one vetoes, confidence caps at 0.65.
All three aligned in a high-conviction macro setup can push to 0.90.
Below 0.60 is always HOLD — never force a signal.

You respond ONLY with valid JSON. No prose outside the JSON block.
"""

_ASSET_CONTEXT = {
    "forex": (
        "Focus on: central bank policy divergence, interest rate differentials, economic growth gap. "
        "Key: a rising USD weakens EUR/USD and AUD/USD. A hawkish Fed vs dovish ECB = strong USD setup."
    ),
    "metal": (
        "Focus on: real yield direction (inverted relationship with gold), inflation expectations, "
        "dollar strength (inverted vs metals), and risk-off demand. "
        "Gold above $2,000 is structural, not speculation."
    ),
    "crypto": (
        "Focus on: institutional flows, correlation to NASDAQ/risk assets, "
        "on-chain accumulation signals, and whether this is a liquidity-driven or fundamental move. "
        "Bitcoin leads altcoins — confirm BTC direction first."
    ),
}

EXTENDED_SIGNAL_PROMPT = """Run this {asset_type} through the three-committee framework.

ASSET: {display_name} ({ticker})
ASSET CLASS: {asset_type_label}
CURRENT PRICE: {price}
TODAY'S MOVE: {price_change_pct}%
{volume_line}

TECHNICAL PICTURE (Marcus Reed):
- RSI (14): {rsi}  {rsi_context}
- MACD Cross: {macd_cross} | MACD Diff: {macd_diff}
- Bollinger Band position: {bb_pct_label} ({bb_pct})
- EMA 9 vs EMA 21: {ema_trend}

MACRO CONTEXT (Ray Dalio):
- SPY today: {spy_change}%
- Market regime: {market_regime}

ASSET CLASS FRAMEWORK (Buffett + Dalio):
{asset_context}

NEWS & CATALYSTS:
{news}

COMMITTEE CHECKLIST:
  Buffett — Fundamental case clear? Not chasing an already-extended move?
  Dalio   — Macro regime and dollar direction support this trade?
  Reed    — R/R ≥ 2:1? Technical entry precise?

Return ONLY this JSON, nothing else:
{{
  "action": "BUY" or "SELL" or "HOLD",
  "confidence": 0.0 to 1.0,
  "setup_type": "breakout" or "reversal" or "momentum" or "range_fade" or "accumulation" or "none",
  "price_target": float,
  "stop_loss": float,
  "risk_reward": float,
  "time_horizon": "intraday" or "1-3 days" or "1-2 weeks",
  "reasoning": "3 sentences: what Buffett, Dalio, and Reed each say about this specific setup.",
  "red_flags": "Any committee veto or concern, or 'none'"
}}
"""

_ASSET_TYPE_LABELS = {
    "forex": "Currency Pair",
    "metal": "Precious Metal / Commodity",
    "crypto": "Cryptocurrency",
}


def analyze_extended(
    snapshot: dict,
    news_text: str,
    spy_change: float = 0.0,
    market_regime: str = "unknown",
) -> dict | None:
    """
    Run the extended three-committee analysis on a non-equity asset.
    snapshot must include: ticker, display_name, asset_type, price,
    rsi, macd_diff, macd_cross, bb_pct, volume_ratio, ema_trend, price_change_pct
    """
    asset_type = snapshot["asset_type"]
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
        "mid-band — no Bollinger edge"
    )

    vol_ratio = snapshot.get("volume_ratio", 1.0)
    volume_line = (
        f"Volume vs avg: {vol_ratio}x"
        if asset_type != "forex"
        else "Volume: N/A for FX (tick data not meaningful)"
    )

    prompt = EXTENDED_SIGNAL_PROMPT.format(
        asset_type=asset_type,
        asset_type_label=_ASSET_TYPE_LABELS.get(asset_type, asset_type),
        display_name=snapshot["display_name"],
        ticker=snapshot["ticker"],
        price=snapshot["price"],
        price_change_pct=snapshot["price_change_pct"],
        volume_line=volume_line,
        rsi=rsi,
        rsi_context=rsi_context,
        macd_cross=snapshot["macd_cross"],
        macd_diff=snapshot["macd_diff"],
        bb_pct=bb_pct,
        bb_pct_label=bb_pct_label,
        ema_trend=snapshot["ema_trend"],
        spy_change=spy_change,
        market_regime=market_regime,
        asset_context=_ASSET_CONTEXT.get(asset_type, ""),
        news=news_text,
    )

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": EXTENDED_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.05},
        )
        raw = response["message"]["content"].strip()

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logger.warning(f"No JSON in response for {snapshot['ticker']}")
            return None

        signal = json.loads(json_match.group())

        required = ["action", "confidence", "price_target", "stop_loss", "reasoning"]
        if not all(k in signal for k in required):
            logger.warning(f"Missing fields for {snapshot['ticker']}")
            return None

        price = snapshot["price"]
        action = signal["action"]

        if signal.get("price_target") is None or signal.get("stop_loss") is None:
            if action == "BUY":
                signal["price_target"] = round(price * 1.03, 6)
                signal["stop_loss"]    = round(price * 0.99, 6)
            elif action == "SELL":
                signal["price_target"] = round(price * 0.97, 6)
                signal["stop_loss"]    = round(price * 1.01, 6)
            else:
                return None
            logger.info(f"LLM omitted levels for {snapshot['ticker']} — using technical defaults")

        target = float(signal["price_target"])
        stop = float(signal["stop_loss"])

        if action == "BUY" and target > price and stop < price:
            rr = (target - price) / (price - stop) if (price - stop) > 0 else 0
        elif action == "SELL" and target < price and stop > price:
            rr = (price - target) / (stop - price) if (stop - price) > 0 else 0
        else:
            rr = 0

        signal["risk_reward"] = round(rr, 2)
        signal["confidence"] = max(0.0, min(1.0, float(signal["confidence"])))

        if rr < 1.5 and signal["action"] != "HOLD":
            signal["confidence"] = min(signal["confidence"], 0.65)
            signal["red_flags"] = signal.get("red_flags", "") + " | R/R below 1.5 — confidence capped"

        # Attach metadata
        signal["ticker"] = snapshot["ticker"]
        signal["display_name"] = snapshot["display_name"]
        signal["asset_type"] = asset_type
        signal["price"] = price
        signal["spy_change"] = spy_change

        return signal

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {snapshot['ticker']}: {e}")
        return None
    except Exception as e:
        logger.error(f"Extended LLM failed for {snapshot['ticker']}: {e}")
        return None
