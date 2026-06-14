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

CRYPTO_PAIRS = {
    "BTC-USD":  "Bitcoin",
    "ETH-USD":  "Ethereum",
    "SOL-USD":  "Solana",
    "BNB-USD":  "BNB",
    "XRP-USD":  "XRP",
    "ADA-USD":  "Cardano",
    "AVAX-USD": "Avalanche",
    "DOGE-USD": "Dogecoin",
    "LINK-USD": "Chainlink",
}
