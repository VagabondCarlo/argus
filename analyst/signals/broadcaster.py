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

_RISK_DISCLOSURE = (
    "⚠️ <b>RISK DISCLOSURE</b>\n"
    "These are algorithmic signals for <b>educational purposes only</b>. "
    "Argus is <b>NOT a licensed financial advisor</b>. Nothing here is financial advice. "
    "You may lose money. Only trade capital you can afford to lose entirely. "
    "Past signals do not guarantee future results. Always do your own research."
)

_HOW_TO_USE = (
    "📋 <b>How to use these signals:</b>\n"
    "1️⃣ Enter near the <b>Entry</b> price\n"
    "2️⃣ Place a <b>stop-loss order</b> at the Stop price in your broker <b>immediately</b> — this is your protection\n"
    "3️⃣ Set a take-profit at the <b>Target</b> price (optional — close manually when target approaches)\n"
    "💰 <b>Size your position so the stop-loss costs no more than 1-2% of your total account</b>\n"
    "   Example: $10,000 account → max $100-200 risk per trade"
)


def format_tier1_broadcast(
    stocks: list[dict],
    forex: list[dict],
    metals: list[dict],
    crypto: list[dict],
    market_regime: str,
    time_slot: str = "morning",
) -> str:
    """
    Free public channel — same visual language as the track-record cards:
    tight monospace watchlist, the system's ACTUAL top pick per class (levels
    are the paid gate, not the ranking), and the running record on every post
    so no single message can cherry-pick. One-line disclaimer; the long
    disclosure lives in the pinned post.
    """
    from shared.database import get_win_rate, get_conn

    now = datetime.now(ET)
    emoji, slot_title, slot_sub = _SLOT_HEADERS.get(time_slot, _SLOT_HEADERS["morning"])
    regime = market_regime.split(" — ")[0].upper()

    lines = [
        f"{emoji} <b>ARGUS — {now.strftime('%a %b %d')}</b>",
        f"<i>{slot_sub} · {regime} · {now.strftime('%-I:%M %p ET')}</i>",
        "",
    ]

    picks = []
    for asset_type, cls in (("stock", stocks), ("crypto", crypto),
                            ("metal", metals), ("forex", forex)):
        top = next((p for p in cls if p["action"] in ("BUY", "SELL")), None)
        if top:
            picks.append((asset_type, top))

    if picks:
        lines.append("Top of the watchlist:")
        for asset_type, p in picks:
            name = (p.get("display_name") or p["ticker"])[:7]
            lines.append(
                f"<code>{_asset_emoji(asset_type)} {name:<7} {p['action']:<4} "
                f"{_conf_bar(p['confidence'])} {p['confidence']:.0%}</code>"
            )
    else:
        lines.append("<i>No setups worth watching right now — that's information too.</i>")

    record = get_win_rate()
    with get_conn() as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM trades WHERE status='open'"
        ).fetchone()["c"]
    total = record["total_trades"]
    rec = (
        f"{record['wins']}W-{record['losses']}L · "
        f"{'+' if record['total_pnl'] >= 0 else '-'}${abs(record['total_pnl']):,.2f}"
        if total else "building"
    )
    lines += [
        "",
        f"<code>live {open_count} open · record {rec}</code>",
        "",
        "<i>educational · not financial advice · paper record, every trade posted</i>",
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
        f"Regime: <b>{regime_tag}</b> | SPY: <b>{spy_change:+.2f}%</b> | <i>Data: {ts}</i>\n\n"
        + _RISK_DISCLOSURE
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

                action_verb = "BUY" if action == "BUY" else "SELL/EXIT"
                stop_dir    = "below" if action == "BUY" else "above"
                lines += [
                    f"\n{_action_emoji(action)} <b>{name} — {action}</b>",
                    f"Confidence: <b>{conf:.0%}</b>  {_conf_bar(conf)}",
                    f"Entry: ~<b>{price_fmt}</b> | Target: <b>{target_fmt}</b> | Stop: <b>{stop_fmt}</b> | R/R: <b>{rr:.1f}x</b>",
                    f"<b>Steps:</b> 1️⃣ {action_verb} near {price_fmt}  "
                    f"2️⃣ Set stop-loss {stop_dir} <b>{stop_fmt}</b> immediately  "
                    f"3️⃣ Take-profit at <b>{target_fmt}</b>",
                    f"📝 <i>{reasoning[:180]}</i>",
                ]
                if execution_block:
                    lines.append(execution_block)

        lines += [
            "",
            _HOW_TO_USE,
        ]
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
