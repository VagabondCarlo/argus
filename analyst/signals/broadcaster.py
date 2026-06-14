"""
Daily multi-asset broadcast engine.
Scans 4 asset classes, picks top 3 from each, and sends to Tier 1 + Tier 2 channels.

Tier 1 (free, public): clean pick list — ticker, direction, confidence
Tier 2 (paid, private): full analysis — entry, target, stop, R/R, committee reasoning
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from analyst.data.multi_asset import scan_forex, scan_metals, scan_crypto, fetch_asset_news
from analyst.sentiment.analyzer_extended import analyze_extended
from analyst.sentiment.analyzer import get_spy_context
from analyst.data.market import get_market_snapshot
from analyst.data.news import fetch_news, format_news_for_prompt
from analyst.sentiment.analyzer import analyze_ticker

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Top 15 liquid stocks scanned for the daily broadcast (separate from full trading scan)
BROADCAST_STOCKS = [
    "AAPL", "NVDA", "MSFT", "TSLA", "META",
    "GOOGL", "AMZN", "AMD", "SPY", "QQQ",
    "JPM", "NFLX", "PLTR", "COIN", "SMCI",
]


def _analyze_asset(snapshot: dict, spy_change: float, market_regime: str) -> dict | None:
    """Thread worker: fetch news + run LLM on one asset."""
    ticker = snapshot["ticker"]
    asset_type = snapshot.get("asset_type")
    try:
        if asset_type:
            news_text = fetch_asset_news(ticker)
            return analyze_extended(snapshot, news_text, spy_change, market_regime)
        else:
            from analyst.data.news import fetch_news, format_news_for_prompt
            news = fetch_news(ticker)
            news_text = format_news_for_prompt(news)
            signal = analyze_ticker(snapshot, news_text, spy_change, market_regime)
            if signal:
                signal["display_name"] = ticker
                signal["asset_type"] = "stock"
                signal["price"] = snapshot["price"]
            return signal
    except Exception as e:
        logger.error(f"Error analyzing {ticker}: {e}")
        return None


def _scan_class(snapshots: list[dict], spy_change: float, market_regime: str, max_workers: int = 4) -> list[dict]:
    """Scan a list of snapshots concurrently and return actionable signals sorted by confidence."""
    signals = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_analyze_asset, s, spy_change, market_regime): s for s in snapshots}
        for fut in as_completed(futures):
            result = fut.result()
            if result and result.get("action") != "HOLD" and result.get("confidence", 0) >= 0.60:
                signals.append(result)

    return sorted(signals, key=lambda s: s["confidence"], reverse=True)


def _scan_broadcast_stocks(spy_change: float, market_regime: str) -> list[dict]:
    """Quick scan of top liquid stocks for broadcast picks."""
    snapshots = []
    for ticker in BROADCAST_STOCKS:
        snap = get_market_snapshot(ticker)
        if snap:
            snapshots.append(snap)
    return _scan_class(snapshots, spy_change, market_regime)


def _conf_bar(confidence: float) -> str:
    filled = round(confidence * 10)
    return "█" * filled + "░" * (10 - filled)


def _action_emoji(action: str) -> str:
    return "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"


def _asset_emoji(asset_type: str) -> str:
    return {"stock": "📈", "forex": "💱", "metal": "🥇", "crypto": "🪙"}.get(asset_type, "📊")


def _section_header(asset_type: str) -> str:
    return {
        "stock": "📈 STOCKS",
        "forex": "💱 FOREX",
        "metal": "🥇 PRECIOUS METALS",
        "crypto": "🪙 CRYPTO",
    }.get(asset_type, asset_type.upper())


def format_tier1_broadcast(
    stocks: list[dict],
    forex: list[dict],
    metals: list[dict],
    crypto: list[dict],
    market_regime: str,
) -> str:
    """
    Free public channel — one pick per asset class, second-best signal.
    The top pick is reserved for Tier 2 (paid). Clear upgrade path shown.
    """
    today = datetime.now(ET).strftime("%A, %B %d %Y")
    lines = [
        f"🎯 <b>ARGUS DAILY SIGNALS</b>",
        f"<i>{today}</i>",
        f"Market: <b>{market_regime.split(' — ')[0].upper()}</b>",
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
) -> str:
    """
    Full analysis format for the paid private channel.
    All levels, R/R, and committee reasoning.
    """
    today = datetime.now(ET).strftime("%A, %B %d %Y")
    regime_tag = market_regime.split(" — ")[0].upper()

    lines = [
        f"🎯 <b>ARGUS PRO — DAILY SIGNAL REPORT</b>",
        f"<i>{today}</i>",
        f"Market regime: <b>{regime_tag}</b> | SPY: <b>{spy_change:+.2f}%</b>",
        "",
    ]

    sections = [
        ("stock", stocks),
        ("forex", forex),
        ("metal", metals),
        ("crypto", crypto),
    ]

    for asset_type, picks in sections:
        top3 = picks[:3]
        lines.append(f"━━━ {_section_header(asset_type)} ━━━")

        if not top3:
            lines.append("  No high-conviction setups today.\n")
            continue

        for s in top3:
            name = s.get("display_name", s["ticker"])
            action = s["action"]
            conf = s["confidence"]
            target = s.get("price_target", 0)
            stop = s.get("stop_loss", 0)
            rr = s.get("risk_reward", 0)
            setup = s.get("setup_type", "—")
            horizon = s.get("time_horizon", "—")
            reasoning = s.get("reasoning", "—")
            red_flags = s.get("red_flags", "none")
            price = s.get("price", 0)

            price_fmt = f"{price:.4f}" if asset_type == "forex" else f"{price:.2f}"
            target_fmt = f"{target:.4f}" if asset_type == "forex" else f"{target:.2f}"
            stop_fmt = f"{stop:.4f}" if asset_type == "forex" else f"{stop:.2f}"

            lines += [
                f"\n{_action_emoji(action)} <b>{name} — {action}</b>",
                f"Confidence: <b>{conf:.0%}</b>  {_conf_bar(conf)}",
                f"Entry: <b>{price_fmt}</b> | Target: <b>{target_fmt}</b> | Stop: <b>{stop_fmt}</b>",
                f"R/R: <b>{rr:.1f}x</b> | Setup: {setup} | Hold: {horizon}",
                f"",
                f"📝 <i>{reasoning}</i>",
            ]
            if red_flags and red_flags.lower() != "none":
                lines.append(f"⚠️ <i>{red_flags}</i>")
            lines.append("")

    lines += [
        "─────────────────────────",
        "<i>⚠️ Argus Pro — Institutional-quality analysis.</i>",
        "<i>Not financial advice. Trade your own plan.</i>",
    ]

    return "\n".join(lines)


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


async def run_broadcast(bot, tier1_channel: str, tier2_channel: str):
    """
    Full broadcast pipeline:
    1. Get SPY context
    2. Scan stocks, forex, metals, crypto concurrently
    3. Format Tier 1 + Tier 2 messages
    4. Send to both channels
    """
    logger.info("Starting daily multi-asset broadcast scan...")

    spy_change, market_regime = get_spy_context()

    # Scan all 4 asset classes concurrently using threads
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_stocks = ex.submit(_scan_broadcast_stocks, spy_change, market_regime)
        f_forex = ex.submit(lambda: _scan_class(scan_forex(), spy_change, market_regime))
        f_metals = ex.submit(lambda: _scan_class(scan_metals(), spy_change, market_regime))
        f_crypto = ex.submit(lambda: _scan_class(scan_crypto(), spy_change, market_regime))

        stocks = f_stocks.result()
        forex = f_forex.result()
        metals = f_metals.result()
        crypto = f_crypto.result()

    logger.info(
        f"Broadcast scan done: {len(stocks)} stocks, {len(forex)} forex, "
        f"{len(metals)} metals, {len(crypto)} crypto signals"
    )

    tier1_msg = format_tier1_broadcast(stocks, forex, metals, crypto, market_regime)
    tier2_msg = format_tier2_broadcast(stocks, forex, metals, crypto, market_regime, spy_change)

    await send_channel_message(bot, tier1_channel, tier1_msg)
    await send_channel_message(bot, tier2_channel, tier2_msg)

    total = sum(len(x[:3]) for x in [stocks, forex, metals, crypto])
    logger.info(f"Daily broadcast complete — {total} signals sent to both channels")
    return total
