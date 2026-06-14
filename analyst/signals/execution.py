"""
Execution suggestion engine.
Given a signal (asset class, direction, time horizon, confidence),
returns concrete "how to play this" options ranked by risk level.
Rule-based — not LLM — for consistency and reliability.
"""

from dataclasses import dataclass


@dataclass
class ExecutionOption:
    risk_level: str       # "conservative" | "moderate" | "aggressive"
    instrument: str       # short name of the vehicle
    how: str              # one sentence — exactly what to do
    note: str             # key risk or requirement


def suggest_execution(signal: dict) -> list[ExecutionOption]:
    """
    Returns 2-3 execution options for a signal, ordered conservative → aggressive.
    signal must include: asset_type, action, time_horizon, confidence, ticker
    """
    asset_type  = signal.get("asset_type", "stock")
    action      = signal.get("action", "BUY")
    horizon     = signal.get("time_horizon", "1-2 days")
    confidence  = signal.get("confidence", 0.75)
    ticker      = signal.get("ticker", "")

    if asset_type == "stock":
        return _stock_suggestions(action, horizon, confidence, ticker)
    elif asset_type == "forex":
        return _forex_suggestions(action, horizon, ticker)
    elif asset_type == "metal":
        return _metal_suggestions(action, horizon, ticker)
    elif asset_type == "crypto":
        return _crypto_suggestions(action, horizon, ticker)

    return []


# ── Stocks ──────────────────────────────────────────────────────────────────

_STOCK_ETF_MAP = {
    "SPY": "SPY", "QQQ": "QQQ",
}

def _stock_suggestions(action: str, horizon: str, confidence: float, ticker: str) -> list[ExecutionOption]:
    options = []
    is_intraday = "intraday" in horizon.lower()
    is_swing    = "week" in horizon.lower() or "3" in horizon

    if action == "BUY":
        # Conservative: buy shares with a hard stop
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument="Shares",
            how=f"Buy {ticker} shares at market open. Set a hard stop at the stop price listed above.",
            note="Lowest risk. No expiration. Requires enough capital to buy at least 1 share.",
        ))

        if is_intraday:
            # Aggressive: 0DTE call — intraday scalp
            options.append(ExecutionOption(
                risk_level="aggressive",
                instrument="0DTE Call Option",
                how=(
                    f"Buy a same-day expiring (0DTE) ATM call on {ticker}. "
                    "Enter within 15 minutes of open. Exit before 3 PM — do not hold to expiry."
                ),
                note="Extremely high leverage. Can go to zero same day. Only for experienced options traders.",
            ))
        elif is_swing:
            # Moderate: weekly call
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument="Weekly Call Option",
                how=(
                    f"Buy a call option on {ticker} expiring in 1-2 weeks, "
                    "strike price near the current price (ATM). "
                    "Close when the stock hits the price target."
                ),
                note="2-5x leverage. Loses value daily — don't hold past the target.",
            ))
        else:
            # Moderate: 2-3 day call
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument="Short-Term Call Option",
                how=(
                    f"Buy a call option on {ticker} expiring in 3-5 days, ATM or one strike OTM. "
                    "Close position when target is reached, not at expiry."
                ),
                note="Higher leverage than shares but premium decays fast. Set an alert at the target.",
            ))

    elif action == "SELL":
        # Conservative: buy a put (no margin account needed)
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument="Put Option",
            how=(
                f"Buy a put option on {ticker}. "
                "Strike near current price (ATM), expiry 3-7 days out. "
                "Close when the stock hits the stop target below."
            ),
            note="Best way to short without a margin account. Max loss is the premium paid.",
        ))

        # Moderate: short the stock
        options.append(ExecutionOption(
            risk_level="moderate",
            instrument="Short Sell",
            how=(
                f"Short {ticker} at market open. "
                "Set a buy-stop at the stop price to cap your loss automatically."
            ),
            note="Requires a margin account. Borrow fees apply on volatile stocks.",
        ))

        if is_intraday:
            options.append(ExecutionOption(
                risk_level="aggressive",
                instrument="0DTE Put Option",
                how=(
                    f"Buy a same-day expiring (0DTE) ATM put on {ticker}. "
                    "Enter within 30 minutes of open on confirmation of weakness. "
                    "Exit before 3 PM — never hold a 0DTE to expiry."
                ),
                note="Can 5-10x on a strong move. Can go to zero in an hour. High risk.",
            ))

    return options


