from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from shared.config import config
from shared.database import get_todays_trades
import logging

logger = logging.getLogger(__name__)

trading = TradingClient(
    config.ALPACA_API_KEY,
    config.ALPACA_SECRET_KEY,
    paper=True
)

data_client = StockHistoricalDataClient(
    config.ALPACA_API_KEY,
    config.ALPACA_SECRET_KEY
)


def get_account():
    try:
        acct = trading.get_account()
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
        quote = data_client.get_stock_latest_quote(req)
        return float(quote[ticker].ask_price)
    except Exception as e:
        logger.error(f"Failed to get price for {ticker}: {e}")
        return None


def get_open_positions():
    try:
        positions = trading.get_all_positions()
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


def place_order(ticker: str, side: str, qty: float, stop_loss_price: float) -> dict:
    try:
        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL

        # Entry order
        order = trading.submit_order(MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY
        ))

        logger.info(f"Order placed: {side} {qty} {ticker} | ID: {order.id}")

        # Attach stop-loss
        if side == "BUY":
            trading.submit_order(TrailingStopOrderRequest(
                symbol=ticker,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                trail_price=str(round(stop_loss_price, 2))
            ))

        return {
            "order_id": str(order.id),
            "status": str(order.status),
            "qty": float(qty),
        }

    except Exception as e:
        logger.error(f"Order failed for {ticker}: {e}")
        return {"error": str(e)}


def close_position(ticker: str) -> dict:
    try:
        trading.close_position(ticker)
        return {"closed": ticker}
    except Exception as e:
        logger.error(f"Failed to close {ticker}: {e}")
        return {"error": str(e)}


def close_all_positions() -> list:
    try:
        trading.close_all_positions(cancel_orders=True)
        return {"closed": "all"}
    except Exception as e:
        logger.error(f"Failed to close all positions: {e}")
        return {"error": str(e)}


def trades_this_week() -> int:
    trades = get_todays_trades()
    return len(trades)
