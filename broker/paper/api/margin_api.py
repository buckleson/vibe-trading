"""Margin estimate of the paper broker.

No broker answers this, so the margin is estimated locally from the current
(live or simulated) price: equity delivery at full value, intraday at 20%,
futures at 12% of contract value plus 3% exposure, long options at the premium
and short options as futures-like margin on the underlying. Spread benefits
are not modelled: the legs are summed.
"""

from types import SimpleNamespace

from broker.paper.api import market_data
from utils.logging import get_logger

logger = get_logger(__name__)

SPAN_RATE = 0.12
EXPOSURE_RATE = 0.03
INTRADAY_RATE = 0.20


def _price(position: dict) -> float:
    try:
        price = float(position.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    if price > 0 and str(position.get("pricetype", "")).upper() in ("LIMIT", "SL"):
        return price
    return float(market_data.snapshot(position["symbol"], position["exchange"])["ltp"])


def _leg_margin(position: dict) -> tuple[float, float]:
    """(span, exposure) of one leg."""
    symbol = position["symbol"]
    exchange = position["exchange"]
    quantity = abs(int(float(position.get("quantity") or 0)))
    action = str(position.get("action", "BUY")).upper()
    product = str(position.get("product", "MIS")).upper()
    kind, details = market_data.classify(symbol, exchange)
    price = _price(position)

    if kind == "equity":
        value = price * quantity
        if product == "CNC":
            return value, 0.0
        return value * INTRADAY_RATE, 0.0
    if kind == "future":
        value = price * quantity
        return value * SPAN_RATE, value * EXPOSURE_RATE
    if kind == "option":
        if action == "BUY":
            return price * quantity, 0.0
        spot, _source = market_data.underlying_spot(details["underlying"])
        value = spot * quantity
        return value * SPAN_RATE, value * EXPOSURE_RATE
    return 0.0, 0.0


def calculate_margin_api(positions, auth):
    """Estimate margin for one or more legs. Returns (response, response_data)."""
    span_total = exposure_total = 0.0
    try:
        for position in positions:
            span, exposure = _leg_margin(position)
            span_total += span
            exposure_total += exposure
    except Exception:
        logger.exception("Paper margin estimate failed")
        return SimpleNamespace(status=400, status_code=400), {
            "status": "error",
            "message": "The margin could not be estimated for these positions. "
            "Check the symbols and quantities.",
        }
    total = span_total + exposure_total
    return SimpleNamespace(status=200, status_code=200), {
        "status": "success",
        "data": {
            "total_margin_required": round(total, 2),
            "span_margin": round(span_total, 2),
            "exposure_margin": round(exposure_total, 2),
        },
    }