# ── Forex ────────────────────────────────────────────────────────────────────

_FOREX_ETF_PROXIES = {
    "EURUSD=X": ("FXE",  "Euro ETF"),
    "GBPUSD=X": ("FXB",  "British Pound ETF"),
    "USDJPY=X": ("FXY",  "Japanese Yen ETF (inverse — buy FXY to short USD/JPY)"),
    "AUDUSD=X": ("FXA",  "Australian Dollar ETF"),
    "USDCAD=X": ("FXC",  "Canadian Dollar ETF (inverse)"),
    "USDCHF=X": ("FXF",  "Swiss Franc ETF (inverse)"),
}

def _forex_suggestions(action: str, horizon: str, ticker: str) -> list[ExecutionOption]:
    etf_ticker, etf_name = _FOREX_ETF_PROXIES.get(ticker, (None, None))
    options = []

    options.append(ExecutionOption(
        risk_level="conservative",
        instrument="Spot Forex",
        how=(
            f"Open a {'long' if action == 'BUY' else 'short'} position on the pair directly "
            "through a forex broker (OANDA, Interactive Brokers, or TD Ameritrade). "
            "Use micro lots (1,000 units) to limit exposure."
        ),
        note="Requires a forex account. Use no more than 10:1 leverage for this time horizon.",
    ))

    if etf_ticker:
        etf_action = "Buy" if action == "BUY" else "Buy"
        if "inverse" in (etf_name or "").lower() and action == "BUY":
            etf_direction = f"Sell {etf_ticker}"
        elif "inverse" in (etf_name or "").lower() and action == "SELL":
            etf_direction = f"Buy {etf_ticker}"
        else:
            etf_direction = f"{'Buy' if action == 'BUY' else 'Sell'} {etf_ticker}"

        options.append(ExecutionOption(
            risk_level="moderate",
            instrument=f"Currency ETF ({etf_ticker})",
            how=(
                f"{etf_direction} ({etf_name}) in your regular brokerage account. "
                "No forex account needed. Tracks the currency pair with slight delay."
            ),
            note="Slightly less precise than spot forex. Works in any brokerage — Robinhood, Fidelity, etc.",
        ))

    return options


# ── Precious Metals ──────────────────────────────────────────────────────────

_METAL_MAP = {
    "GC=F": {
        "etf": "GLD",  "etf_name": "SPDR Gold ETF",
        "futures": "/GC", "proxy": "GDX", "proxy_name": "Gold Miners ETF",
    },
    "SI=F": {
        "etf": "SLV",  "etf_name": "iShares Silver Trust",
        "futures": "/SI", "proxy": "SLV", "proxy_name": "Silver ETF",
    },
    "PL=F": {
        "etf": "PPLT", "etf_name": "Aberdeen Platinum ETF",
        "futures": "/PL", "proxy": None, "proxy_name": None,
    },
    "PA=F": {
        "etf": "PALL", "etf_name": "Aberdeen Palladium ETF",
        "futures": "/PA", "proxy": None, "proxy_name": None,
    },
    "HG=F": {
        "etf": "CPER", "etf_name": "United States Copper ETF",
        "futures": "/HG", "proxy": "COPX", "proxy_name": "Global Copper Miners ETF",
    },
}

def _metal_suggestions(action: str, horizon: str, ticker: str) -> list[ExecutionOption]:
    meta = _METAL_MAP.get(ticker, {})
    etf = meta.get("etf")
    etf_name = meta.get("etf_name")
    futures = meta.get("futures")
    proxy = meta.get("proxy")
    proxy_name = meta.get("proxy_name")
    options = []

    if etf:
        if action == "BUY":
            options.append(ExecutionOption(
                risk_level="conservative",
                instrument=f"ETF — {etf}",
                how=f"Buy shares of {etf} ({etf_name}) in your brokerage. No futures account needed.",
                note="Tracks the spot price closely. Most liquid metals ETF. Sell when target is hit.",
            ))
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument=f"Call Option on {etf}",
                how=f"Buy a call option on {etf}, strike ATM, expiry 1-2 weeks out.",
                note="3-5x leverage on the metal move. Close before expiry when target is reached.",
            ))
        else:
            options.append(ExecutionOption(
                risk_level="conservative",
                instrument=f"Put Option on {etf}",
                how=f"Buy a put option on {etf} ({etf_name}), ATM strike, 1-2 week expiry.",
                note="Clean way to short metals without a futures account. Max loss is premium paid.",
            ))

    if proxy and proxy != etf and action == "BUY":
        options.append(ExecutionOption(
            risk_level="moderate",
            instrument=f"Mining Stocks — {proxy}",
            how=(
                f"Buy {proxy} ({proxy_name}). Mining stocks amplify metal moves — "
                "gold up 1% often means GDX up 2-3%."
            ),
            note="Higher leverage than the metal ETF, more volatile. Has company/operational risk too.",
        ))

    if futures:
        options.append(ExecutionOption(
            risk_level="aggressive",
            instrument=f"Futures — {futures}",
            how=(
                f"{'Go long' if action == 'BUY' else 'Go short'} one {futures} futures contract "
                f"through a futures-enabled broker (TD Ameritrade, Interactive Brokers, Schwab). "
                "Set stop at the stop price immediately after entry."
            ),
            note=f"One {futures} contract controls a large position. High leverage. Requires a futures account.",
        ))

    return options


