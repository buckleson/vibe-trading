"""Book mapping of the paper broker.

The live books of the paper broker are always empty (Sandbox mode keeps its own
books in sandbox.db), so these functions only have to turn an empty book into
OpenAlgo's empty shapes. They accept the rows OpenAlgo's common shape would
carry, so a non-empty list passes through unchanged.
"""


def _rows(book):
    """The list of rows inside a book reply (a dict with "data", or a list)."""
    if isinstance(book, dict):
        book = book.get("data") or []
    return [row for row in (book or []) if isinstance(row, dict)]


def map_order_data(order_data):
    return _rows(order_data)


def calculate_order_statistics(order_data):
    rows = _rows(order_data)
    status = [str(row.get("order_status", "")).lower() for row in rows]
    return {
        "total_buy_orders": sum(1 for row in rows if row.get("action") == "BUY"),
        "total_sell_orders": sum(1 for row in rows if row.get("action") == "SELL"),
        "total_completed_orders": status.count("complete"),
        "total_open_orders": status.count("open"),
        "total_rejected_orders": status.count("rejected"),
    }


def transform_order_data(orders):
    return _rows(orders)


def map_trade_data(trade_data):
    return _rows(trade_data)


def transform_tradebook_data(tradebook_data):
    return _rows(tradebook_data)


def map_position_data(position_data):
    return _rows(position_data)


def transform_positions_data(positions_data):
    return _rows(positions_data)


def map_portfolio_data(portfolio_data):
    return _rows(portfolio_data)


def calculate_portfolio_statistics(holdings_data):
    rows = _rows(holdings_data)
    value = sum(float(r.get("quantity", 0)) * float(r.get("ltp", 0)) for r in rows)
    invested = sum(float(r.get("quantity", 0)) * float(r.get("average_price", 0)) for r in rows)
    pnl = sum(float(r.get("pnl", 0)) for r in rows)
    return {
        "totalholdingvalue": value,
        "totalinvvalue": invested,
        "totalprofitandloss": pnl,
        "totalpnlpercentage": (pnl / invested * 100) if invested else 0,
    }


def transform_holdings_data(holdings_data):
    return _rows(holdings_data)
