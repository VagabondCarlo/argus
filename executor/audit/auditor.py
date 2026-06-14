"""
Executor-side independent audit.
The Analyst scores 70-75%. This auditor stress-tests the signal
from a pure risk/execution perspective before capital moves.
"""
import ollama
import json
import logging
import re

logger = logging.getLogger(__name__)

MODEL = "llama3.1:8b"

AUDIT_SYSTEM_PROMPT = """You are the Argus Risk Desk — an independent execution auditor.

The Analyst has already approved this signal using three frameworks (Buffett quality,
Dalio macro, Reed technical). Your job is NOT to find trades. Your job is to be the
last skeptic before real capital moves.

You ask four questions — answer each honestly:

1. TIMING: Is right now the ideal entry, or is the stock extended/too early?
2. WORST CASE: If this trade goes against us immediately, what is the realistic damage?
3. COUNTER-THESIS: What single event or data point would make this trade completely wrong?
4. EXECUTION QUALITY: Is the setup precise enough to enter at this exact price, or are we guessing?

You are NOT trying to find reasons to trade. You are trying to find reasons NOT to.
If you cannot find a strong reason to reject it, you approve it with a high score.

If the Analyst's confidence was already 70-75%, your job is to determine if deeper
scrutiny reveals it deserves to cross the 75% execution threshold — or whether something
was missed that should keep it grounded.

Respond ONLY with valid JSON. No prose outside the JSON block.
"""

AUDIT_PROMPT = """Stress-test this signal before capital is deployed.

SIGNAL FROM ANALYST:
  Ticker:             {ticker}
  Action:             {action}
  Analyst Confidence: {analyst_confidence:.0%}
  Setup Type:         {setup_type}
  Price Target:       ${price_target:.2f}
  Stop Loss:          ${stop_loss:.2f}
  Risk/Reward:        {risk_reward:.1f}x
  Analyst Reasoning:  {reasoning}
  Red Flags Noted:    {red_flags}

CURRENT MARKET DATA:
  Price:              ${price:.2f}
  RSI:                {rsi}
  Volume Ratio:       {volume_ratio}x normal
  EMA Trend:          {ema_trend}
  SPY Today:          {spy_change:+.2f}%
  Market Regime:      {market_regime}

ACCOUNT HEALTH:
  Weekly trades used: {weekly_trades}/3
  Available capital:  ${available_capital:.2f}

Run your four-question stress test. Return ONLY this JSON:
{{
  "approved": true or false,
  "audit_confidence": 0.0 to 1.0,
  "timing_verdict": "ideal" or "acceptable" or "poor",
  "worst_case": "One sentence describing the realistic downside scenario.",
  "counter_thesis": "One sentence — what would make this trade fail.",
  "audit_notes": "2-3 sentences. What the Risk Desk found. Cite specifics.",
  "veto_reason": "If approved is false, explain why. Otherwise 'none'."
}}

Rules:
- audit_confidence >= 0.75 means the trade executes
- If analyst red_flags are serious, veto unless the setup is exceptional
- Weekly trades at 3/3 = auto veto (approved: false)
- If timing_verdict is "poor", cap audit_confidence at 0.65
- Be the skeptic. One clear veto reason is enough to block.
"""


def run_audit(signal: dict, snapshot: dict, account_info: dict, weekly_trades: int, spy_change: float, market_regime: str) -> dict:
    """
    Independent stress-test of an analyst signal.
    Returns audit result with approved flag and final confidence.
    """
    price = snapshot.get("price", 0)
    available_capital = float(account_info.get("cash", 0))

    prompt = AUDIT_PROMPT.format(
        ticker=signal["ticker"],
        action=signal["action"],
        analyst_confidence=signal["confidence"],
        setup_type=signal.get("setup_type", "unknown"),
        price_target=signal.get("price_target", price),
        stop_loss=signal.get("stop_loss", price * 0.98),
        risk_reward=signal.get("risk_reward", 0),
        reasoning=signal.get("reasoning", ""),
        red_flags=signal.get("red_flags", "none"),
        price=price,
        rsi=snapshot.get("rsi", 50),
        volume_ratio=snapshot.get("volume_ratio", 1.0),
        ema_trend=snapshot.get("ema_trend", "unknown"),
        spy_change=spy_change,
        market_regime=market_regime,
        weekly_trades=weekly_trades,
        available_capital=available_capital,
    )

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.05}
        )
        raw = response["message"]["content"].strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logger.warning(f"No JSON in audit response for {signal['ticker']}")
            return _default_reject("LLM returned no JSON")

        result = json.loads(json_match.group())

        # Hard rule: weekly limit is absolute
        if weekly_trades >= 3:
            result["approved"] = False
            result["veto_reason"] = "Weekly trade limit reached (3/3)"
            result["audit_confidence"] = 0.0

        logger.info(
            f"AUDIT {signal['ticker']}: approved={result.get('approved')} "
            f"conf={result.get('audit_confidence', 0):.0%} "
            f"timing={result.get('timing_verdict')} "
            f"veto={result.get('veto_reason','none')}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Audit JSON parse error for {signal['ticker']}: {e}")
        return _default_reject("JSON parse error")
    except Exception as e:
        logger.error(f"Audit failed for {signal['ticker']}: {e}")
        return _default_reject(str(e))


def _default_reject(reason: str) -> dict:
    return {
        "approved": False,
        "audit_confidence": 0.0,
        "timing_verdict": "poor",
        "worst_case": "Unknown — audit failed.",
        "counter_thesis": "Unknown — audit failed.",
        "audit_notes": f"Audit error: {reason}",
        "veto_reason": reason,
    }
