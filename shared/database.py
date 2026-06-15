import sqlite3
import os
from datetime import datetime, date
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "argus.db")


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
                executed    INTEGER DEFAULT 0
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


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_signal(ticker, action, confidence, price_target, stop_loss, reasoning):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO signals (ticker, action, confidence, price_target, stop_loss, reasoning, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ticker, action, confidence, price_target, stop_loss, reasoning,
              datetime.utcnow().isoformat()))


def get_todays_signals(min_confidence=0.0):
    today = date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM signals
            WHERE date(generated_at) = ?
            AND confidence >= ?
            ORDER BY confidence DESC
        """, (today, min_confidence)).fetchall()
    return [dict(r) for r in rows]


def get_todays_trades():
    today = date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.*, s.ticker, s.action, s.reasoning
            FROM trades t
            JOIN signals s ON t.signal_id = s.id
            WHERE date(t.executed_at) = ?
            ORDER BY t.executed_at DESC
        """, (today,)).fetchall()
    return [dict(r) for r in rows]


def get_trade_history(limit=10):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.*, s.ticker, s.action
            FROM trades t
            JOIN signals s ON t.signal_id = s.id
            WHERE t.status = 'closed'
            ORDER BY t.closed_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_todays_stats():
    today = date.today().isoformat()
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
    cutoff = datetime.utcnow().replace(microsecond=0) - __import__('datetime').timedelta(hours=RATE_LIMIT_HOURS)
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
