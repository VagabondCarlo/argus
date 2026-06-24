from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, StopOrderRequest, LimitOrderRequest,
    StopLimitOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from shared.config import config
import logging
import math
import time

logger = logging.getLogger(__name__)

_trading = None
_data_client = None


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


def get_latest_price(ticker: str) -> float | None:
    try:
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
            }
            for p in positions
        ]
    except Exception as e:
        logger.error(f"Failed to get positions: {e}")
        return []


def calculate_position_size(price: float, stop_loss: float) -> float:
    capital = config.ACCOUNT_CAPITAL
    max_risk_per_trade = capital * config.STOP_LOSS_PCT
    risk_per_share = abs(price - stop_loss)

    if risk_per_share <= 0:
        return 0.0

    shares = max_risk_per_trade / risk_per_share

    max_position_value = capital * config.MAX_POSITION_SIZE
    max_shares_by_value = max_position_value / price
    shares = min(shares, max_shares_by_value)

    return round(shares, 2) if shares >= 0.01 else 0.0


def preflight_check(ticker: str, side: str) -> str | None:
    positions = get_open_positions()

    if len(positions) >= config.MAX_OPEN_POSITIONS:
        return f"Max {config.MAX_OPEN_POSITIONS} positions reached"

    for p in positions:
        if p["ticker"] == ticker:
            return f"Already holding {ticker}"

    acct = get_account()
    if not acct:
        return "Cannot reach Alpaca account"

    daily_pnl = acct.get("pnl_today", 0)
    if daily_pnl <= -(config.ACCOUNT_CAPITAL * config.DAILY_LOSS_LIMIT):
        return f"Daily loss limit hit (${daily_pnl:+.2f})"

    return None


def place_order(ticker: str, side: str, qty: float, stop_loss_price: float,
                take_profit_price: float | None = None) -> dict:
    client = _get_trading()

    block = preflight_check(ticker, side)
    if block:
        logger.warning(f"Order blocked for {ticker}: {block}")
        return {"error": block}

    price = get_latest_price(ticker)
    if not price:
        return {"error": "Cannot get current price"}

    sized_qty = calculate_position_size(price, stop_loss_price)
    if sized_qty <= 0:
        return {"error": "Position too small after risk sizing"}

    qty = min(qty, sized_qty)
    order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL

    logger.info(
        f"Placing {side} {qty} {ticker} @ ~${price:.2f} "
        f"stop=${stop_loss_price:.2f} target=${take_profit_price or 'none'}"
    )

    try:
        order = client.submit_order(MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY
        ))
        logger.info(f"Entry filled: {side} {qty} {ticker} | ID: {order.id}")
    except Exception as e:
        logger.error(f"Market order failed for {ticker}: {e}")
        return {"error": str(e)}

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
    try:
        _get_trading().close_position(ticker)
        return {"closed": ticker}
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
