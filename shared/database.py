import sqlite3
import os
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "argus.db")


def _utc_today() -> str:
    """Current date in UTC — always consistent with generated_at timestamps."""
    return datetime.now(timezone.utc).date().isoformat()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                action      TEXT NOT NULL,
                confidence  REAL NOT NULL,
                price_target REAL,
                stop_loss   REAL,
                reasoning   TEXT,
                generated_at TEXT NOT NULL,
                executed    INTEGER DEFAULT 0,
                asset_type  TEXT DEFAULT 'stock',
                entry_price REAL
            );

            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id   INTEGER REFERENCES signals(id),
                order_id    TEXT,
                fill_price  REAL,
                quantity    REAL,
                executed_at TEXT,
                closed_at   TEXT,
                close_price REAL,
                pnl         REAL,
                status      TEXT DEFAULT 'open'
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                trade_date       TEXT PRIMARY KEY,
                signals_analyzed INTEGER DEFAULT 0,
                signals_executed INTEGER DEFAULT 0,
                signals_rejected INTEGER DEFAULT 0,
                total_pnl        REAL DEFAULT 0.0,
                wins             INTEGER DEFAULT 0,
                losses           INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS paid_users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT,
                added_at  TEXT DEFAULT (datetime('now')),
                note      TEXT
            );

            CREATE TABLE IF NOT EXISTS guest_questions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                asked_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_guest_questions_user ON guest_questions(user_id, asked_at);
        """)
        _migrate(conn)


def _migrate(conn):
    """Apply schema changes to existing databases without dropping data."""
    for stmt in [
        "ALTER TABLE signals ADD COLUMN asset_type TEXT DEFAULT 'stock'",
        "ALTER TABLE signals ADD COLUMN entry_price REAL",
    ]:
        try:
            conn.execute(stmt)
        except Exception:
            pass  # Column already exists


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_signal(ticker, action, confidence, price_target, stop_loss, reasoning, asset_type="stock", entry_price=None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO signals (ticker, action, confidence, price_target, stop_loss, reasoning, generated_at, asset_type, entry_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, action, confidence, price_target, stop_loss, reasoning,
              _utcnow(), asset_type, entry_price))


def get_recent_signals(min_confidence: float, asset_types: list[str], max_age_minutes: int):
    """Unexecuted BUY/SELL candidates within the freshness window, best first.

    The executor ranks whole scan batches instead of taking signals in arrival
    order, so this must return every live candidate — not just the first match.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
    placeholders = ",".join("?" * len(asset_types))
    query = f"""
        SELECT * FROM signals
        WHERE generated_at >= ?
        AND confidence >= ?
        AND executed = 0
        AND asset_type IN ({placeholders})
        ORDER BY confidence DESC
    """
    with get_conn() as conn:
        rows = conn.execute(query, [cutoff, min_confidence, *asset_types]).fetchall()
    return [dict(r) for r in rows]


def record_position_close(ticker: str, close_price: float, pnl: float):
    """Mark the most recent open trade for a ticker as closed.

    Used by the position monitor (hard cut / breakeven exit) so risk limits
    and win-rate stats see monitor-driven closes, not just signal-driven ones.
    Ticker matching is separator-insensitive: Alpaca reports crypto positions
    as BTCUSD while signals store BTC-USD.
    """
    norm = ticker.replace("-", "").replace("/", "")
    now = _utcnow()
    trade_date = _utc_today()
    is_win = pnl >= 0
    with get_conn() as conn:
        conn.execute("""
            UPDATE trades SET closed_at=?, close_price=?, pnl=?, status='closed'
            WHERE id = (
                SELECT t.id FROM trades t
                JOIN signals s ON t.signal_id = s.id
                WHERE REPLACE(REPLACE(s.ticker, '-', ''), '/', '') = ?
                AND t.status = 'open'
                ORDER BY t.executed_at DESC LIMIT 1
            )
        """, (now, close_price, pnl, norm))
        conn.execute("""
            INSERT INTO daily_stats (trade_date, wins, losses, total_pnl)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                wins      = wins      + excluded.wins,
                losses    = losses    + excluded.losses,
                total_pnl = total_pnl + excluded.total_pnl
        """, (trade_date, 1 if is_win else 0, 0 if is_win else 1, pnl))


