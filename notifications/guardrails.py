"""Guardrails for the guest-facing LLM chat.

Defense in depth, cheapest layer first:
  1. screen_input  — regex screen for the common jailbreak playbook, length cap,
                     URL limits. Flagged messages never reach the LLM.
  2. prompt hardening — user text is wrapped as untrusted data (done in bot.py).
  3. screen_output — replies that leak prompt internals or break the
                     suggestions-only compliance rule get replaced.
  4. strikes       — 3 flagged messages in 24h mutes the user for 24h.

Strikes are in-memory: a bot restart amnesties everyone, which is fine — the
goal is stopping iteration, not holding grudges. Every flag is logged with the
user_id so patterns are visible in the bot pane.
"""
import logging
import re
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 1000
MAX_REPLY_CHARS = 2500
STRIKE_LIMIT = 3
STRIKE_WINDOW_S = 24 * 3600
MUTE_S = 24 * 3600

_strikes: dict[int, list[float]] = defaultdict(list)
_muted_until: dict[int, float] = {}

# The common jailbreak playbook. Deliberately NOT included: "token" (crypto
# guests say it constantly), generic "act as if" (normal market speech).
_INJECTION_PATTERNS = [
    r"ignore (all |any |your |the |previous |prior |above )*(instructions|rules|prompt)",
    r"disregard (your|the|all|any|previous|prior)",
    r"system prompt",
    r"you are now",
    r"new (persona|identity|instructions|system)",
    r"act as (if you were|a different|an? unrestricted)",
    r"pretend (you're|you are|to be)",
    r"developer mode",
    r"\bDAN\b",
    r"jailbreak",
    r"do anything now",
    r"(reveal|show|repeat|print|output) (your|the) (instructions|prompt|rules|system)",
    r"override (your|the|all)",
    r"without (your|any) (restrictions|rules|filters)",
    r"master.?key",
    r"api.?key",
    r"\.env\b",
    r"\bpassword\b",
    r"base64|rot13",
]
_inj_re = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Replies that must never go out: prompt leakage, broken persona, or
# directive trading language (the suggestions-only compliance rule).
_OUTPUT_PATTERNS = [
    r"my (system )?(prompt|instructions) (says?|are|is|tell)",
    r"as an? (DAN|unrestricted|uncensored)",
    r"i am no longer (argus|bound|restricted)",
    r"you should (buy|sell|short)",
    r"\b(buy|sell) now\b",
    r"guaranteed (profit|win|return|gain)",
]
_out_re = re.compile("|".join(_OUTPUT_PATTERNS), re.IGNORECASE)

DEFLECT_REPLY = (
    "Nice try. I talk markets, signals, and the occasional game — "
    "that's the whole menu. Ask me something about trading."
)

FALLBACK_REPLY = (
    "I'm focused on one thing — finding high-probability trades. "
    "Ask me about the market or today's signals."
)


def screen_input(text: str) -> tuple[bool, str]:
    """(ok, reason). Flagged input must never reach the LLM."""
    if len(text) > MAX_INPUT_CHARS:
        return False, f"length {len(text)} over cap"
    m = _inj_re.search(text)
    if m:
        return False, f"pattern '{m.group(0)[:40]}'"
    if text.lower().count("http") > 1:
        return False, "multiple URLs"
    return True, ""


def screen_output(text: str) -> str:
    """Replace unsafe LLM replies; cap length."""
    if not text or not text.strip():
        return FALLBACK_REPLY
    if _out_re.search(text):
        logger.warning("Guardrail: output screen replaced an LLM reply")
        return FALLBACK_REPLY
    return text[:MAX_REPLY_CHARS]


def record_flag(user_id: int) -> int:
    """Count a strike; mute at the limit. Returns current strike count."""
    now = time.time()
    strikes = [t for t in _strikes[user_id] if now - t < STRIKE_WINDOW_S]
    strikes.append(now)
    _strikes[user_id] = strikes
    if len(strikes) >= STRIKE_LIMIT:
        _muted_until[user_id] = now + MUTE_S
        logger.warning(
            f"Guardrail: user {user_id} muted 24h after {len(strikes)} flagged messages"
        )
    return len(strikes)


def is_muted(user_id: int) -> bool:
    return time.time() < _muted_until.get(user_id, 0.0)
