"""Integration tests for the signal -> execution path.

These exist because v1 went 21 days generating signals that never executed
and nothing caught it. Every test drives the real process_pending_signals()
against a real (temp) database — only the Alpaca gateway and Telegram are
mocked. If a change breaks the signal -> order path, these fail.

Run from the repo root:  venv/bin/python -m pytest tests/ -v
"""
from datetime import datetime, timedelta, timezone

import pytest

import shared.database as db


@pytest.fixture
def ex(tmp_path, monkeypatch):
    """Executor module wired to a temp DB with the broker and Telegram mocked."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()

    import executor.main as exmod

    exmod.orders = []
    exmod.closes = []

    def fake_place_order(ticker, side, qty, stop_loss_price,
                         take_profit_price=None, asset_type="stock"):
        exmod.orders.append(
            {"ticker": ticker, "side": side, "qty": qty, "asset_type": asset_type}
        )
        return {"order_id": f"test-{len(exmod.orders)}", "status": "accepted", "qty": qty}

    def fake_close_position(ticker):
        exmod.closes.append(ticker)
        return {"closed": ticker}

    monkeypatch.setattr(exmod, "get_account", lambda: {
        "cash": 100_000.0, "portfolio_value": 100_000.0,
        "buying_power": 100_000.0, "pnl_today": 0.0,
    })
    monkeypatch.setattr(exmod, "get_open_positions", lambda: [])
    monkeypatch.setattr(exmod, "get_latest_price", lambda t, a="stock": 100.0)
    monkeypatch.setattr(exmod, "place_order", fake_place_order)
    monkeypatch.setattr(exmod, "close_position", fake_close_position)
    monkeypatch.setattr(exmod, "cancel_open_orders", lambda t: 0)
    monkeypatch.setattr(exmod, "send_sync_notification", lambda *a, **k: None)
    monkeypatch.setattr(exmod, "post_trade_close", lambda t: None)  # no Telegram from tests
    monkeypatch.setattr(exmod, "is_crypto_tradable", lambda t: True)
    monkeypatch.setattr(exmod, "_is_market_hours", lambda: True)

    # Pin the config this suite assumes, regardless of what .env says
    monkeypatch.setattr(exmod.config, "CONFIDENCE_THRESHOLD", 0.72)
    monkeypatch.setattr(exmod.config, "SIGNAL_MAX_AGE_MINUTES", 30)
    monkeypatch.setattr(exmod.config, "MAX_OPEN_POSITIONS", 3)
    monkeypatch.setattr(exmod.config, "CRYPTO_ENABLED", True)

    return exmod


def _signal(ticker, action, conf, asset_type="stock", entry=100.0):
    db.save_signal(
        ticker=ticker, action=action, confidence=conf,
        price_target=entry * 1.04, stop_loss=entry * 0.98,
        reasoning="integration test", asset_type=asset_type, entry_price=entry,
    )


def _fake_position(ticker, asset_class="stock"):
    return {
        "ticker": ticker, "qty": 1.0, "avg_entry": 50.0,
        "current_price": 50.0, "unrealized_pnl": 0.0, "asset_class": asset_class,
    }


def test_signal_above_threshold_places_order(ex):
    _signal("TEST", "BUY", 0.74)
    ex.process_pending_signals()

    assert len(ex.orders) == 1
    assert ex.orders[0]["ticker"] == "TEST"
    assert ex.orders[0]["side"] == "BUY"

    with db.get_conn() as conn:
        sig = conn.execute("SELECT executed FROM signals WHERE ticker='TEST'").fetchone()
        trade = conn.execute("SELECT status FROM trades").fetchone()
    assert sig["executed"] == 1
    assert trade["status"] == "open"


def test_below_threshold_never_executes(ex):
    _signal("WEAK", "BUY", 0.69)
    ex.process_pending_signals()
    assert ex.orders == []


def test_picks_best_not_first(ex, monkeypatch):
    """One open slot, three candidates — the highest confidence wins,
    not the earliest arrival. This is the core v2 behavior change."""
    _signal("NVDA", "BUY", 0.73)   # arrives first
    _signal("AAPL", "BUY", 0.78)   # best
    _signal("MSFT", "BUY", 0.75)
    monkeypatch.setattr(
        ex, "get_open_positions",
        lambda: [_fake_position("XOM"), _fake_position("CVX")],
    )

    ex.process_pending_signals()

    assert len(ex.orders) == 1
    assert ex.orders[0]["ticker"] == "AAPL"


def test_fills_all_open_slots_ranked(ex):
    _signal("NVDA", "BUY", 0.73)   # weakest — no slot for it
    _signal("AAPL", "BUY", 0.78)
    _signal("MSFT", "BUY", 0.75)
    _signal("TSLA", "BUY", 0.74)

    ex.process_pending_signals()

    assert [o["ticker"] for o in ex.orders] == ["AAPL", "MSFT", "TSLA"]


def test_stale_signal_ignored(ex):
    """A strong signal from 6 hours ago is a price that no longer exists.

    (6h, not 2h: in the first 15 min after the open the stock window widens
    to 165 min so pre-market signals can execute — a 2h-old signal would be
    legitimately eligible then.)
    """
    old = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    with db.get_conn() as conn:
        conn.execute("""
            INSERT INTO signals (ticker, action, confidence, price_target, stop_loss,
                                 reasoning, generated_at, asset_type, entry_price)
            VALUES ('STALE', 'BUY', 0.80, 104, 98, 'old', ?, 'stock', 100)
        """, (old,))

    ex.process_pending_signals()
    assert ex.orders == []


def test_watch_signals_never_trade(ex):
    """v1 bug: a high-confidence WATCH fell through to a live order."""
    _signal("WTCH", "WATCH", 0.85)
    ex.process_pending_signals()
    assert ex.orders == []


def test_crypto_executes_after_hours(ex, monkeypatch):
    monkeypatch.setattr(ex, "_is_market_hours", lambda: False)
    _signal("BTC-USD", "BUY", 0.74, asset_type="crypto")
    _signal("AAPL", "BUY", 0.80, asset_type="stock")  # market closed — must wait

    ex.process_pending_signals()

    assert len(ex.orders) == 1
    assert ex.orders[0]["ticker"] == "BTC-USD"
    assert ex.orders[0]["asset_type"] == "crypto"


def test_duplicate_ticker_takes_strongest(ex):
    _signal("NVDA", "BUY", 0.73)
    _signal("NVDA", "BUY", 0.76)
    ex.process_pending_signals()
    assert len(ex.orders) == 1


def test_sell_closes_position_and_records_trade(ex, monkeypatch):
    """Full round trip: BUY opens the trade row, SELL closes THAT row —
    v1 left the entry row open forever and inserted a separate close row."""
    _signal("TSLA", "BUY", 0.74)
    ex.process_pending_signals()          # entry
    assert len(ex.orders) == 1

    monkeypatch.setattr(ex, "get_open_positions", lambda: [{
        "ticker": "TSLA", "qty": 2.0, "avg_entry": 100.0,
        "current_price": 105.0, "unrealized_pnl": 10.0, "asset_class": "stock",
    }])
    _signal("TSLA", "SELL", 0.74)
    ex.process_pending_signals()          # exit

    assert ex.closes == ["TSLA"]
    with db.get_conn() as conn:
        rows = conn.execute("SELECT status, pnl FROM trades").fetchall()
    assert len(rows) == 1                 # one round trip = one row
    assert rows[0]["status"] == "closed"
    assert rows[0]["pnl"] == 10.0


def test_track_record_card_format():
    """The public feed card: monospace numbers, running record, paper label."""
    from notifications.track_record import format_trade_close
    t = {
        "ticker": "SOL-USD", "confidence": 0.68, "fill_price": 73.83,
        "close_price": 75.14, "quantity": 2.708926, "pnl": 3.55,
        "executed_at": "2026-07-17T13:08:05+00:00",
        "closed_at": "2026-07-17T17:20:05+00:00",
    }
    rec = {"wins": 5, "losses": 3, "total_trades": 8,
           "win_rate": 0.625, "total_pnl": 14.20}
    card = format_trade_close(t, rec)
    assert "✅ WIN — SOL-USD" in card
    assert "+$3.55" in card
    assert "5W-3L" in card
    assert "held 4h 12m" in card
    assert "paper trading" in card


def test_drift_guard_skips_chased_price(ex, monkeypatch):
    """Signal planned entry $100 (stop $98 → $2 risk). Live price $101.50 has
    already consumed 75% of the risk distance toward target — don't chase."""
    monkeypatch.setattr(ex, "get_latest_price", lambda t, a="stock": 101.5)
    _signal("CHSE", "BUY", 0.75)

    ex.process_pending_signals()

    assert ex.orders == []
    with db.get_conn() as conn:
        sig = conn.execute("SELECT executed FROM signals").fetchone()
    assert sig["executed"] == 1  # marked handled — no 30s retry loop


