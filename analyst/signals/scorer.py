import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

from analyst.data.universe import get_core_universe, get_full_universe
from analyst.data.universe_extended import FOREX_PAIRS, METALS_PAIRS, CRYPTO_PAIRS
from analyst.data.screener import run_prescreen, filter_by_market_regime
from analyst.data.market import get_market_snapshot
from analyst.data.multi_asset import get_extended_snapshot
from analyst.data.social_aggregator import get_all_social_tickers
from analyst.sentiment.analyzer import get_spy_context
from analyst.signals.technical import score_snapshot
from shared.database import save_signal, get_todays_signals, get_conn
from shared.config import config

logger = logging.getLogger(__name__)


def is_market_hours() -> bool:
    now = datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_time <= now <= close_time


def is_premarket() -> bool:
    now = datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    return now.replace(hour=7, minute=0) <= now < now.replace(hour=9, minute=30)


def recently_analyzed(ticker: str, hours: int = 4) -> bool:
    """Return True if this ticker was already scored within the last N hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM signals WHERE ticker=? AND generated_at>=?",
            (ticker, cutoff)
        ).fetchone()
    return row is not None


def same_signal_exists(ticker: str, action: str, hours: int = 8) -> bool:
    """True if this ticker already has a same-direction signal saved within N hours.
    Prevents saving 10 copies of 'BNB SELL' across overnight scan cycles.
    A direction flip (SELL→BUY) always saves — that's a real change worth recording.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM signals WHERE ticker=? AND action=? AND generated_at>=?",
            (ticker, action, cutoff)
        ).fetchone()
    return row is not None


def get_weekly_signal_count() -> int:
    """How many signals have we already committed to this week (ET week boundary)."""
    today = datetime.now(_ET).date()
    monday = today - timedelta(days=today.weekday())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM signals WHERE executed=1 AND date(generated_at)>=?",
            (monday.isoformat(),)
        ).fetchone()
    return row["cnt"] if row else 0