def get_signal_levels_for_position(ticker: str) -> dict | None:
    """Stop/target from the signal that opened the most recent open trade for a ticker.

    The position monitor enforces these in software — most positions have no
    broker-side protection (no stop/limit legs on crypto or fractional stock
    orders). Ticker matching is separator-insensitive: positions report BTCUSD,
    signals store BTC-USD.
    """
    norm = ticker.replace("-", "").replace("/", "").upper()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT s.stop_loss, s.price_target
            FROM trades t JOIN signals s ON t.signal_id = s.id
            WHERE REPLACE(REPLACE(UPPER(s.ticker), '-', ''), '/', '') = ?
            AND t.status = 'open'
            ORDER BY t.executed_at DESC LIMIT 1
        """, (norm,)).fetchone()
    return dict(row) if row else None


def get_todays_signals(min_confidence=0.0, asset_type: str | None = None):
    today = _utc_today()
    query = """
        SELECT * FROM signals
        WHERE date(generated_at) = ?
        AND confidence >= ?
    """
    params: list = [today, min_confidence]
    if asset_type:
        query += " AND asset_type = ?"
        params.append(asset_type)
    query += " ORDER BY confidence DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_todays_trades():
    today = _utc_today()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.*, COALESCE(s.ticker, t.order_id) as ticker,
                   COALESCE(s.action, 'BUY') as action,
                   COALESCE(s.reasoning, '') as reasoning
            FROM trades t
            LEFT JOIN signals s ON t.signal_id = s.id AND t.signal_id != 0
            WHERE date(t.executed_at) = ?
            ORDER BY t.executed_at DESC
        """, (today,)).fetchall()
    return [dict(r) for r in rows]


def get_trade_history(limit=10):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.*, COALESCE(s.ticker, t.order_id) as ticker,
                   COALESCE(s.action, 'BUY') as action
            FROM trades t
            LEFT JOIN signals s ON t.signal_id = s.id AND t.signal_id != 0
            WHERE t.status = 'closed'
            ORDER BY t.closed_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_win_rate() -> dict:
    """Lifetime win rate across all closed trades."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COALESCE(SUM(wins), 0)   as total_wins,
                COALESCE(SUM(losses), 0) as total_losses,
                COALESCE(SUM(total_pnl), 0) as total_pnl
            FROM daily_stats
        """).fetchone()
    total_wins   = row["total_wins"]
    total_losses = row["total_losses"]
    total_trades = total_wins + total_losses
    win_rate = total_wins / total_trades if total_trades else 0.0
    return {
        "wins": total_wins,
        "losses": total_losses,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "total_pnl": row["total_pnl"],
    }


def get_todays_stats():
    today = _utc_today()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_stats WHERE trade_date = ?", (today,)
        ).fetchone()
    return dict(row) if row else {
        "trade_date": today,
        "signals_analyzed": 0,
        "signals_executed": 0,
        "signals_rejected": 0,
        "total_pnl": 0.0,
        "wins": 0,
        "losses": 0,
    }


# ── Paid user management ──────────────────────────────────────────────────────

def is_paid_user(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM paid_users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row is not None


def add_paid_user(user_id: int, username: str = "", note: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO paid_users (user_id, username, note) VALUES (?, ?, ?)",
            (user_id, username, note)
        )


def remove_paid_user(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM paid_users WHERE user_id = ?", (user_id,))


def list_paid_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM paid_users ORDER BY added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Guest rate limiting (2 questions per 4 hours, by Telegram user_id) ────────

RATE_LIMIT_MAX   = 2
RATE_LIMIT_HOURS = 4


def count_recent_questions(user_id: int) -> tuple[int, str | None]:
    """Returns (count_in_window, oldest_asked_at ISO string or None)."""
    cutoff = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=RATE_LIMIT_HOURS)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT asked_at FROM guest_questions WHERE user_id = ? AND asked_at > ? ORDER BY asked_at ASC",
            (user_id, cutoff.isoformat())
        ).fetchall()
    if not rows:
        return 0, None
    return len(rows), rows[0]["asked_at"]


def record_question(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO guest_questions (user_id) VALUES (?)", (user_id,)
        )
