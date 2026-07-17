"""Shadow-book resolution logic — must match the original replay's rules."""
from analyst.shadow_book import resolve_from_bars

# bars are (high, low, close)


def test_buy_hits_target():
    bars = [(101, 99.5, 100.5), (102.5, 100.8, 102.2)]  # target 102, stop 98
    outcome, exit_price = resolve_from_bars(bars, "BUY", 98, 102)
    assert outcome == "win"
    assert exit_price == 102


def test_buy_hits_stop():
    bars = [(101, 99.5, 100.5), (100.2, 97.8, 98.5)]
    outcome, exit_price = resolve_from_bars(bars, "BUY", 98, 102)
    assert outcome == "loss"
    assert exit_price == 98


def test_ambiguous_bar_counts_as_loss():
    """Stop and target inside the same bar — conservative call, same as replay."""
    bars = [(102.5, 97.5, 100.0)]
    outcome, exit_price = resolve_from_bars(bars, "BUY", 98, 102)
    assert outcome == "loss"


def test_unresolved_returns_none_with_last_close():
    bars = [(100.5, 99.5, 100.1), (100.8, 99.8, 100.4)]
    outcome, exit_price = resolve_from_bars(bars, "BUY", 98, 102)
    assert outcome is None
    assert exit_price == 100.4


def test_sell_direction_inverted():
    """SELL: stop above, target below."""
    bars = [(100.4, 99.6, 100.0), (99.9, 97.9, 98.1)]  # falls to target 98
    outcome, exit_price = resolve_from_bars(bars, "SELL", 102, 98)
    assert outcome == "win"
    assert exit_price == 98