def run_scan(full_universe: bool = False) -> list[dict]:
    """
    Full scan pipeline:
    1. Load universe (core or full)
    2. Pre-screen for activity (fast, rule-based)
    3. Adjust for market regime (SPY direction)
    4. Deep technical analysis on candidates
    5. LLM veteran scoring
    6. Save and notify on actionable signals

    Only analyzes tickers not already seen today.
    Stops early if weekly trade limit is reached.
    """
    weekly_count = get_weekly_signal_count()
    if weekly_count >= config.MAX_TRADES_PER_WEEK:
        logger.info(f"Weekly trade limit reached ({weekly_count}). No new signals needed.")
        return []

    # Step 1: Universe — skip tickers scored in the last 4 hours
    tickers = get_full_universe() if full_universe else get_core_universe()
    tickers = [t for t in tickers if not recently_analyzed(t, hours=4)]

    if not tickers:
        logger.info("All tickers already analyzed today.")
        return []

    # Step 2: Pre-screen
    candidates = run_prescreen(tickers)
    if not candidates:
        logger.info("No candidates passed pre-screen.")
        return []

    # Step 3: SPY regime filter
    spy_change, market_regime = get_spy_context()
    candidates = filter_by_market_regime(candidates, spy_change)
    logger.info(f"Scoring {len(candidates)} candidates (SPY: {spy_change:+.1f}%, {market_regime})")

    new_signals = []
    trade_date = datetime.now(timezone.utc).date().isoformat()

    # Step 4: Fetch all snapshots in parallel, score with pure technicals (no LLM)
    tickers_map = {c["ticker"]: c for c in candidates}
    snapshots: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(get_market_snapshot, t): t for t in tickers_map}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                snap = fut.result()
                if snap:
                    snap["asset_type"] = "stock"
                    snap["spy_change"] = spy_change
                    snapshots[ticker] = snap
            except Exception as e:
                logger.warning(f"Snapshot failed for {ticker}: {e}")

    logger.info(f"Snapshots fetched: {len(snapshots)}/{len(candidates)}")

    # Step 5a: Pull social conviction once for the whole scan (cached per day)
    try:
        social_map = {s["ticker"]: s for s in get_all_social_tickers(min_mentions=2)}
    except Exception as e:
        logger.warning(f"Social scan failed, continuing without it: {e}")
        social_map = {}

    # Step 5b: Score each snapshot, apply social modifier
    for ticker, snapshot in snapshots.items():
        signal = score_snapshot(snapshot)

        action = signal.get("action", "WATCH")
        confidence = signal.get("confidence", 0.0)
        risk_reward = signal.get("risk_reward", 0.0)

        # Social modifier: cross-platform buzz adjusts confidence ±0.04
        social = social_map.get(ticker)
        if social:
            sent = social.get("sentiment_label", "neutral")
            cross = social.get("cross_platform", False)
            boost = 0.04 if cross else 0.02
            if (action == "BUY" and sent == "bullish") or (action == "SELL" and sent == "bearish"):
                confidence = min(confidence + boost, 0.88)
                signal["reasoning"] += f" Social: {sent} ({', '.join(social['platforms'])})."
            elif (action == "BUY" and sent == "bearish") or (action == "SELL" and sent == "bullish"):
                confidence = max(confidence - boost, 0.50)
                signal["reasoning"] += f" ⚠️ Social headwind: {sent} sentiment on {', '.join(social['platforms'])}."
            signal["confidence"] = round(confidence, 2)

        # Update signals analyzed count
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO daily_stats (trade_date, signals_analyzed)
                VALUES (?, 1)
                ON CONFLICT(trade_date) DO UPDATE SET signals_analyzed = signals_analyzed + 1
            """, (trade_date,))

        # Minimum floors: WATCH needs conf ≥ 0.62; BUY/SELL need conf ≥ 0.60 and R/R ≥ 1.2
        below_floor = (
            (action == "WATCH" and confidence < 0.62) or
            (action in ("BUY", "SELL") and (confidence < 0.60 or risk_reward < 1.2))
        )
        if below_floor:
            logger.info(f"PASS: {ticker} | {action} | conf={confidence:.0%} | R/R={risk_reward:.1f}")
            with get_conn() as conn:
                conn.execute("""
                    INSERT INTO daily_stats (trade_date, signals_rejected)
                    VALUES (?, 1)
                    ON CONFLICT(trade_date) DO UPDATE SET signals_rejected = signals_rejected + 1
                """, (trade_date,))
            continue

        save_signal(
            ticker=ticker,
            action=action,
            confidence=confidence,
            price_target=signal.get("price_target", snapshot["price"]),
            stop_loss=signal.get("stop_loss", snapshot["price"] * 0.98),
            reasoning=signal.get("reasoning", ""),
            asset_type="stock",
        )
        new_signals.append(signal)

        logger.info(
            f"SIGNAL: {ticker} {action} | conf={confidence:.0%} | "
            f"R/R={risk_reward:.1f} | {signal.get('setup_type','')}"
        )

    # Step 6: Route signals by confidence tier
    import httpx

    above_threshold = [s for s in new_signals if s["confidence"] >= config.CONFIDENCE_THRESHOLD]
    audit_candidates = [
        s for s in new_signals
        if 0.70 <= s["confidence"] < config.CONFIDENCE_THRESHOLD
    ]

    # Signals at 70-75% — forward to executor for independent audit (no notification — logged only)
    for s in audit_candidates:
        logger.info(f"Forwarding {s['ticker']} ({s['confidence']:.0%}) to executor audit")
        try:
            httpx.post(
                f"http://{config.EXECUTOR_HOST}:{config.EXECUTOR_PORT}/audit",
                headers={"Authorization": f"Bearer {config.MASTER_KEY}"},
                json={
                    "ticker": s["ticker"],
                    "action": s["action"],
                    "confidence": s["confidence"],
                    "price_target": s.get("price_target", 0),
                    "stop_loss": s.get("stop_loss", 0),
                    "risk_reward": s.get("risk_reward", 0),
                    "setup_type": s.get("setup_type", "unknown"),
                    "reasoning": s.get("reasoning", ""),
                    "red_flags": s.get("red_flags", "none"),
                },
                timeout=120,
            )
        except Exception as e:
            logger.error(f"Failed to send {s['ticker']} to executor audit: {e}")

    logger.info(
        f"Scan done: {len(new_signals)} signals saved, "
        f"{len(above_threshold)} above threshold, {len(audit_candidates)} sent to audit"
    )
    return new_signals


def run_extended_scan() -> list[dict]:
    """
    24/7 scan of crypto, forex, and metals.
    Uses pure technical scoring — no LLM, no pre-screen needed.
    Re-scans each asset every 2 hours so overnight moves are caught.
    """
    spy_change, _ = get_spy_context()
    trade_date = datetime.now(timezone.utc).date().isoformat()

    all_assets: dict[str, tuple[str, str]] = {}
    for ticker, name in CRYPTO_PAIRS.items():
        all_assets[ticker] = (name, "crypto")
    for ticker, name in FOREX_PAIRS.items():
        all_assets[ticker] = (name, "forex")
    for ticker, name in METALS_PAIRS.items():
        all_assets[ticker] = (name, "metal")

    # Skip assets scored within the last 2 hours
    to_scan = {t: v for t, v in all_assets.items() if not recently_analyzed(t, hours=2)}
    if not to_scan:
        logger.info("Extended scan: all assets scored recently — skipping")
        return []

    logger.info(f"Extended scan: {len(to_scan)} assets (crypto/forex/metals)")

    def _fetch(ticker_name_type):
        ticker, (name, asset_type) = ticker_name_type
        try:
            snap = get_extended_snapshot(ticker, name, asset_type)
            if snap:
                snap["spy_change"] = spy_change
            return snap
        except Exception as e:
            logger.warning(f"Extended snapshot failed for {ticker}: {e}")
            return None

    new_signals = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_fetch, item): item[0] for item in to_scan.items()}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                snap = fut.result()
                if not snap:
                    continue

                signal = score_snapshot(snap)
                action = signal["action"]
                confidence = signal["confidence"]

                with get_conn() as conn:
                    conn.execute("""
                        INSERT INTO daily_stats (trade_date, signals_analyzed)
                        VALUES (?, 1)
                        ON CONFLICT(trade_date) DO UPDATE SET signals_analyzed = signals_analyzed + 1
                    """, (trade_date,))

                # Minimum floor: 0.62 for all signal types — cuts pure noise
                if confidence >= 0.62:
                    if same_signal_exists(ticker, action, hours=8):
                        logger.debug(f"Skip duplicate: {ticker} {action} already saved within 8h")
                    else:
                        save_signal(
                            ticker=ticker,
                            action=action,
                            confidence=confidence,
                            price_target=signal["price_target"],
                            stop_loss=signal["stop_loss"],
                            reasoning=signal["reasoning"],
                            asset_type=signal["asset_type"],
                        )
                        new_signals.append(signal)
                        logger.info(f"SIGNAL [{signal['asset_type'].upper()}]: {ticker} {action} | conf={confidence:.0%}")
                else:
                    with get_conn() as conn:
                        conn.execute("""
                            INSERT INTO daily_stats (trade_date, signals_rejected)
                            VALUES (?, 1)
                            ON CONFLICT(trade_date) DO UPDATE SET signals_rejected = signals_rejected + 1
                        """, (trade_date,))

            except Exception as e:
                logger.error(f"Extended scan error for {ticker}: {e}")

    above_threshold = [s for s in new_signals if s["confidence"] >= config.CONFIDENCE_THRESHOLD]
    logger.info(f"Extended scan done: {len(new_signals)} signals, {len(above_threshold)} above threshold")
    return new_signals
