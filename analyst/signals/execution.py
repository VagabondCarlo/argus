"""
Execution suggestion engine.
Given a signal (asset class, direction, time horizon, confidence),
returns "how to play this" options ranked by risk level.

All language is framed as suggestions — Argus is not a financial advisor.
Rule-based, not LLM-generated, for consistency.
"""

from dataclasses import dataclass

_DYOR = "This is a suggestion only. Do your own research before making any decision."


@dataclass
class ExecutionOption:
    risk_level: str       # "conservative" | "moderate" | "aggressive"
    instrument: str       # short name of the vehicle
    how: str              # suggestion — what some traders consider in this setup
    note: str             # key risk or requirement + DYOR reminder


def suggest_execution(signal: dict) -> list[ExecutionOption]:
    """
    Returns 2-3 execution options for a signal, ordered conservative → aggressive.
    """
    asset_type = signal.get("asset_type", "stock")
    action     = signal.get("action", "BUY")
    horizon    = signal.get("time_horizon", "1-2 days")
    ticker     = signal.get("ticker", "")

    if asset_type == "stock":
        return _stock_suggestions(action, horizon, ticker)
    elif asset_type == "forex":
        return _forex_suggestions(action, horizon, ticker)
    elif asset_type == "metal":
        return _metal_suggestions(action, horizon, ticker)
    elif asset_type == "crypto":
        return _crypto_suggestions(action, horizon, ticker)

    return []


# ── Stocks ───────────────────────────────────────────────────────────────────

def _stock_suggestions(action: str, horizon: str, ticker: str) -> list[ExecutionOption]:
    options = []
    is_intraday = "intraday" in horizon.lower()
    is_swing    = "week" in horizon.lower() or "3" in horizon

    if action == "BUY":
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument="Shares",
            how=(
                f"Some traders in this setup consider taking a position in {ticker} shares "
                "at or near the open, with a stop order placed at the stop price above "
                "to limit downside automatically."
            ),
            note=f"Lowest risk approach — no expiration, no leverage. Requires enough capital for at least 1 share. {_DYOR}",
        ))

        if is_intraday:
            options.append(ExecutionOption(
                risk_level="aggressive",
                instrument="0DTE Call Option (Same-Day Expiry)",
                how=(
                    f"Traders looking for an intraday scalp on {ticker} sometimes consider "
                    "a same-day (0DTE) at-the-money call option, typically entered within "
                    "the first 15–30 minutes of open and closed well before 3 PM. "
                    "This is a minute-to-minute contract — it expires worthless at end of day."
                ),
                note=f"Extremely high risk. The premium can go to zero within hours. Only suitable for experienced options traders. {_DYOR}",
            ))
        elif is_swing:
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument="Weekly Call Option",
                how=(
                    f"Traders holding for a multi-day move sometimes consider a call option "
                    f"on {ticker} expiring in 1–2 weeks, with a strike near the current price. "
                    "The position would typically be closed when the price target is approached, "
                    "not held to expiry."
                ),
                note=f"Options lose value every day (theta decay) — the longer you hold, the more you pay for time. {_DYOR}",
            ))
        else:
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument="Short-Term Call Option (3–5 Days)",
                how=(
                    f"For a 1–3 day move, some traders consider a short-term call option on {ticker} "
                    "expiring in 3–5 days, at or slightly out of the money. "
                    "The idea is to close the position when the target is reached, not at expiry."
                ),
                note=f"More leverage than shares but premium decays fast. Set a price alert at the target. {_DYOR}",
            ))

    elif action == "SELL":
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument="Put Option",
            how=(
                f"Traders anticipating a drop in {ticker} sometimes consider a put option "
                "with a strike near the current price, expiring 3–7 days out. "
                "The position would typically be closed when the price reaches the lower target."
            ),
            note=f"A put option lets you profit from a decline without needing a margin account. Max loss is limited to the premium paid. {_DYOR}",
        ))

        options.append(ExecutionOption(
            risk_level="moderate",
            instrument="Short Position",
            how=(
                f"Some traders in a bearish setup consider shorting {ticker}, "
                "with a buy-stop order placed at the stop price to automatically limit losses "
                "if the trade moves against them."
            ),
            note=f"Requires a margin account and short-selling approval. Borrow fees apply on high-demand tickers. {_DYOR}",
        ))

        if is_intraday:
            options.append(ExecutionOption(
                risk_level="aggressive",
                instrument="0DTE Put Option (Same-Day Expiry)",
                how=(
                    f"For an intraday bearish scalp on {ticker}, some traders consider "
                    "a same-day (0DTE) at-the-money put option, typically entered "
                    "within the first 30 minutes of open on confirmation of downside momentum. "
                    "These are closed before 3 PM — never held to expiry."
                ),
                note=f"Can amplify a strong down move significantly. Can also go to zero within an hour on a reversal. Very high risk. {_DYOR}",
            ))

    return options


