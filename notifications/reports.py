from datetime import date
from shared.database import get_todays_signals, get_todays_trades, get_todays_stats


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
    trades = get_todays_trades()
    signals = get_todays_signals(min_confidence=0.60)
    stats = get_todays_stats()

    today = date.today().strftime("%A, %B %d")
    lines = [f"☀️ *Mid-Day Report — {today}*\n", "📊 Paper Trading Mode\n"]

    lines.append(f"*Trades executed today:* {stats['signals_executed']}/{3}")

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

    lines.append("\n_Markets close 4:00 PM ET. After-market report at 4:30 PM._")
    return "\n".join(lines)


def aftermarket_report() -> str:
    trades = get_todays_trades()
    signals = get_todays_signals(min_confidence=0.60)
    stats = get_todays_stats()
    missed = [s for s in signals if not s["executed"]]

    today = date.today().strftime("%A, %B %d")
    lines = [f"🌙 *After-Market Report — {today}*\n", "📊 Paper Trading Mode\n"]

    lines.append(f"*Day Summary:*")
    lines.append(f"• Trades: {stats['signals_executed']} | Wins: {stats['wins']} | Losses: {stats['losses']}")
    pnl_icon = "📈" if stats["total_pnl"] >= 0 else "📉"
    lines.append(f"• {pnl_icon} Paper P&L: ${stats['total_pnl']:.2f}")
    lines.append(f"• Signals analyzed: {stats['signals_analyzed']} | Rejected: {stats['signals_rejected']}")

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
        "👁 *Welcome to Argus Trading Intelligence*\n\n"
        "I'm an autonomous AI trading system that scans the entire market in real-time "
        "using local language models, technical analysis, and live news feeds.\n\n"
        "Built and operated by a private trader. Paper trading mode — all signals are live analysis.\n\n"
        "You can also just *talk to me* — ask about the market, a sector, "
        "or what conditions I look for before making a move.\n\n"
        "*Commands:*\n\n"
        "/predictions — Today's highest-confidence trade reads\n"
        "/suggestions — Full setups with entry, stop-loss, and target\n"
        "/setups — Only signals at 65%+ confidence\n"
        "/news — Top 3 market-moving headlines right now\n"
    )


def guest_predictions(signals) -> str:
    if not signals:
        return "📈 *Today's Predictions*\n\nNo signals generated yet today. Check back after market open."

    lines = ["📈 *Today's Predictions*\n"]
    lines.append("These are Argus's highest-confidence reads on the market today:\n")
    for s in signals[:5]:
        icon = "🟢" if s["action"] == "BUY" else "🔴"
        lines.append(
            f"{icon} *{s['ticker']}* — {s['action']} @ ${s.get('price_target', 0):.2f}\n"
            f"Confidence: {s['confidence']:.0%}\n"
            f"_{s['reasoning'][:120]}_\n"
        )
    lines.append("⚠️ _Not financial advice. Paper trading system._")
    return "\n".join(lines)


def guest_suggestions(signals) -> str:
    if not signals:
        return "💡 *Trade Suggestions*\n\nNo suggestions available yet today."

    lines = ["💡 *Trade Suggestions*\n"]
    lines.append("Setups Argus identified today with entry, stop, and target:\n")
    for s in signals[:5]:
        icon = "🟢" if s["action"] == "BUY" else "🔴"
        risk = round(abs(s.get("price_target", 0) - s.get("stop_loss", 0)), 2)
        lines.append(
            f"{icon} *{s['ticker']}* {s['action']}\n"
            f"Entry: ~${s.get('price_target', 0):.2f} | "
            f"Stop: ${s.get('stop_loss', 0):.2f} | "
            f"Risk: ${risk:.2f}/share\n"
            f"Confidence: {s['confidence']:.0%}\n"
        )
    lines.append("⚠️ _Not financial advice. These are paper trading signals._")
    return "\n".join(lines)


def guest_high_probability(signals) -> str:
    high = [s for s in signals if s["confidence"] >= 0.65]
    if not high:
        return "🔥 *High Probability Setups*\n\nNo high-probability setups identified yet today."

    lines = ["🔥 *High Probability Setups*\n"]
    lines.append(
        f"Argus identified {len(high)} setup(s) today with ≥65% confidence. "
        f"Trades execute automatically at ≥75%.\n"
    )
    for s in high:
        executed_tag = " ✅ *Executed*" if s["executed"] else ""
        lines.append(
            f"• *{s['ticker']}* {s['action']} — {s['confidence']:.0%}{executed_tag}\n"
            f"  _{s['reasoning'][:100]}_\n"
        )
    lines.append("⚠️ _Not financial advice. Autonomous paper trading system._")
    return "\n".join(lines)
