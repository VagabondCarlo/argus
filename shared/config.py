import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    # Alpaca
    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    TIER1_CHANNEL_ID = os.getenv("TIER1_CHANNEL_ID", "")   # free public channel
    TIER2_CHANNEL_ID = os.getenv("TIER2_CHANNEL_ID", "")   # paid private channel

    # News
    NEWS_API_KEY = os.getenv("NEWS_API_KEY")

    # Social media
    TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

    # Master key — required for destructive commands
    MASTER_KEY = os.getenv("MASTER_KEY", "")

    # Trading rules — hard limits, not suggestions
    # 0.72 floor set from the v1 signal replay (June 16 – July 6 archive):
    # >=0.72 won 56% at ~2:1 R/R (+20.4R); the 0.70-0.72 slice lost ~23R.
    CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.72"))
    MAX_TRADES_PER_WEEK = int(os.getenv("MAX_TRADES_PER_WEEK", "25"))
    MAX_OPEN_POSITIONS  = int(os.getenv("MAX_OPEN_POSITIONS", "3"))

    # Signals older than this never execute — a scalp entry from 15+ minutes
    # ago is priced on a market that no longer exists. Scans run every 5 min
    # during market hours, so a fresh batch always arrives before expiry.
    SIGNAL_MAX_AGE_MINUTES = int(os.getenv("SIGNAL_MAX_AGE_MINUTES", "15"))

    # Crypto executes through Alpaca 24/7; forex/metals stay signal-only (no broker)
    CRYPTO_ENABLED = os.getenv("CRYPTO_ENABLED", "true").lower() == "true"

    # Short selling — stocks only (Alpaca can't short crypto). OFF by default;
    # flip to "true" in .env once reviewed. Unlocks SELL signals (currently
    # discarded) — backtest: SELL-with-trend wins ~62%. Shorts use the same
    # -3% hard cut and $50 sizing as longs; the position monitor is the stop.
    SHORTING_ENABLED = os.getenv("SHORTING_ENABLED", "false").lower() == "true"

    # Telegram noise control. "digest": routine trade activity (entries, normal
    # exits, breakeven) is logged + DB-recorded and appears in the 3 daily
    # reports; pushes fire only for events needing a human (risk limits, failed
    # orders, hard cuts). "all": push everything (v1 behavior).
    NOTIFY_MODE = os.getenv("NOTIFY_MODE", "digest")

    # Public track-record feed: every closed trade + daily recap post here.
    # Unset = preview mode (posts go to the owner's chat tagged [PREVIEW]).
    # Set to the Tier 1 channel ID to go public.
    TRACK_RECORD_CHANNEL_ID = os.getenv("TRACK_RECORD_CHANNEL_ID", "")

    # Position sizing — always based on ACCOUNT_CAPITAL, never on broker cash balance
    # This prevents oversized positions on paper accounts that have large starting balances
    MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.20"))   # 20% of ACCOUNT_CAPITAL per trade
    ACCOUNT_CAPITAL   = float(os.getenv("ACCOUNT_CAPITAL", "500.00"))   # real capital at risk

    # Loss limits (expressed as fraction of ACCOUNT_CAPITAL)
    STOP_LOSS_PCT      = float(os.getenv("STOP_LOSS_PCT",      "0.02"))  # 2% per trade
    DAILY_LOSS_LIMIT   = float(os.getenv("DAILY_LOSS_LIMIT",   "0.03"))  # 3% per day  = $15
    WEEKLY_LOSS_LIMIT  = float(os.getenv("WEEKLY_LOSS_LIMIT",  "0.06"))  # 6% per week = $30

    # Inter-agent communication
    ANALYST_HOST = os.getenv("ANALYST_HOST", "localhost")
    ANALYST_PORT = int(os.getenv("ANALYST_PORT", "8001"))
    EXECUTOR_HOST = os.getenv("EXECUTOR_HOST", "localhost")
    EXECUTOR_PORT = int(os.getenv("EXECUTOR_PORT", "8002"))

    # LLM backend (Agent 2 Ollama over Tailscale)
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")


config = Config()

if not config.MASTER_KEY:
    logger.critical("MASTER_KEY is not set — all owner commands are unprotected. Set it in .env and restart.")