def test_drift_guard_skips_price_through_stop(ex, monkeypatch):
    """Live price below the signal's stop means the setup already failed."""
    monkeypatch.setattr(ex, "get_latest_price", lambda t, a="stock": 97.5)
    _signal("BRKN", "BUY", 0.75)

    ex.process_pending_signals()

    assert ex.orders == []


def test_monitor_closes_at_signal_target(ex):
    """The monitor must bank wins at the signal's target — most positions have
    no broker-side take-profit (crypto and fractional stock orders can't)."""
    _signal("WINR", "BUY", 0.75)          # entry 100 → target 104, stop 98
    ex.process_pending_signals()          # opens the position
    assert len(ex.orders) == 1

    pos = {"ticker": "WINR", "qty": 1.0, "avg_entry": 100.0,
           "current_price": 104.2, "unrealized_pnl": 4.2, "asset_class": "stock"}
    ex._evaluate_position(pos, market_open=True)

    assert ex.closes == ["WINR"]
    with db.get_conn() as conn:
        trade = conn.execute("SELECT status, pnl FROM trades").fetchone()
    assert trade["status"] == "closed"
    assert trade["pnl"] == pytest.approx(4.2)


def test_monitor_closes_at_signal_stop(ex):
    """Same for the stop: -2% signal stop must fire before the -3% hard cut."""
    _signal("LOSR", "BUY", 0.75)          # stop 98
    ex.process_pending_signals()

    pos = {"ticker": "LOSR", "qty": 1.0, "avg_entry": 100.0,
           "current_price": 97.9, "unrealized_pnl": -2.1, "asset_class": "stock"}
    ex._evaluate_position(pos, market_open=True)

    assert ex.closes == ["LOSR"]


def test_weekly_limit_counts_entries_not_closes(ex):
    """A round trip (entry row + close row) is one trade against the 25/week cap."""
    from executor.risk.manager import get_weekly_trade_count
    now = datetime.now(timezone.utc).isoformat()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO trades (signal_id, order_id, executed_at, status) VALUES (1, 'abc123', ?, 'open')",
            (now,))
        conn.execute(
            "INSERT INTO trades (signal_id, order_id, executed_at, status) VALUES (1, 'close', ?, 'closed')",
            (now,))
    assert get_weekly_trade_count() == 1


def test_untradable_crypto_skipped(ex, monkeypatch):
    """Coins Alpaca doesn't list (e.g. BNB) must be skipped, not errored."""
    monkeypatch.setattr(ex, "is_crypto_tradable", lambda t: False)
    _signal("BNB-USD", "BUY", 0.78, asset_type="crypto")

    ex.process_pending_signals()

    assert ex.orders == []
    with db.get_conn() as conn:
        sig = conn.execute("SELECT executed FROM signals").fetchone()
    assert sig["executed"] == 1  # marked handled so it doesn't retry forever
