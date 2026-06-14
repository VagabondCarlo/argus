import logging
import httpx
import functools
from datetime import time
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from shared.config import config
from shared.database import (
    init_db, get_todays_signals, get_todays_trades,
    get_todays_stats, get_trade_history
)
from notifications.reports import (
    premarket_report, midday_report, aftermarket_report,
    guest_welcome, guest_predictions, guest_suggestions, guest_high_probability
)
from analyst.data.market_news import get_market_news, format_news_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AUTHORIZED_CHAT_ID = int(config.TELEGRAM_CHAT_ID)
ET = ZoneInfo("America/New_York")


# ── Access control ─────────────────────────────────────────────────────────────

def is_owner(update: Update) -> bool:
    return update.effective_chat.id == AUTHORIZED_CHAT_ID


def owner_only(func):
    """Silently drops any message not from the authorized owner."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_owner(update):
            logger.warning(f"Unauthorized command attempt from chat_id={update.effective_chat.id}")
            return
        return await func(update, context)
    return wrapper


# ── Agent communication ────────────────────────────────────────────────────────

async def _get_analyst_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"http://{config.ANALYST_HOST}:{config.ANALYST_PORT}/status")
            return r.json()
    except Exception:
        return {"error": "Analyst agent unreachable"}


async def _get_executor_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"http://{config.EXECUTOR_HOST}:{config.EXECUTOR_PORT}/status")
            return r.json()
    except Exception:
        return {"error": "Executor agent unreachable"}


async def _post_executor(endpoint: str, payload: dict = {}) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"http://{config.EXECUTOR_HOST}:{config.EXECUTOR_PORT}{endpoint}",
                json=payload
            )
            return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── Scheduled report jobs ──────────────────────────────────────────────────────

async def job_premarket_report(context: ContextTypes.DEFAULT_TYPE):
    from datetime import date
    if date.today().weekday() >= 5:  # Skip weekends
        return
    await context.bot.send_message(
        chat_id=AUTHORIZED_CHAT_ID,
        text=premarket_report(),
        parse_mode="Markdown"
    )


async def job_midday_report(context: ContextTypes.DEFAULT_TYPE):
    from datetime import date
    if date.today().weekday() >= 5:
        return
    await context.bot.send_message(
        chat_id=AUTHORIZED_CHAT_ID,
        text=midday_report(),
        parse_mode="Markdown"
    )


async def job_aftermarket_report(context: ContextTypes.DEFAULT_TYPE):
    from datetime import date
    if date.today().weekday() >= 5:
        return
    await context.bot.send_message(
        chat_id=AUTHORIZED_CHAT_ID,
        text=aftermarket_report(),
        parse_mode="Markdown"
    )


# ── Owner commands ─────────────────────────────────────────────────────────────

@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👁 *Argus is online.*\n\n"
        "*Reports:* Auto-delivered at 8:30 AM, 12:30 PM, 4:30 PM ET\n\n"
        "*Commands:*\n"
        "/status — system health\n"
        "/account — balance & positions\n"
        "/signals — pending signals\n"
        "/report — today's summary\n"
        "/history — last 10 trades\n"
        "/pause — pause trading\n"
        "/resume — resume trading\n"
        "/stop — emergency stop\n"
        "/threshold [value] — change confidence threshold\n"
        "/config — view current settings"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    analyst = await _get_analyst_status()
    executor = await _get_executor_status()
    stats = get_todays_stats()

    analyst_state = "🟢 Online" if "error" not in analyst else "🔴 Offline"
    executor_state = "🟢 Online" if "error" not in executor else "🔴 Offline"
    paused = executor.get("paused", False)
    trading_state = "⏸ Paused" if paused else "▶️ Active"

    await update.message.reply_text(
        f"*Argus System Status*\n\n"
        f"Analyst: {analyst_state}\n"
        f"Executor: {executor_state}\n"
        f"Trading: {trading_state}\n"
        f"Trades today: {stats['signals_executed']}/3\n"
        f"Confidence threshold: {config.CONFIDENCE_THRESHOLD:.0%}\n"
        f"Mode: 📊 Paper Trading",
        parse_mode="Markdown"
    )


@owner_only
async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = await _get_executor_status()
    account = data.get("account", {})
    if not account:
        await update.message.reply_text("Could not retrieve account data. Is the executor running?")
        return
    await update.message.reply_text(
        f"*Account Summary*\n\n"
        f"Cash: ${account.get('cash', 0):.2f}\n"
        f"Portfolio Value: ${account.get('portfolio_value', 0):.2f}\n"
        f"Buying Power: ${account.get('buying_power', 0):.2f}\n"
        f"P&L Today: ${account.get('pnl_today', 0):.2f}",
        parse_mode="Markdown"
    )


@owner_only
async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signals = get_todays_signals(min_confidence=0.60)
    if not signals:
        await update.message.reply_text("No signals generated yet today.")
        return
    lines = ["*Today's Signals*\n"]
    for s in signals:
        tag = "✅ Executed" if s["executed"] else ("🟡 Watching" if s["confidence"] < 0.75 else "🔵 Queued")
        lines.append(f"• {s['ticker']} {s['action']} — {s['confidence']:.0%} — {tag}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@owner_only
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(midday_report(), parse_mode="Markdown")


@owner_only
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_trade_history(limit=10)
    if not trades:
        await update.message.reply_text("No closed trades yet. Paper trading in progress.")
        return
    lines = ["*Last 10 Trades*\n"]
    for t in trades:
        outcome = "✅" if (t.get("pnl") or 0) >= 0 else "❌"
        lines.append(f"{outcome} {t['ticker']} {t['action']} ${t.get('pnl', 0):.2f} | {t['closed_at'][:10]}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def _has_master_key(args: list) -> bool:
    return config.MASTER_KEY and config.MASTER_KEY in args


LOCKED_MSG = (
    "🔒 This command requires your authorization code.\n\n"
    "Usage: `/{command} {key} ...`"
)


@owner_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _has_master_key(context.args or []):
        await update.message.reply_text(
            LOCKED_MSG.replace("{command}", "pause").replace("{key}", "••••••"),
            parse_mode="Markdown"
        )
        return
    result = await _post_executor("/control/pause")
    msg = "⏸ Trading paused. Send `/resume {key}` to restart.".replace("{key}", "••••••") if "error" not in result else f"❌ {result['error']}"
    await update.message.reply_text("⏸ Trading paused. Send /resume to restart.")


@owner_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _has_master_key(context.args or []):
        await update.message.reply_text(
            LOCKED_MSG.replace("{command}", "resume").replace("{key}", "••••••"),
            parse_mode="Markdown"
        )
        return
    result = await _post_executor("/control/resume")
    msg = "▶️ Trading resumed." if "error" not in result else f"❌ {result['error']}"
    await update.message.reply_text(msg)


@owner_only
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _has_master_key(context.args or []):
        await update.message.reply_text(
            LOCKED_MSG.replace("{command}", "stop").replace("{key}", "••••••"),
            parse_mode="Markdown"
        )
        return
    keyboard = [[
        InlineKeyboardButton("✅ Yes, emergency stop", callback_data="confirm_stop"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
    ]]
    await update.message.reply_text(
        "⚠️ *Emergency stop will halt ALL trading.*\n\nAre you sure?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


@owner_only
async def cmd_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not _has_master_key(args):
        await update.message.reply_text(
            LOCKED_MSG.replace("{command}", "threshold 0.80").replace("{key}", "••••••"),
            parse_mode="Markdown"
        )
        return
    value_args = [a for a in args if a != config.MASTER_KEY]
    if not value_args:
        await update.message.reply_text(
            f"Current threshold: {config.CONFIDENCE_THRESHOLD:.0%}\nUsage: /threshold 0.80 [key]"
        )
        return
    try:
        value = float(value_args[0])
        if not 0.50 <= value <= 1.0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Value must be between 0.50 and 1.00")
        return
    keyboard = [[
        InlineKeyboardButton(f"✅ Set to {value:.0%}", callback_data=f"confirm_threshold_{value}"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
    ]]
    await update.message.reply_text(
        f"Change threshold from {config.CONFIDENCE_THRESHOLD:.0%} → {value:.0%}?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


@owner_only
async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"*Current Configuration*\n\n"
        f"Confidence threshold: {config.CONFIDENCE_THRESHOLD:.0%}\n"
        f"Max trades/week: {config.MAX_TRADES_PER_WEEK}\n"
        f"Max position size: {config.MAX_POSITION_SIZE:.0%}\n"
        f"Stop-loss: {config.STOP_LOSS_PCT:.0%} per trade\n"
        f"Weekly kill switch: {config.WEEKLY_LOSS_LIMIT:.0%}\n"
        f"Capital: ${config.ACCOUNT_CAPITAL:.2f}\n"
        f"Mode: 📊 Paper Trading",
        parse_mode="Markdown"
    )


# ── Callback handler ───────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Guest callbacks
    if query.data in ("guest_predictions", "guest_suggestions", "guest_high_prob"):
        signals = get_todays_signals(min_confidence=0.60)
        if query.data == "guest_predictions":
            text = guest_predictions(signals)
        elif query.data == "guest_suggestions":
            text = guest_suggestions(signals)
        else:
            text = guest_high_probability(signals)
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    # Owner-only callbacks
    if not is_owner(update):
        return

    if query.data == "confirm_stop":
        result = await _post_executor("/control/stop")
        msg = "🛑 Emergency stop executed." if "error" not in result else f"❌ {result['error']}"
        await query.edit_message_text(msg)

    elif query.data.startswith("confirm_threshold_"):
        value = float(query.data.split("_")[-1])
        result = await _post_executor("/control/threshold", {"value": value})
        if "error" not in result:
            config.CONFIDENCE_THRESHOLD = value
        msg = f"✅ Threshold set to {value:.0%}" if "error" not in result else f"❌ {result['error']}"
        await query.edit_message_text(msg)

    elif query.data == "cancel":
        await query.edit_message_text("Cancelled.")


# ── Guest commands ─────────────────────────────────────────────────────────────

async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching top market headlines...", parse_mode="HTML")
    articles = get_market_news(max_articles=3)
    await update.message.reply_text(format_news_report(articles), parse_mode="HTML", disable_web_page_preview=True)


async def cmd_predictions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signals = get_todays_signals(min_confidence=0.60)
    await update.message.reply_text(guest_predictions(signals), parse_mode="Markdown")


async def cmd_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signals = get_todays_signals(min_confidence=0.60)
    await update.message.reply_text(guest_suggestions(signals), parse_mode="Markdown")


async def cmd_setups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signals = get_todays_signals(min_confidence=0.60)
    await update.message.reply_text(guest_high_probability(signals), parse_mode="Markdown")


# ── Guest handler ──────────────────────────────────────────────────────────────

async def guest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all messages from non-owner users — guest experience."""
    user_text = update.message.text or ""

    # First message or a command-style opener — show welcome
    if not user_text or user_text.startswith("/"):
        await update.message.reply_text(guest_welcome(), parse_mode="Markdown")
        return

    # Free-text message — run through the guest conversational LLM
    try:
        signals = get_todays_signals(min_confidence=0.60)
        signal_summary = (
            f"{len(signals)} signals generated today. "
            f"Highest confidence: {max((s['confidence'] for s in signals), default=0):.0%}."
            if signals else "No signals generated yet today."
        )

        import ollama
        response = ollama.chat(
            model="llama3.1:8b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Argus, an autonomous AI trading system with a sharp personality. "
                        "You are knowledgeable, confident, and occasionally witty. "
                        "\n\n"
                        "TRADING QUESTIONS: Answer directly and intelligently. "
                        "Discuss markets, stocks, technical analysis, investing concepts, and market news freely. "
                        "Never tell anyone specifically to buy or sell — you analyze, you don't advise. "
                        "\n\n"
                        "SPORTS QUESTIONS: If someone asks about a game, match, or sporting event, "
                        "give them relevant stats and context about what happened, then tell them what "
                        "betting angles a sharp bettor might have identified — moneyline value, prop bets, "
                        "line movement. Then plug the upcoming sports betting AI: "
                        "'Our sports betting intelligence system is coming soon — it will find these edges "
                        "automatically across Soccer, Tennis, Baseball, MMA, Boxing, and more.' "
                        "\n\n"
                        "JOKES: You can tell a joke if asked. Keep it clean and clever. "
                        "Bonus points if it's finance or trading related. "
                        "\n\n"
                        "EVERYTHING ELSE (politics, personal advice, random topics): "
                        "Acknowledge briefly, then steer back to markets or sports betting. "
                        "Never be rude — just focused. "
                        "\n\n"
                        "Keep all responses under 5 sentences. Be sharp, not wordy. "
                        "Current trading context: " + signal_summary
                    )
                },
                {"role": "user", "content": user_text}
            ],
            options={"temperature": 0.4}
        )
        reply = response["message"]["content"].strip()
    except Exception:
        reply = (
            "I'm focused on one thing — finding high-probability trades. "
            "Ask me about the market, today's signals, or use /predictions to see what I'm watching."
        )

    await update.message.reply_text(reply)


