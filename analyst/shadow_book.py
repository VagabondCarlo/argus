"""Shadow book — virtual outcome scoring for signals we deliberately don't trade.

The executor only trades >=0.72 (the replay-proven band). Everything the
analyst saves below that still carries an entry, stop, and target — so each
night this job replays the untraded signals against actual 15-min price
history and records whether they WOULD have won. Full calibration data,
zero real losses, nothing on the public record.

Resolution rules match the original replay: stop and target hit in the same
bar counts as a loss (conservative). Signals unresolved after MAX_AGE_DAYS
are recorded as 'expired' at their last close.

Run nightly via launchd (com.argus.shadowbook), or manually:
    venv/bin/python -m analyst.shadow_book
"""
import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

from shared.database import get_conn, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shadow_book")

MIN_AGE_HOURS = 2      # give a signal time to play out before first scoring
MAX_AGE_DAYS = 3       # unresolved after this = expired at last close
MIN_CONFIDENCE = 0.62


def resolve_from_bars(bars, action: str, stop: float, target: float):
    """Walk (high, low, close) bars; return (outcome, exit_price) or (None, last_close).

    outcome: 'win' | 'loss' | None (still open). Ambiguous bars = loss.
    """
    last_close = None
    is_buy = action == "BUY"
    for high, low, close in bars:
        last_close = close
        hit_stop = (low <= stop) if is_buy else (high >= stop)
        hit_target = (high >= target) if is_buy else (low <= target)
        if hit_stop:                      # includes ambiguous both-hit bars
            return "loss", stop
        if hit_target:
            return "win", target
    return None, last_close


def _eligible_signals(conn):
    now = datetime.now(timezone.utc)
    newest = (now - timedelta(hours=MIN_AGE_HOURS)).isoformat()
    oldest = (now - timedelta(days=7)).isoformat()
    return conn.execute("""
        SELECT s.id, s.ticker, s.action, s.confidence, s.asset_type,
               s.entry_price, s.stop_loss, s.price_target, s.generated_at
        FROM signals s
        LEFT JOIN virtual_outcomes v ON v.signal_id = s.id
        WHERE v.signal_id IS NULL
        AND s.executed = 0
        AND s.action IN ('BUY', 'SELL')
        AND s.confidence >= ?
        AND s.generated_at BETWEEN ? AND ?
        AND s.entry_price IS NOT NULL
        AND s.stop_loss IS NOT NULL
        AND s.price_target IS NOT NULL
    """, (MIN_CONFIDENCE, oldest, newest)).fetchall()


def run():
    init_db()
    with get_conn() as conn:
        signals = _eligible_signals(conn)
    if not signals:
        logger.info("Shadow book: nothing to score")
        return

    logger.info(f"Shadow book: scoring {len(signals)} untraded signals")
    by_ticker: dict[str, list] = {}
    for s in signals:
        by_ticker.setdefault(s["ticker"], []).append(s)

    now = datetime.now(timezone.utc)
    resolved = []
    for ticker, sigs in by_ticker.items():
        try:
            df = yf.download(ticker, interval="15m", period="8d", progress=False)
            if df is None or not len(df):
                continue
            import pandas as pd
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            idx = df.index
            df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
        except Exception as e:
            logger.warning(f"Shadow book: no data for {ticker}: {e}")
            continue

        for s in sigs:
            ts = datetime.fromisoformat(s["generated_at"])
            fut = df[df.index > ts]
            if not len(fut):
                continue
            bars = list(zip(fut["High"], fut["Low"], fut["Close"]))
            outcome, exit_price = resolve_from_bars(
                bars, s["action"], s["stop_loss"], s["price_target"]
            )
            age_days = (now - ts).days
            if outcome is None:
                if age_days < MAX_AGE_DAYS:
                    continue  # still open — retry tomorrow
                outcome = "expired"
            entry = s["entry_price"]
            risk = abs(entry - s["stop_loss"])
            if risk <= 0 or exit_price is None:
                continue
            r = ((exit_price - entry) if s["action"] == "BUY" else (entry - exit_price)) / risk
            resolved.append((
                s["id"], s["ticker"], s["action"], s["confidence"], s["asset_type"],
                entry, s["stop_loss"], s["price_target"], outcome,
                round(float(exit_price), 6), round(float(r), 3),
                now.isoformat(),
            ))

    if resolved:
        with get_conn() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO virtual_outcomes
                (signal_id, ticker, action, confidence, asset_type, entry, stop,
                 target, outcome, exit_price, r_multiple, resolved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, resolved)
    logger.info(f"Shadow book: recorded {len(resolved)} outcomes")

    # Band summary — the whole point of the exercise
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT CASE WHEN confidence >= 0.72 THEN '0.72+'
                        WHEN confidence >= 0.66 THEN '0.66-0.72'
                        ELSE '0.62-0.66' END band,
                   COUNT(*) n,
                   SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) wins,
                   ROUND(SUM(r_multiple), 2) total_r
            FROM virtual_outcomes GROUP BY band ORDER BY band
        """).fetchall()
    for row in rows:
        logger.info(
            f"  band {row['band']}: n={row['n']} wins={row['wins']} totalR={row['total_r']}"
        )


if __name__ == "__main__":
    run()