# ── Crypto ───────────────────────────────────────────────────────────────────

_CRYPTO_ETF_MAP = {
    "BTC-USD": ("IBIT", "BlackRock Bitcoin ETF"),
    "ETH-USD": ("ETHA", "BlackRock Ethereum ETF"),
}

def _crypto_suggestions(action: str, horizon: str, ticker: str) -> list[ExecutionOption]:
    etf_ticker, etf_name = _CRYPTO_ETF_MAP.get(ticker, (None, None))
    coin_name = ticker.replace("-USD", "")
    options = []

    # Conservative: spot on exchange
    if action == "BUY":
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument=f"Spot Crypto — {coin_name}",
            how=(
                f"Buy {coin_name} directly on Coinbase, Kraken, or Gemini. "
                "Set a price alert at the target and a sell order at the stop price."
            ),
            note="You own the asset outright. No expiration. Can hold through volatility.",
        ))

        if etf_ticker:
            options.append(ExecutionOption(
                risk_level="conservative",
                instrument=f"Crypto ETF — {etf_ticker}",
                how=(
                    f"Buy {etf_ticker} ({etf_name}) in your regular brokerage account. "
                    "No crypto exchange account needed."
                ),
                note="Tracks the coin price. Slightly less responsive than spot. Great for IRA accounts.",
            ))

        options.append(ExecutionOption(
            risk_level="moderate",
            instrument=f"Call Option on {etf_ticker or coin_name}",
            how=(
                f"Buy a call option on {etf_ticker or 'IBIT'} expiring in 1-2 weeks, ATM strike. "
                "Close when price target is hit."
            ),
            note="3-5x leverage. Only available on ETF-listed coins (BTC, ETH). Loses value daily.",
        ))

    elif action == "SELL":
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument=f"Sell/Exit {coin_name}",
            how=(
                f"If you hold {coin_name}, this is a signal to take profits or reduce your position. "
                "Move to stablecoins (USDC/USDT) to preserve capital."
            ),
            note="Only short crypto if you have experience. Most retail traders should just exit longs.",
        ))

        if etf_ticker:
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument=f"Put Option on {etf_ticker}",
                how=(
                    f"Buy a put option on {etf_ticker} ({etf_name}), ATM strike, 1-2 week expiry. "
                    "Profits if the coin drops."
                ),
                note="Clean way to profit from a crypto drop without shorting on an exchange.",
            ))

    return options


# ── Formatting helpers ────────────────────────────────────────────────────────

_RISK_EMOJI = {
    "conservative": "🟢",
    "moderate":     "🟡",
    "aggressive":   "🔴",
}


def format_execution_tier1(signal: dict) -> str:
    """One-line execution hint for the free channel."""
    suggestions = suggest_execution(signal)
    if not suggestions:
        return ""
    # Show the conservative option only
    s = suggestions[0]
    return f"💡 <i>How to play: {s.instrument} — {s.how.split('.')[0]}.</i>"


def format_execution_tier2(signal: dict) -> str:
    """Full execution section for the paid channel."""
    suggestions = suggest_execution(signal)
    if not suggestions:
        return ""
    lines = ["<b>How to play this:</b>"]
    for s in suggestions:
        emoji = _RISK_EMOJI.get(s.risk_level, "⚪")
        lines.append(f"{emoji} <b>{s.instrument}</b>  [{s.risk_level.upper()}]")
        lines.append(f"   {s.how}")
        lines.append(f"   <i>⚠️ {s.note}</i>")
    return "\n".join(lines)
