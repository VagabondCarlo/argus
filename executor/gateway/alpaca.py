from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, StopOrderRequest, LimitOrderRequest,
    StopLimitOrderRequest, GetAssetsRequest, GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide, TimeInForce, OrderClass, AssetClass, AssetStatus, QueryOrderStatus,
)
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, CryptoLatestQuoteRequest
from shared.config import config
import logging
import math
import time

logger = logging.getLogger(__name__)

_trading = None
_data_client = None
_crypto_data_client = None
_tradable_crypto: set[str] | None = None


def _get_trading():
    global _trading
    if _trading is None:
        _trading = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=True)
    return _trading


def _get_data_client():
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    return _data_client


def _get_crypto_data_client():
    global _crypto_data_client
    if _crypto_data_client is None:
        _crypto_data_client = CryptoHistoricalDataClient()  # crypto quotes need no keys
    return _crypto_data_client


def normalize_symbol(ticker: str) -> str:
    """Separator-insensitive symbol key: BTC-USD, BTC/USD and BTCUSD all match.

    Signals store Yahoo format (BTC-USD), Alpaca orders take BTC/USD, and
    Alpaca positions come back as BTCUSD.
    """
    return ticker.replace("-", "").replace("/", "").upper()


def to_alpaca_crypto(ticker: str) -> str:
    """BTC-USD (signal format) -> BTC/USD (Alpaca order format)."""
    return ticker.replace("-", "/") if "/" not in ticker else ticker


def get_tradable_crypto() -> set[str]:
    """Alpaca-tradable crypto pairs, fetched once and cached (e.g. {'BTC/USD', ...})."""
    global _tradable_crypto
    if _tradable_crypto is None:
        try:
            assets = _get_trading().get_all_assets(
                GetAssetsRequest(asset_class=AssetClass.CRYPTO, status=AssetStatus.ACTIVE)
            )
            _tradable_crypto = {a.symbol for a in assets if a.tradable}
            logger.info(f"Alpaca tradable crypto pairs: {sorted(_tradable_crypto)}")
        except Exception as e:
            logger.error(f"Failed to fetch crypto assets: {e}")
            return set()  # don't cache a failure
    return _tradable_crypto


def is_crypto_tradable(ticker: str) -> bool:
    return to_alpaca_crypto(ticker) in get_tradable_crypto()


def get_account():
    try:
        acct = _get_trading().get_account()
        return {
            "cash": float(acct.cash),
            "portfolio_value": float(acct.portfolio_value),
            "buying_power": float(acct.buying_power),
            "pnl_today": float(acct.equity) - float(acct.last_equity),
        }
    except Exception as e:
        logger.error(f"Failed to get account: {e}")
        return {}


def get_latest_price(ticker: str, asset_type: str = "stock") -> float | None:
    try:
        if asset_type == "crypto":
            symbol = to_alpaca_crypto(ticker)
            req = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = _get_crypto_data_client().get_crypto_latest_quote(req)
            return float(quote[symbol].ask_price)
        req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
        quote = _get_data_client().get_stock_latest_quote(req)
        return float(quote[ticker].ask_price)
    except Exception as e:
        logger.error(f"Failed to get price for {ticker}: {e}")
        return None


def get_open_positions():
    try:
        positions = _get_trading().get_all_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": float(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.unrealized_pl),
                "asset_class": "crypto" if p.asset_class == AssetClass.CRYPTO else "stock",
            }
            for p in positions
        ]
    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        return []


def cancel_open_orders(ticker: str) -> int:
    """Cancel resting orders (stop/take-profit legs) for one symbol.

    Must run before close_position on stocks — resting sell orders hold the
    shares, and Alpaca rejects the close with 'insufficient qty available'.
    """
    try:
        client = _get_trading()
        orders = client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[ticker])
        )
        for o in orders:
            client.cancel_order_by_id(o.id)
        return len(orders)
    except Exception as e:
        logger.error(f"Failed to cancel orders for {ticker}: {e}")
        return 0


def calculate_position_size(price: float, stop_loss: float, asset_type: str = "stock") -> float:
    capital = config.ACCOUNT_CAPITAL
    max_risk_per_trade = capital * config.STOP_LOSS_PCT
    risk_per_share = abs(price - stop_loss)

    if risk_per_share <= 0:
        return 0.0

    shares = max_risk_per_trade / risk_per_share

    max_position_value = capital * config.MAX_POSITION_SIZE
    max_shares_by_value = max_position_value / price
    shares = min(shares, max_shares_by_value)

    if asset_type == "crypto":
        # BTC at $100k+ needs 6-decimal qty; 2-decimal rounding zeroes it out.
        # Alpaca minimum crypto order is ~$10 notional.
        qty = round(shares, 6)
        return qty if qty * price >= 10.0 else 0.0

    return round(shares, 2) if shares >= 0.01 else 0.0


