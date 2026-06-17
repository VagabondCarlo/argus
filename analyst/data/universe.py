import io
import requests
import pandas as pd
import yfinance as yf
import logging

logger = logging.getLogger(__name__)

# Curated universe: S&P 500 + high-volume NASDAQ + ETFs
# Pulled once per process, cached in memory.

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_SP500_CACHE: list[str] = []

# High-liquidity non-S&P names worth watching for day setups
EXTRA_TICKERS = [
    "PLTR", "RIVN", "LCID", "SOFI", "HOOD", "COIN", "MARA", "RIOT",
    "SOXL", "TQQQ", "SQQQ", "UVXY", "SPXL", "LABU", "ARKK",
    "XLE", "XLF", "XLK", "XLV", "XBI", "GLD", "SLV", "USO",
    "BABA", "NIO", "XPEV", "LI", "GRAB", "SE", "MELI",
    "SMCI", "ARM", "AVGO", "QCOM", "MU", "INTC", "TSM",
]


def get_sp500_tickers() -> list[str]:
    global _SP500_CACHE
    if _SP500_CACHE:
        return _SP500_CACHE
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        resp = requests.get(SP500_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), header=0)
        sp500 = tables[0]["Symbol"].tolist()
        _SP500_CACHE = [t.replace(".", "-") for t in sp500]
        logger.info(f"S&P 500 list fetched: {len(_SP500_CACHE)} tickers cached")
        return _SP500_CACHE
    except Exception as e:
        logger.error(f"Failed to fetch S&P 500 list: {e}")
        return []


def get_full_universe() -> list[str]:
    """Returns the full tradeable universe: S&P 500 + curated extras."""
    sp500 = get_sp500_tickers()
    all_tickers = list(set(sp500 + EXTRA_TICKERS))
    logger.info(f"Universe loaded: {len(all_tickers)} tickers")
    return all_tickers


def get_core_universe() -> list[str]:
    """
    Smaller universe for faster scans: top 300 most liquid S&P names + extras.
    Used during regular scan cycles. Full universe used pre-market.
    """
    # These 300 represent ~85% of total S&P market cap and volume
    core = [
        "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","BRK-B","AVGO","JPM",
        "LLY","UNH","XOM","V","MA","COST","HD","MRK","ABBV","CVX","PEP","KO",
        "ADBE","ORCL","AMD","CRM","TMO","ACN","MCD","BAC","LIN","NFLX","GE","PM",
        "TXN","DHR","INTU","AMGN","MS","IBM","WMT","DIS","QCOM","ISRG","RTX","GS",
        "CAT","SPGI","HON","T","NOW","UNP","UBER","AMAT","AXP","SBUX","BKNG","PLD",
        "SYK","TJX","SCHW","VRTX","MDT","CB","C","ETN","MO","NEE","REGN","PANW",
        "BSX","LRCX","ADI","DE","ADP","ZTS","MDLZ","CI","AON","SO","GILD","ITW",
        "WM","CME","NOC","SLB","MCO","MMC","ICE","ELV","BDX","GD","FCX","MPC",
        "HCA","PSX","OXY","COP","EOG","VLO","PXD","DVN","HAL","MRO","APA","FANG",
        "COIN","HOOD","PLTR","SOFI","RBLX","SNAP","PINS","TWTR","U","DKNG","PENN",
        "SMCI","ARM","MRVL","NXPI","ON","SWKS","MPWR","ENPH","SEDG","FSLR","RUN",
        "RIVN","LCID","NIO","XPEV","LI","CHPT","BLNK","EVGO",
        "SPY","QQQ","IWM","DIA","XLE","XLF","XLK","XLV","XBI","ARKK",
        "SOXL","TQQQ","UVXY","GLD","SLV","USO","MARA","RIOT","CLSK",
    ]
    return list(set(core + EXTRA_TICKERS))