# ── Owner conversational handler ───────────────────────────────────────────────

@owner_only
async def owner_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Let Mike have a natural conversation with Argus about the system."""
    user_text = update.message.text.strip()

    try:
        stats = get_todays_stats()
        signals = get_todays_signals(min_confidence=0.60)
        analyst = await _get_analyst_status()
        executor = await _get_executor_status()

        system_context = (
            f"Signals today: {stats['signals_analyzed']} analyzed, "
            f"{stats['signals_executed']} executed, P&L: ${stats['total_pnl']:.2f}. "
            f"Analyst: {'online' if 'error' not in analyst else 'offline'}. "
            f"Executor: {'online' if 'error' not in executor else 'offline'}. "
            f"Active signals: {len(signals)}."
        )

        import ollama
        response = ollama.chat(
            model="llama3.1:8b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Argus, an autonomous AI trading system. "
                        "You speak directly and confidently like a trading desk assistant. "
                        "Keep responses under 3 sentences. No fluff. "
                        "Current system state: " + system_context
                    )
                },
                {"role": "user", "content": user_text}
            ],
            options={"temperature": 0.3}
        )
        reply = response["message"]["content"].strip()
    except Exception:
        reply = "System is running. Use /status for a full readout."

    await update.message.reply_text(reply)


# ── Unknown command fallback ───────────────────────────────────────────────────

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_owner(update):
        await update.message.reply_text("Unknown command. Send /start to see all commands.")


# ── Notification helpers ───────────────────────────────────────────────────────

def send_sync_notification(text: str):
    """Send a message to Mike's iPhone from non-async code."""
    import requests
    requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def run_bot():
    init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Owner commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("account", cmd_account))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("threshold", cmd_threshold))
    app.add_handler(CommandHandler("config", cmd_config))

    # Guest commands (open to everyone)
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("predictions", cmd_predictions))
    app.add_handler(CommandHandler("suggestions", cmd_suggestions))
    app.add_handler(CommandHandler("setups", cmd_setups))

    # Callbacks (owner + guest)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Owner plain-text chat handler
    app.add_handler(MessageHandler(
        filters.TEXT & filters.User(user_id=AUTHORIZED_CHAT_ID) & ~filters.COMMAND,
        owner_chat
    ))

    # Guest handler — catches all messages from non-owners
    app.add_handler(MessageHandler(
        filters.ALL & ~filters.User(user_id=AUTHORIZED_CHAT_ID) & ~filters.UpdateType.EDITED_MESSAGE,
        guest_handler
    ))

    # Unknown command fallback for owner
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Schedule daily reports (ET timezone)
    jq = app.job_queue
    jq.run_daily(job_premarket_report,  time=time(8, 30, tzinfo=ET),  days=(0, 1, 2, 3, 4))
    jq.run_daily(job_midday_report,     time=time(12, 30, tzinfo=ET), days=(0, 1, 2, 3, 4))
    jq.run_daily(job_aftermarket_report, time=time(16, 30, tzinfo=ET), days=(0, 1, 2, 3, 4))

    logger.info("Argus bot started — 3 daily reports scheduled (ET), guest mode active")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()