def preflight_check(ticker: str, side: str) -> str | None:
    positions = get_open_positions()

    if len(positions) >= config.MAX_OPEN_POSITIONS:
        return f"Max {config.MAX_OPEN_POSITIONS} positions reached"

    for p in positions:
        if normalize_symbol(p["ticker"]) == normalize_symbol(ticker):
            return f"Already holding {ticker}"

    acct = get_account()
    if not acct:
        return "Cannot reach Alpaca account"

    daily_pnl = acct.get("pnl_today", 0)
    if daily_pnl <= -(config.ACCOUNT_CAPITAL * config.DAILY_LOSS_LIMIT):
        return f"Daily loss limit hit (${daily_pnl:+.2f})"

    return None


def place_order(ticker: str, side: str, qty: float, stop_loss_price: float,
                take_profit_price: float | None = None, asset_type: str = "stock") -> dict:
    client = _get_trading()

    block = preflight_check(ticker, side)
    if block:
        logger.warning(f"Order blocked for {ticker}: {block}")
        return {"error": block}

    price = get_latest_price(ticker, asset_type)
    if not price:
        return {"error": "Cannot get current price"}

    sized_qty = calculate_position_size(price, stop_loss_price, asset_type)
    if sized_qty <= 0:
        return {"error": "Position too small after risk sizing"}

    qty = min(qty, sized_qty)
    order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
    symbol = to_alpaca_crypto(ticker) if asset_type == "crypto" else ticker
    # Alpaca crypto only accepts GTC/IOC, and doesn't support stop or bracket
    # orders — the position monitor is the stop for crypto positions.
    tif = TimeInForce.GTC if asset_type == "crypto" else TimeInForce.DAY

    logger.info(
        f"Placing {side} {qty} {symbol} @ ~${price:.2f} "
        f"stop=${stop_loss_price:.2f} target=${take_profit_price or 'none'}"
    )

    try:
        order = client.submit_order(MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=tif
        ))
        logger.info(f"Entry filled: {side} {qty} {symbol} | ID: {order.id}")
    except Exception as e:
        logger.error(f"Market order failed for {symbol}: {e}")
        return {"error": str(e)}

    if asset_type == "crypto":
        return {
            "order_id": str(order.id),
            "status": str(order.status),
            "qty": float(qty),
            "risk_sized": True,
        }

    time.sleep(2)
    stop_qty = int(math.floor(qty))
    stop_side = OrderSide.SELL if side == "BUY" else OrderSide.BUY

    if stop_qty >= 1:
        try:
            client.submit_order(StopOrderRequest(
                symbol=ticker,
                qty=stop_qty,
                side=stop_side,
                time_in_force=TimeInForce.GTC,
                stop_price=round(stop_loss_price, 2)
            ))
            logger.info(f"Stop-loss set: ${stop_loss_price:.2f} for {stop_qty} {ticker}")
        except Exception as e:
            logger.warning(f"Stop-loss failed for {ticker}: {e}")

    if take_profit_price and stop_qty >= 1:
        try:
            client.submit_order(LimitOrderRequest(
                symbol=ticker,
                qty=stop_qty,
                side=stop_side,
                time_in_force=TimeInForce.GTC,
                limit_price=round(take_profit_price, 2)
            ))
            logger.info(f"Take-profit set: ${take_profit_price:.2f} for {stop_qty} {ticker}")
        except Exception as e:
            logger.warning(f"Take-profit failed for {ticker}: {e}")

    return {
        "order_id": str(order.id),
        "status": str(order.status),
        "qty": float(qty),
        "risk_sized": True,
    }


def close_position(ticker: str) -> dict:
    """Close a position. Includes the actual fill price when the close order
    fills within a couple of seconds; callers fall back to their snapshot price."""
    try:
        order = _get_trading().close_position(ticker)
        fill_price = None
        try:
            time.sleep(2)
            filled = _get_trading().get_order_by_id(order.id)
            if filled.filled_avg_price:
                fill_price = float(filled.filled_avg_price)
        except Exception:
            pass
        return {"closed": ticker, "fill_price": fill_price}
    except Exception as e:
        logger.error(f"Failed to close {ticker}: {e}")
        return {"error": str(e)}


def close_all_positions() -> dict:
    try:
        _get_trading().close_all_positions(cancel_orders=True)
        return {"closed": "all"}
    except Exception as e:
        logger.error(f"Failed to close all positions: {e}")
        return {"error": str(e)}
