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
    CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    MAX_TRADES_PER_WEEK = int(os.getenv("MAX_TRADES_PER_WEEK", "25"))
    MAX_OPEN_POSITIONS  = int(os.getenv("MAX_OPEN_POSITIONS", "3"))

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


config = Config()

if not config.MASTER_KEY:
    logger.critical("MASTER_KEY is not set — all owner commands are unprotected. Set it in .env and restart.")
