from datetime import date
from shared.database import get_todays_signals, get_todays_trades, get_todays_stats, get_win_rate

_DISCLAIMER = (
    "⚠️ *Not financial advice.* Argus is an algorithmic signal tool for educational purposes only. "
    "We are not licensed advisors. You may lose money. Only risk capital you can afford to lose entirely."
)

_STOP_INSTRUCTIONS = (
    "*How to use these signals:*\n"
    "1️⃣ Enter near the Entry price\n"
    "2️⃣ Place a stop-loss order at the Stop price in your broker immediately\n"
    "3️⃣ Set a take-profit at the Target price\n"
    "💰 Risk no more than 1-2% of your account per trade"
)


def premarket_report() -> str:
    signals = get_todays_signals(min_confidence=0.60)
    actionable = [s for s in signals if s["confidence"] >= 0.75]
    watching = [s for s in signals if s["confidence"] < 0.75]

    today = date.today().strftime("%A, %B %d")
    lines = [f"🌅 *Pre-Market Report — {today}*\n", "📊 Paper Trading Mode\n"]

    if actionable:
        lines.append(f"*Signals ready to execute ({len(actionable)}):*")
        for s in actionable[:3]:
            lines.append(
                f"• {s['ticker']} {s['action']} — {s['confidence']:.0%} confidence\n"
                f"  Target: ${s['price_target']:.2f} | Stop: ${s['stop_loss']:.2f}\n"
                f"  _{s['reasoning'][:100]}_"
            )
    else:
        lines.append("*No signals above 75% threshold yet.*\nArgus is scanning — signals update throughout the morning.")

    if watching:
        lines.append(f"\n*Watching closely ({len(watching)}):*")
        for s in watching[:3]:
            lines.append(f"• {s['ticker']} {s['action']} — {s['confidence']:.0%} — building confidence")

    lines.append("\n_Market opens 9:30 AM ET. Next report at 12:30 PM._")
    return "\n".join(lines)


def midday_report() -> str:
    from shared.config import config
    trades = get_todays_trades()
    signals = get_todays_signals(min_confidence=0.60)
    stats = get_todays_stats()
    wr = get_win_rate()

    today = date.today().strftime("%A, %B %d")
    lines = [f"☀️ *Mid-Day Report — {today}*\n", "📊 Paper Trading Mode\n"]

    lines.append(f"*Trades this week:* {stats['signals_executed']}/{config.MAX_TRADES_PER_WEEK}")

    if trades:
        for t in trades:
            status = "🟢 Open" if t["status"] == "open" else "⬜ Closed"
            lines.append(
                f"• {t['ticker']} {t['action']} @ ${t['fill_price']:.2f} — {status}"
            )
    else:
        lines.append("• No trades executed yet today.")

    lines.append(f"\n*Signals analyzed:* {stats['signals_analyzed']}")
    lines.append(f"*Still watching:* {len([s for s in signals if not s['executed']])} setups")

    if stats["total_pnl"] != 0:
        pnl_icon = "📈" if stats["total_pnl"] >= 0 else "📉"
        lines.append(f"\n{pnl_icon} *Paper P&L today:* ${stats['total_pnl']:.2f}")

    if wr["total_trades"] > 0:
        lines.append(
            f"\n*All-time track record:* {wr['wins']}W / {wr['losses']}L — "
            f"{wr['win_rate']:.0%} win rate | ${wr['total_pnl']:+.2f} P&L"
        )

    lines.append("\n_Markets close 4:00 PM ET. After-market report at 4:30 PM._")
    return "\n".join(lines)


def aftermarket_report() -> str:
    from shared.config import config
    trades = get_todays_trades()
    signals = get_todays_signals(min_confidence=0.60)
    stats = get_todays_stats()
    missed = [s for s in signals if not s["executed"]]
    wr = get_win_rate()

    today = date.today().strftime("%A, %B %d")
    lines = [f"🌙 *After-Market Report — {today}*\n", "📊 Paper Trading Mode\n"]

    lines.append(f"*Day Summary:*")
    lines.append(f"• Trades: {stats['signals_executed']} | Wins: {stats['wins']} | Losses: {stats['losses']}")
    pnl_icon = "📈" if stats["total_pnl"] >= 0 else "📉"
    lines.append(f"• {pnl_icon} Paper P&L: ${stats['total_pnl']:.2f}")
    lines.append(f"• Signals analyzed: {stats['signals_analyzed']} | Rejected: {stats['signals_rejected']}")

    if wr["total_trades"] > 0:
        lines.append(
            f"\n*Track record:* {wr['wins']}W / {wr['losses']}L "
            f"({wr['win_rate']:.0%} win rate) | ${wr['total_pnl']:+.2f} total P&L"
        )

    if missed:
        lines.append(f"\n*Signals not executed (below 75% threshold):*")
        for s in missed[:3]:
            lines.append(
                f"• {s['ticker']} {s['action']} — {s['confidence']:.0%}\n"
                f"  _{s['reasoning'][:100]}_"
            )

    lines.append("\n*Tomorrow's outlook:*")
    lines.append("Argus will begin scanning pre-market at 8:00 AM ET.")
    lines.append("Pre-market report delivered at 8:30 AM.")
    lines.append("\n_Rest up. Argus never sleeps. 👁_")
    return "\n".join(lines)


