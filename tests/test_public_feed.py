"""Leak-prevention tests for the public feed.

The one job: prove the public payload can never carry entry prices, targets,
secrets, or internal fields — no matter what's in the DB. If someone adds a
field to a signal query later, these fail.
"""
import json

import pytest

import shared.database as db


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    # A tradeable signal, a degenerate one (collapsed levels), a WATCH
    db.save_signal("NVDA", "BUY", 0.74, 128.0, 118.0, "x", "stock", entry_price=120.0)
    db.save_signal("BAT-USD", "BUY", 0.65, 0.08, 0.08, "x", "crypto", entry_price=0.08)  # degenerate
    db.save_signal("SPY", "WATCH", 0.80, 600.0, 580.0, "x", "stock", entry_price=590.0)  # not actionable
    import notifications.public_feed as pf
    return pf


def test_signals_never_expose_entry_or_target(seeded):
    payload = seeded.build_public_payload(include_news=False)
    for s in payload["signals"]:
        assert "entry" not in s and "entry_price" not in s
        assert "target" not in s and "price_target" not in s
        assert "stop" in s                       # stop IS shown
        assert set(s.keys()) <= {"ticker", "action", "confidence",
                                 "asset_type", "stop", "high_conviction"}


def test_degenerate_signal_filtered(seeded):
    payload = seeded.build_public_payload(include_news=False)
    tickers = [s["ticker"] for s in payload["signals"]]
    assert "BAT-USD" not in tickers               # entry == stop == target → dropped
    assert "NVDA" in tickers


def test_watch_signals_excluded(seeded):
    payload = seeded.build_public_payload(include_news=False)
    assert "SPY" not in [s["ticker"] for s in payload["signals"]]


def test_high_conviction_flag(seeded):
    payload = seeded.build_public_payload(include_news=False)
    nvda = next(s for s in payload["signals"] if s["ticker"] == "NVDA")
    assert nvda["high_conviction"] is True        # 0.74 >= 0.72


def test_no_secrets_anywhere_in_payload(seeded, monkeypatch):
    # Even if the environment holds secrets, they must not reach the payload
    monkeypatch.setenv("MASTER_KEY", "J4x$0n!SECRET")
    monkeypatch.setenv("ALPACA_API_KEY", "PKTESTKEY1234567890")
    blob = json.dumps(seeded.build_public_payload(include_news=False))
    for needle in ("J4x", "SECRET", "PKTEST", "ALPACA", "MASTER", "TELEGRAM", "192.168", "100.1"):
        assert needle not in blob


def test_renders_without_error(seeded):
    from notifications.render_terminal import render
    html_out = render(seeded.build_public_payload(include_news=False))
    assert "ARGUS" in html_out
    assert "NVDA" in html_out
    assert "120.0" not in html_out                # entry price must not render
    assert "PRO →" in html_out                    # entry/target gated
