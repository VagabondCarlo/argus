from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from shared.config import config
from shared.database import get_conn
import logging
from datetime import date, timedelta

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


def place_order(ticker: str, side: str, qty: float, stop_loss_price: float) -> dict:
    try:
        client = _get_trading()
        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL

        # Entry market order
        order = client.submit_order(MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY
        ))
        logger.info(f"Order placed: {side} {qty} {ticker} | ID: {order.id}")

        # Protective stop-loss order (opposite side)
        stop_side = OrderSide.SELL if side == "BUY" else OrderSide.BUY
        client.submit_order(StopOrderRequest(
            symbol=ticker,
            qty=qty,
            side=stop_side,
            time_in_force=TimeInForce.GTC,
            stop_price=round(stop_loss_price, 2)
        ))
        logger.info(f"Stop-loss set at ${stop_loss_price:.2f} for {ticker}")

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
        _get_trading().close_position(ticker)
        return {"closed": ticker}
    except Exception as e:
        logger.error(f"Failed to close {ticker}: {e}")
        return {"error": str(e)}


def close_all_positions() -> list:
    try:
        _get_trading().close_all_positions(cancel_orders=True)
        return {"closed": "all"}
    except Exception as e:
        logger.error(f"Failed to close all positions: {e}")
        return {"error": str(e)}


def trades_this_week() -> int:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE date(executed_at) >= ?",
            (monday.isoformat(),)
        ).fetchone()
    return row["cnt"] if row else 0