def guest_welcome() -> str:
    return (
        "👁 *Welcome to Argus*\n\n"
        "Autonomous AI trading signals — stocks, forex, metals, crypto.\n"
        "Real-time technical analysis running 24/7 on a private server.\n\n"
        "⚠️ *These signals are for educational purposes only. "
        "Not financial advice. We are not licensed advisors. "
        "You may lose money — only risk what you can afford to lose.*\n\n"
        "*Commands:*\n"
        "/predictions — Today's top setups\n"
        "/suggestions — Full setups with entry, stop, and target\n"
        "/setups — High\\-probability signals only\n"
        "/news — Market headlines\n"
        "/disclaimer — Full risk disclosure"
    )


def guest_predictions(signals) -> str:
    if not signals:
        return "📈 *Today's Predictions*\n\nNo signals generated yet today. Check back after market open."

    lines = ["📈 *Today's Predictions*\n"]
    lines.append("Argus's highest\\-confidence reads today:\n")
    for s in signals[:5]:
        icon = "🟢" if s["action"] == "BUY" else "🔴"
        lines.append(
            f"{icon} *{s['ticker']}* — {s['action']}\n"
            f"Confidence: {s['confidence']:.0%}\n"
            f"_{s['reasoning'][:120]}_\n"
        )
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def guest_suggestions(signals) -> str:
    if not signals:
        return "💡 *Trade Suggestions*\n\nNo suggestions available yet today."

    lines = ["💡 *Trade Suggestions*\n"]
    lines.append("Setups with entry, stop, and target:\n")
    for s in signals[:5]:
        icon = "🟢" if s["action"] == "BUY" else "🔴"
        entry = s.get("price_target", 0)
        stop  = s.get("stop_loss",   0)
        risk  = round(abs(entry - stop), 2)
        lines.append(
            f"{icon} *{s['ticker']}* {s['action']}\n"
            f"Target: ${entry:.2f} | Stop: ${stop:.2f} | Risk per share: ${risk:.2f}\n"
            f"Confidence: {s['confidence']:.0%}\n"
        )
    lines += [
        _STOP_INSTRUCTIONS,
        "",
        _DISCLAIMER,
    ]
    return "\n".join(lines)


def guest_high_probability(signals) -> str:
    high = [s for s in signals if s["confidence"] >= 0.65]
    if not high:
        return "🔥 *High Probability Setups*\n\nNo high-probability setups identified yet today."

    wr = get_win_rate()
    lines = ["🔥 *High Probability Setups*\n"]
    lines.append(
        f"Argus identified {len(high)} setup(s) today with 65%+ confidence. "
        f"Trades execute automatically at 75%+.\n"
    )

    if wr["total_trades"] > 0:
        lines.append(
            f"📊 *Track record:* {wr['wins']}W / {wr['losses']}L "
            f"({wr['win_rate']:.0%} win rate)\n"
        )

    for s in high:
        executed_tag = " ✅ *Executed*" if s["executed"] else ""
        lines.append(
            f"• *{s['ticker']}* {s['action']} — {s['confidence']:.0%}{executed_tag}\n"
            f"  _{s['reasoning'][:100]}_\n"
        )
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def full_disclaimer() -> str:
    return (
        "📋 *Argus Risk Disclosure*\n\n"
        "*What Argus is:*\n"
        "An autonomous algorithmic signal system using technical analysis, "
        "social sentiment, and local AI models to identify potential trade setups\\.\n\n"
        "*What Argus is NOT:*\n"
        "• A licensed financial advisor\n"
        "• A broker or investment manager\n"
        "• A guarantee of any return\n\n"
        "*Your responsibility:*\n"
        "• These signals are for educational and informational purposes only\n"
        "• Nothing here constitutes financial advice\n"
        "• You are solely responsible for your own trading decisions\n"
        "• You may lose your entire investment\n"
        "• Past signal performance does not guarantee future results\n"
        "• Always do your own research before placing any trade\n\n"
        "*Position sizing rule:*\n"
        "Never risk more than 1\\-2% of your total account on a single trade\\. "
        "If a trade hits its stop\\-loss, your loss should be manageable\\. "
        "Example: $5,000 account → $50\\-100 max loss per trade\\.\n\n"
        "*Stop\\-loss rule:*\n"
        "Always place a stop\\-loss order in your broker immediately after entering a trade\\. "
        "The stop price in every signal is your suggested exit level if the trade goes against you\\. "
        "Without a stop, a single bad trade can wipe out weeks of gains\\.\n\n"
        "_By using Argus signals you confirm you understand and accept these risks\\._"
    )