# ── Forex ────────────────────────────────────────────────────────────────────

_FOREX_ETF_PROXIES = {
    "EURUSD=X": ("FXE",  "Euro ETF",                False),
    "GBPUSD=X": ("FXB",  "British Pound ETF",        False),
    "USDJPY=X": ("FXY",  "Japanese Yen ETF",         True),   # inverse — FXY rises when USD/JPY falls
    "AUDUSD=X": ("FXA",  "Australian Dollar ETF",    False),
    "USDCAD=X": ("FXC",  "Canadian Dollar ETF",      True),
    "USDCHF=X": ("FXF",  "Swiss Franc ETF",          True),
}

def _forex_suggestions(action: str, horizon: str, ticker: str) -> list[ExecutionOption]:
    proxy = _FOREX_ETF_PROXIES.get(ticker)
    options = []

    direction = "long" if action == "BUY" else "short"
    options.append(ExecutionOption(
        risk_level="conservative",
        instrument="Spot Forex",
        how=(
            f"Traders aligned with this signal sometimes consider a {direction} position "
            "on the pair through a forex broker such as OANDA, Interactive Brokers, or TD Ameritrade. "
            "Micro lots (1,000 units) are one way to limit exposure while learning the pair."
        ),
        note=f"Requires a forex-enabled account. Consider no more than 10:1 leverage for this time horizon. {_DYOR}",
    ))

    if proxy:
        etf_ticker, etf_name, is_inverse = proxy
        if is_inverse:
            etf_direction = "a long position in" if action == "SELL" else "a short position in"
        else:
            etf_direction = "a long position in" if action == "BUY" else "a short position in"

        options.append(ExecutionOption(
            risk_level="moderate",
            instrument=f"Currency ETF — {etf_ticker}",
            how=(
                f"Traders without a forex account sometimes consider {etf_direction} {etf_ticker} "
                f"({etf_name}) through a regular brokerage. "
                "It tracks the currency pair with a slight delay and no forex margin required."
                + (" Note: this ETF moves inversely to the pair." if is_inverse else "")
            ),
            note=f"Available on Robinhood, Fidelity, Schwab, etc. Less precise than spot but accessible. {_DYOR}",
        ))

    return options


# ── Precious Metals ──────────────────────────────────────────────────────────

_METAL_MAP = {
    "GC=F": {"etf": "GLD",  "etf_name": "SPDR Gold ETF",              "futures": "/GC", "proxy": "GDX",  "proxy_name": "Gold Miners ETF"},
    "SI=F": {"etf": "SLV",  "etf_name": "iShares Silver Trust",        "futures": "/SI", "proxy": None,   "proxy_name": None},
    "PL=F": {"etf": "PPLT", "etf_name": "Aberdeen Platinum ETF",       "futures": "/PL", "proxy": None,   "proxy_name": None},
    "PA=F": {"etf": "PALL", "etf_name": "Aberdeen Palladium ETF",      "futures": "/PA", "proxy": None,   "proxy_name": None},
    "HG=F": {"etf": "CPER", "etf_name": "US Copper ETF",               "futures": "/HG", "proxy": "COPX", "proxy_name": "Global Copper Miners ETF"},
}

