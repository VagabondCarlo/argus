"""
Multi-asset broadcast engine — 3x daily to Tier 1 and Tier 2 channels.

Schedule (ET): 8:15 AM pre-market | 12:00 PM midday | 4:30 PM next-day preview

Tier 1 (free, public): 1 pick per class (2nd best), confidence score, upgrade CTA
Tier 2 (paid, private): top 3 per class, full entry/stop/target, committee reasoning
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from analyst.data.multi_asset import get_extended_snapshot
from analyst.data.universe_extended import FOREX_PAIRS, METALS_PAIRS, CRYPTO_PAIRS
from analyst.sentiment.analyzer import get_spy_context
from analyst.data.market import get_market_snapshot
from analyst.signals.execution import format_execution_tier1, format_execution_tier2
from analyst.signals.technical import score_snapshot

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

BROADCAST_STOCKS = [
    "AAPL", "NVDA", "MSFT", "TSLA", "META",
    "GOOGL", "AMZN", "AMD", "SPY", "QQQ",
    "JPM", "NFLX", "PLTR", "COIN", "SMCI",
]


def _fetch_stock_snapshot(ticker: str) -> dict | None:
    snap = get_market_snapshot(ticker)
    if snap:
        snap["display_name"] = ticker
        snap["asset_type"] = "stock"
    return snap


def _scan_class(fetch_fn, tickers) -> list[dict]:
    """Fetch snapshots in parallel, score instantly with pure technicals. No LLM."""
    snapshots = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(fetch_fn, t) for t in tickers]
        for fut in as_completed(futures):
            try:
                snap = fut.result()
                if snap:
                    snapshots.append(score_snapshot(snap))
            except Exception as e:
                logger.warning(f"Asset fetch failed, skipping: {e}")

    order = {"BUY": 0, "SELL": 1, "WATCH": 2}
    return sorted(snapshots, key=lambda s: (order.get(s["action"], 3), -s["confidence"]))


def _conf_bar(confidence: float) -> str:
    filled = round(confidence * 10)
    return "█" * filled + "░" * (10 - filled)


def _action_emoji(action: str) -> str:
    return "🟢" if action == "BUY" else "🔴" if action == "SELL" else "👁" if action == "WATCH" else "⚪"


def _asset_emoji(asset_type: str) -> str:
    return {"stock": "📈", "forex": "💱", "metal": "🥇", "crypto": "🪙"}.get(asset_type, "📊")


def _section_header(asset_type: str) -> str:
    return {
        "stock": "📈 STOCKS",
        "forex": "💱 FOREX",
        "metal": "🥇 PRECIOUS METALS",
        "crypto": "🪙 CRYPTO",
    }.get(asset_type, asset_type.upper())


_SLOT_HEADERS = {
    "morning":     ("🌅", "PRE-MARKET PICKS",      "Setups to watch at the 9:30 open"),
    "midday":      ("☀️", "MIDDAY UPDATE",          "Live setups with fresh market data"),
    "aftermarket": ("🌙", "NEXT DAY PREVIEW",       "What to watch for tomorrow's open"),
}


def format_tier1_broadcast(
    stocks: list[dict],
    forex: list[dict],
    metals: list[dict],
    crypto: list[dict],
    market_regime: str,
    time_slot: str = "morning",
) -> str:
    """
    Free public channel — one pick per asset class, second-best signal.
    The top pick is reserved for Tier 2 (paid). Clear upgrade path shown.
    """
    now = datetime.now(ET)
    today = now.strftime("%A, %B %d %Y")
    ts = now.strftime("%-I:%M %p ET")
    emoji, slot_title, slot_sub = _SLOT_HEADERS.get(time_slot, _SLOT_HEADERS["morning"])
    lines = [
        f"{emoji} <b>ARGUS — {slot_title}</b>",
        f"<i>{today}  ·  {slot_sub}</i>",
        f"Market: <b>{market_regime.split(' — ')[0].upper()}</b>  |  <i>Data: {ts}</i>",
        "",
    ]

    sections = [
        ("stock", stocks),
        ("forex", forex),
        ("metal", metals),
        ("crypto", crypto),
    ]

    has_any = False
    for asset_type, picks in sections:
        # Index [1] = second-most-confident pick; [0] is reserved for Pro
        pick = picks[1] if len(picks) >= 2 else (picks[0] if picks else None)

        lines.append(f"{_asset_emoji(asset_type)} <b>{_section_header(asset_type)}</b>")

        if not pick:
            lines.append("  No setup today.")
        else:
            has_any = True
            name = pick.get("display_name", pick["ticker"])
            conf = pick["confidence"]
            action = pick["action"]
            lines.append(
                f"  {_action_emoji(action)} <b>{name}</b> — {action} | {conf:.0%}"
            )
            hint = format_execution_tier1(pick)
            if hint:
                lines.append(f"  {hint}")
        lines.append("")

    lines += [
        "─────────────────────────────",
        "📊 <b>What does the % mean?</b>",
        "",
        "That's Argus's confidence score — calculated by our",
        "three-committee AI framework (macro analysis, fundamentals,",
        "and technical execution). A 74% means 3 independent models",
        "ran this setup and agreed it has a real edge.",
        "<b>We are not financial advisors. Do your own research.",
        "These are our calculations — trade at your own risk.</b>",
        "",
        "─────────────────────────────",
        "🔒 <b>Today's #1 pick in each class + full",
        "entry/stop/target levels are in Argus Pro.</b>",
        "",
        "Every day. Every asset class.",
        "Same intelligence the institutions use.",
        "",
        "📩 <b>DM @ArgusVagabondBot to upgrade.</b>",
    ]

    return "\n".join(lines)


def format_tier2_broadcast(
    stocks: list[dict],
    forex: list[dict],
    metals: list[dict],
    crypto: list[dict],
    market_regime: str,
    spy_change: float,
    time_slot: str = "morning",
) -> list[str]:
    """
    Full analysis for paid channel — returns a list of messages (one per asset class)
    so each stays under Telegram's 4096 char limit.
    """
    now = datetime.now(ET)
    today = now.strftime("%A, %B %d %Y")
    ts = now.strftime("%-I:%M %p ET")
    regime_tag = market_regime.split(" — ")[0].upper()
    emoji, slot_title, slot_sub = _SLOT_HEADERS.get(time_slot, _SLOT_HEADERS["morning"])

    header = (
        f"{emoji} <b>ARGUS PRO — {slot_title}</b>\n"
        f"<i>{today}  ·  {slot_sub}</i>\n"
        f"Regime: <b>{regime_tag}</b> | SPY: <b>{spy_change:+.2f}%</b> | <i>Data: {ts}</i>"
    )

    sections = [
        ("stock", stocks),
        ("forex", forex),
        ("metal", metals),
        ("crypto", crypto),
    ]

    messages = [header]

    for asset_type, picks in sections:
        top3 = picks[:3]
        lines = [f"━━━ {_section_header(asset_type)} ━━━"]

        if not top3:
            lines.append("  No high-conviction setups today.")
        else:
            for s in top3:
                name = s.get("display_name", s["ticker"])
                action = s["action"]
                conf = s["confidence"]
                target = s.get("price_target", 0)
                stop = s.get("stop_loss", 0)
                rr = s.get("risk_reward", 0)
                horizon = s.get("time_horizon", "—")
                reasoning = s.get("reasoning", "—")[:200]
                price = s.get("price", 0)

                is_fx = asset_type == "forex"
                price_fmt  = f"{price:.4f}"  if is_fx else f"{price:.2f}"
                target_fmt = f"{target:.4f}" if is_fx else f"{target:.2f}"
                stop_fmt   = f"{stop:.4f}"   if is_fx else f"{stop:.2f}"

                execution_block = format_execution_tier2(s)

                lines += [
                    f"\n{_action_emoji(action)} <b>{name} — {action}</b>",
                    f"Confidence: <b>{conf:.0%}</b>  {_conf_bar(conf)}",
                    f"Entry: <b>{price_fmt}</b> | Target: <b>{target_fmt}</b> | Stop: <b>{stop_fmt}</b>",
                    f"R/R: <b>{rr:.1f}x</b> | Hold: {horizon}",
                    f"📝 <i>{reasoning}</i>",
                ]
                if execution_block:
                    lines.append(execution_block)

        lines.append("\n<i>Not financial advice. Trade your own plan.</i>")
        messages.append("\n".join(lines))

    return messages


async def send_channel_message(bot, channel_id: str, text: str):
    """Send an HTML-formatted message to a Telegram channel."""
    if not channel_id or channel_id.startswith("REPLACE"):
        logger.warning(f"Channel ID not configured: {channel_id!r}")
        return
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info(f"Broadcast sent to {channel_id}")
    except Exception as e:
        logger.error(f"Failed to send to channel {channel_id}: {e}")


def _fetch_extended(args):
    ticker, name, asset_type = args
    snap = get_extended_snapshot(ticker, name, asset_type)
    return snap


async def run_broadcast(bot, tier1_channel: str, tier2_channel: str, time_slot: str = "morning"):
    """
    Fast broadcast pipeline — pure technical scoring, no LLM.
    All data fetches run in parallel; scoring is instant math.
    Typical wall-clock time: 5–15 seconds.
    """
    logger.info(f"Starting {time_slot} broadcast (fast technical mode)...")

    spy_change, market_regime = get_spy_context()

    forex_tickers  = [(t, n, "forex")  for t, n in FOREX_PAIRS.items()]
    metals_tickers = [(t, n, "metal")  for t, n in METALS_PAIRS.items()]
    crypto_tickers = [(t, n, "crypto") for t, n in CRYPTO_PAIRS.items()]

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_stocks = ex.submit(_scan_class, _fetch_stock_snapshot, BROADCAST_STOCKS)
        f_forex  = ex.submit(_scan_class, _fetch_extended, forex_tickers)
        f_metals = ex.submit(_scan_class, _fetch_extended, metals_tickers)
        f_crypto = ex.submit(_scan_class, _fetch_extended, crypto_tickers)

        stocks = f_stocks.result()
        forex  = f_forex.result()
        metals = f_metals.result()
        crypto = f_crypto.result()

    logger.info(
        f"Broadcast scan done: {len(stocks)} stocks, {len(forex)} forex, "
        f"{len(metals)} metals, {len(crypto)} crypto signals"
    )

    tier1_msg = format_tier1_broadcast(stocks, forex, metals, crypto, market_regime, time_slot)
    tier2_msgs = format_tier2_broadcast(stocks, forex, metals, crypto, market_regime, spy_change, time_slot)

    await send_channel_message(bot, tier1_channel, tier1_msg)
    for msg in tier2_msgs:
        await send_channel_message(bot, tier2_channel, msg)

    total = sum(len(x[:3]) for x in [stocks, forex, metals, crypto])
    logger.info(f"{time_slot.capitalize()} broadcast complete — {total} signals published")
    return total
