"""
OpenClaw research agent client.
Uses the openclaw CLI (`openclaw agent`) to run one-shot agent turns via the
local gateway — no custom HTTP endpoint needed. If OpenClaw isn't installed
or the gateway isn't running, every call gracefully returns an empty string.
"""

import logging
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60  # browser research can take a while


def ask_openclaw(question: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """
    Run one agent turn via `openclaw agent` CLI.
    Returns the agent's text response, or empty string if unavailable.
    """
    if not is_openclaw_available():
        return ""
    try:
        result = subprocess.run(
            ["openclaw", "agent", "--model", "ollama-local/llama3.1:8b", question],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "").strip()
        if output:
            return output
        if result.returncode != 0:
            logger.debug(f"openclaw agent exited {result.returncode}: {result.stderr[:200]}")
        return ""
    except subprocess.TimeoutExpired:
        logger.debug("openclaw agent timed out")
        return ""
    except Exception as e:
        logger.debug(f"openclaw agent call failed: {e}")
        return ""


def is_openclaw_available() -> bool:
    """Returns True if the openclaw binary is on PATH and the gateway is running."""
    if not shutil.which("openclaw"):
        return False
    try:
        result = subprocess.run(
            ["openclaw", "gateway", "health"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return result.returncode == 0
    except Exception:
        return False


# ── Intent detection ─────────────────────────────────────────────────────────

_RESEARCH_KEYWORDS = [
    "right now", "happening with", "latest on", "what's going on",
    "tell me about", "research", "look up", "look into", "find out",
    "insider", "insiders", "sec filing", "form 4",
    "options flow", "unusual options", "dark pool",
    "reddit", "wallstreetbets", "wsb", "stocktwits", "social",
    "analyst rating", "upgrade", "downgrade", "price target",
    "short interest", "short squeeze",
    "earnings report", "earnings date", "when do they report",
    "news on", "news about", "headlines",
    "sentiment on", "what do people think",
    "institutional", "whale", "big money",
    "coingecko", "on-chain", "whale wallet",
]

_TICKER_RE = re.compile(r'\b([A-Z]{1,5}(?:-USD)?)\b')


def needs_live_research(text: str) -> bool:
    """Returns True if the message is asking for live, web-sourced data."""
    lower = text.lower()
    if any(kw in lower for kw in _RESEARCH_KEYWORDS):
        return True
    has_ticker = bool(_TICKER_RE.search(text))
    is_question = any(w in lower for w in [
        "what", "how", "why", "when", "where", "who",
        "show me", "give me", "can you", "is there"
    ])
    return has_ticker and is_question


def extract_ticker(text: str) -> str | None:
    match = _TICKER_RE.search(text)
    return match.group(1) if match else None


def build_research_prompt(user_text: str) -> str:
    ticker = extract_ticker(user_text)
    base = (
        f"Research request from Argus trading system: {user_text}\n\n"
        "Please browse the most relevant financial sources and return:\n"
        "1. What's actually happening with this asset right now\n"
        "2. Any insider activity, analyst changes, or unusual options flow\n"
        "3. Social sentiment from Reddit or StockTwits\n"
        "4. Any red flags or strong signals a trader should know\n"
        "Be concise — 5-8 sentences max. No fluff."
    )
    if ticker:
        base = f"Focus on: {ticker}\n\n" + base
    return base
