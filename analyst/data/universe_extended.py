"""
Extended market universe — forex, precious metals, crypto.
Used for the daily multi-market broadcast.
"""

FOREX_PAIRS = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD",
    "USDCHF=X": "USD/CHF",
    "NZDUSD=X": "NZD/USD",
    "EURJPY=X": "EUR/JPY",
    "GBPJPY=X": "GBP/JPY",
}

METALS_PAIRS = {
    "GC=F":     "Gold (XAU/USD)",
    "SI=F":     "Silver (XAG/USD)",
    "PL=F":     "Platinum",
    "PA=F":     "Palladium",
    "HG=F":     "Copper",
}

# Expanded July 17 2026: every pair below (except BNB) validated as BOTH
# Alpaca-tradable and yfinance-data-rich before inclusion. More assets scanned
# = more >=0.72 setups per day at full veto quality — breadth is the flow
# lever, not looser gates. BNB stays for market coverage; the executor skips
# non-tradable pairs automatically.
CRYPTO_PAIRS = {
    "BTC-USD":   "Bitcoin",
    "ETH-USD":   "Ethereum",
    "SOL-USD":   "Solana",
    "BNB-USD":   "BNB",
    "XRP-USD":   "XRP",
    "ADA-USD":   "Cardano",
    "AVAX-USD":  "Avalanche",
    "DOGE-USD":  "Dogecoin",
    "LINK-USD":  "Chainlink",
    "DOT-USD":   "Polkadot",
    "LTC-USD":   "Litecoin",
    "BCH-USD":   "Bitcoin Cash",
    "AAVE-USD":  "Aave",
    "SHIB-USD":  "Shiba Inu",
    "FIL-USD":   "Filecoin",
    "CRV-USD":   "Curve",
    "SUSHI-USD": "SushiSwap",
    "YFI-USD":   "Yearn",
    "BAT-USD":   "Basic Attention",
}