def _metal_suggestions(action: str, horizon: str, ticker: str) -> list[ExecutionOption]:
    meta = _METAL_MAP.get(ticker, {})
    etf       = meta.get("etf")
    etf_name  = meta.get("etf_name")
    futures   = meta.get("futures")
    proxy     = meta.get("proxy")
    proxy_name = meta.get("proxy_name")
    options = []

    if etf:
        if action == "BUY":
            options.append(ExecutionOption(
                risk_level="conservative",
                instrument=f"Metal ETF — {etf}",
                how=(
                    f"Traders looking for exposure to this move sometimes consider a position in "
                    f"{etf} ({etf_name}) through a regular brokerage account. "
                    "No futures account needed — it tracks the metal price closely."
                ),
                note=f"Most accessible approach. Liquid and available everywhere. Close the position when the target is approached. {_DYOR}",
            ))
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument=f"Call Option on {etf}",
                how=(
                    f"Some traders seeking leverage on a bullish metal move consider a call option "
                    f"on {etf} expiring 1–2 weeks out, strike near the current price. "
                    "The idea is to close when the target is reached, not at expiry."
                ),
                note=f"Options add leverage but also decay daily. Only one approach — weigh the risk carefully. {_DYOR}",
            ))
        else:
            options.append(ExecutionOption(
                risk_level="conservative",
                instrument=f"Put Option on {etf}",
                how=(
                    f"Traders expecting a decline in this metal sometimes consider a put option "
                    f"on {etf} ({etf_name}), strike near current price, expiring 1–2 weeks out."
                ),
                note=f"Max loss limited to premium paid. No need to short the futures market directly. {_DYOR}",
            ))

    if proxy and action == "BUY":
        options.append(ExecutionOption(
            risk_level="moderate",
            instrument=f"Mining Stocks — {proxy}",
            how=(
                f"Some traders use mining stocks like {proxy} ({proxy_name}) as a leveraged proxy "
                f"for the metal — mining equities often move 2–3x the metal's percentage move. "
                "This adds company and operational risk on top of the commodity move."
            ),
            note=f"Higher potential return than the ETF but also higher volatility. Research individual holdings. {_DYOR}",
        ))

    if futures:
        direction = "a long position in" if action == "BUY" else "a short position in"
        options.append(ExecutionOption(
            risk_level="aggressive",
            instrument=f"Futures — {futures}",
            how=(
                f"Experienced futures traders sometimes consider {direction} one {futures} contract "
                "through a futures-enabled broker (TD Ameritrade, Interactive Brokers, Schwab). "
                "A stop order at the stop price would typically be placed immediately after entry."
            ),
            note=f"Futures carry significant leverage and require a futures-approved account. One contract controls a large notional position. {_DYOR}",
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

    if action == "BUY":
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument=f"Spot Crypto — {coin_name}",
            how=(
                f"Traders aligned with a bullish {coin_name} signal sometimes consider "
                f"a spot position on an exchange such as Coinbase, Kraken, or Gemini. "
                "A price alert at the target and a standing sell order at the stop price "
                "are two ways some traders manage the position."
            ),
            note=f"You hold the asset directly. No expiration. Crypto is highly volatile — size accordingly. {_DYOR}",
        ))

        if etf_ticker:
            options.append(ExecutionOption(
                risk_level="conservative",
                instrument=f"Crypto ETF — {etf_ticker}",
                how=(
                    f"Traders who prefer to stay within a brokerage account sometimes consider "
                    f"{etf_ticker} ({etf_name}), which tracks {coin_name} without requiring "
                    "a separate crypto exchange account. Works in IRA and standard accounts."
                ),
                note=f"Slightly less responsive than spot but accessible everywhere. {_DYOR}",
            ))

            options.append(ExecutionOption(
                risk_level="moderate",
                instrument=f"Call Option on {etf_ticker}",
                how=(
                    f"Some traders seeking leverage on a bullish {coin_name} move consider "
                    f"a call option on {etf_ticker} expiring 1–2 weeks out, strike near current price. "
                    "Only available on ETF-listed coins."
                ),
                note=f"Options on crypto ETFs add leverage but decay daily. Crypto can move fast in both directions. {_DYOR}",
            ))

    elif action == "SELL":
        options.append(ExecutionOption(
            risk_level="conservative",
            instrument=f"Reduce or Exit {coin_name} Position",
            how=(
                f"Traders who already hold {coin_name} and are seeing a bearish signal "
                "sometimes consider reducing their position or moving into a stablecoin "
                "(USDC or USDT) to preserve capital while they reassess."
            ),
            note=f"Exiting a long is the lowest-risk bearish action. Shorting crypto carries additional complexity and risk. {_DYOR}",
        ))

        if etf_ticker:
            options.append(ExecutionOption(
                risk_level="moderate",
                instrument=f"Put Option on {etf_ticker}",
                how=(
                    f"Some traders expecting a {coin_name} decline consider a put option on "
                    f"{etf_ticker} ({etf_name}), expiring 1–2 weeks out, strike near current price. "
                    "This is one way to express a bearish view without shorting on a crypto exchange."
                ),
                note=f"Max loss limited to premium paid. Only available for BTC and ETH via their ETFs. {_DYOR}",
            ))

    return options


# ── Formatting helpers ────────────────────────────────────────────────────────

_RISK_EMOJI = {
    "conservative": "🟢",
    "moderate":     "🟡",
    "aggressive":   "🔴",
}


def format_execution_tier1(signal: dict) -> str:
    """One-line execution hint for the free channel — conservative option only."""
    suggestions = suggest_execution(signal)
    if not suggestions:
        return ""
    s = suggestions[0]
    first_sentence = s.how.split(".")[0].strip()
    return f"💡 <i>One approach some traders consider: {s.instrument.lower()} — {first_sentence}.</i>"


def format_execution_tier2(signal: dict) -> str:
    """Full execution suggestion block for the paid channel."""
    suggestions = suggest_execution(signal)
    if not suggestions:
        return ""
    lines = ["<b>How some traders approach this setup:</b>"]
    for s in suggestions:
        emoji = _RISK_EMOJI.get(s.risk_level, "⚪")
        lines.append(f"\n{emoji} <b>{s.instrument}</b>  [{s.risk_level.upper()}]")
        lines.append(f"   {s.how}")
        lines.append(f"   <i>⚠️ {s.note}</i>")
    return "\n".join(lines)
