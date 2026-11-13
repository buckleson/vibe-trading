"""Order functions of the paper broker.

The paper broker has no broker account behind it, so nothing can be sent to an
exchange. The app runs it in Sandbox (analyzer) mode, where every order goes to
the Sandbox engine and never reaches this module. If a live order does arrive
here (analyzer mode switched off, or a caller that forces live), it is refused
with a sentence the trader can act on, and the books are empty.

Every function of the common order contract is present with the usual return
shape, so the services that import them work unchanged.
"""

from types import SimpleNamespace

from utils.logging import get_logger

logger = get_logger(__name__)

LIVE_ORDERS_REFUSED = (
    "Live orders are not available without a broker account. "
    "Switch to Sandbox mode to place this order."
)
REFUSED_STATUS = 400


def _refusal(action: str) -> dict:
    logger.warning(f"Refused a live {action} on the paper broker: Sandbox mode is required")
    return {"status": "error", "message": LIVE_ORDERS_REFUSED}


def _response(status: int) -> SimpleNamespace:
    """A minimal response object: services read ``.status`` (some ``.status_code``)."""
    return SimpleNamespace(status=status, status_code=status)


def _empty_book() -> dict:
    return {"status": "success", "data": []}


def get_order_book(auth):
    """The live order book: always empty."""
    return _empty_book()


def get_trade_book(auth):
    """The live trade book: always empty."""
    return _empty_book()


def get_positions(auth):
    """The live position book: always empty."""
    return _empty_book()


def get_holdings(auth):
    """The live holdings: always empty."""
    return _empty_book()


def get_open_position(tradingsymbol, exchange, producttype, auth):
    """Net quantity held live, as a string: always "0"."""
    return "0"


def place_order_api(data, auth):
    """Refuse a live order. Returns (response, response_data, orderid)."""
    return _response(REFUSED_STATUS), _refusal("order"), None


def place_smartorder_api(data, auth):
    """Refuse a live smart order. Returns (response, response_data, orderid)."""
    return _response(REFUSED_STATUS), _refusal("smart order"), None


def close_all_positions(current_api_key, auth):
    """Refuse a live close-all. Returns (response_data, status_code)."""
    return _refusal("close of all positions"), REFUSED_STATUS


def cancel_order(orderid, auth):
    """Refuse a live cancel. Returns (response_data, status_code)."""
    response = _refusal("cancel")
    response["orderid"] = orderid
    return response, REFUSED_STATUS


def modify_order(data, auth):
    """Refuse a live modify. Returns (response_data, status_code)."""
    response = _refusal("modify")
    response["orderid"] = (data or {}).get("orderid")
    return response, REFUSED_STATUS


def cancel_all_orders_api(data, auth):
    """There are no live orders to cancel. Returns (canceled, failed)."""
    logger.info("Cancel all on the paper broker: no live orders exist")
    return [], []
