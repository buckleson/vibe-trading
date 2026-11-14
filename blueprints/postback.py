"""
Broker postback (webhook) receivers for real-time order updates.

Public POST routes at /postback/<broker>. Brokers cannot authenticate with
OpenAlgo sessions, so these are CSRF-exempt (see app.py) and a postback is
accepted only when the payload itself proves who sent it:
- Zerodha payloads carry a SHA-256 checksum (order_id + order_timestamp +
  api_secret) that is verified against BROKER_API_SECRET, and
- the <broker> in the URL must match the instance's active broker session
  (single-user-per-deployment, per CLAUDE.md).

A postback from any other broker carries nothing of the kind, so it is
refused (see VERIFIED_BROKERS). The URL names only the broker,
which is public, and an accepted postback becomes a live order update that
the strategy engine applies to its orders and that can fire an order-placing
Flow workflow. Anyone who could reach the server could post a fill that never
happened. Order updates for other brokers arrive through their order WebSocket
adapters instead, which OpenAlgo opens itself with the broker token.

Each route parses the broker payload, normalizes it into OpenAlgo's common
order-update format (reusing the status/pricetype/product tables from the
corresponding broker/*/streaming/*_order_adapter.py — single source of
truth), and publishes events.OrderUpdateEvent on the in-process event bus.
The registered subscribers fan out to socketio + the websocket_proxy relay,
identical to the order-WebSocket ingestion path.

This is the production-friendly *secondary* path: postbacks require a public
HTTPS URL registered with the broker (rejected for localhost), while the
dedicated order-WebSocket adapters work everywhere. If both are configured,
clients may see duplicate updates for the same transition — deduplicate on
(orderid, order_status, filled_quantity).
"""

import hashlib
import hmac
import os

from flask import Blueprint, jsonify, request

from database.auth_db import Auth
from utils.event_bus import bus
from utils.logging import get_logger
from websocket_proxy.order_adapter import to_openalgo_symbol

logger = get_logger(__name__)

postback_bp = Blueprint("postback_bp", __name__, url_prefix="/postback")

SUPPORTED_BROKERS = {"zerodha"}

#: Brokers whose postbacks prove their sender. A broker belongs here only when
#: its payload carries something a stranger cannot produce (a signature made
#: with the API secret, as Zerodha's is) and this module checks it.
VERIFIED_BROKERS = frozenset({"zerodha"})

#: One answer for every refusal, so the reply does not tell a caller which
#: broker is logged in, or which check it failed.
_REFUSED = ({"status": "error", "message": "Postback not accepted"}, 403)

def _get_active_session() -> Auth | None:
    """Return the instance's active (non-revoked) broker session, if any."""
    try:
        return Auth.query.filter_by(is_revoked=False).first()
    except Exception:
        logger.exception("Postback: failed to read active broker session")
        return None


def _publish(user_id: str, broker: str, fields: dict) -> None:
    from events import OrderUpdateEvent

    fields.setdefault("mode", "live")
    fields.setdefault("broker", broker)
    fields.setdefault("api_type", f"{broker}.postback")
    fields.setdefault("request_data", {"user_id": user_id})
    bus.publish(OrderUpdateEvent(**fields))


# --- per-broker payload normalizers ------------------------------------------
# Each returns OrderUpdateEvent kwargs or None if the payload is not an order
# event. They reuse the _STATUS_MAP/_PRICETYPE_MAP/_PRODUCT_MAP tables defined
# in the corresponding streaming order adapters.


def _normalize_zerodha(data: dict) -> dict | None:
    from broker.zerodha.streaming.zerodha_order_adapter import _STATUS_MAP

    raw_status = str(data.get("status", "")).upper()
    order_status = _STATUS_MAP.get(raw_status, raw_status.lower() or "open")
    exchange = data.get("exchange", "")
    return {
        "orderid": str(data.get("order_id", "")),
        "symbol": to_openalgo_symbol(data.get("tradingsymbol", ""), exchange),
        "exchange": exchange,
        "action": str(data.get("transaction_type", "")).upper(),
        "quantity": int(data.get("quantity") or 0),
        "price": float(data.get("price") or 0),
        "trigger_price": float(data.get("trigger_price") or 0),
        "pricetype": data.get("order_type", ""),
        "product": data.get("product", ""),
        "order_status": order_status,
        "filled_quantity": int(data.get("filled_quantity") or 0),
        "pending_quantity": int(
            data.get("pending_quantity") or data.get("unfilled_quantity") or 0
        ),
        "average_price": float(data.get("average_price") or 0),
        "rejection_reason": (data.get("status_message") or "")
        if order_status == "rejected"
        else "",
    }


_NORMALIZERS = {
    "zerodha": _normalize_zerodha,
}


def _validate_zerodha_checksum(data: dict) -> bool:
    """Zerodha postbacks carry checksum = SHA-256(order_id + order_timestamp +
    api_secret) — see broker-api-docs/zerodha-api-docs/12-postbacks.md."""
    api_secret = os.getenv("BROKER_API_SECRET", "")
    checksum = str(data.get("checksum", ""))
    order_id = str(data.get("order_id", ""))
    order_timestamp = str(data.get("order_timestamp", ""))
    if not (api_secret and checksum and order_id):
        return False
    expected = hashlib.sha256(
        f"{order_id}{order_timestamp}{api_secret}".encode()
    ).hexdigest()
    return hmac.compare_digest(checksum, expected)


@postback_bp.route("/<broker>", methods=["POST"])
def broker_postback(broker: str):
    broker = broker.lower()
    if broker not in SUPPORTED_BROKERS:
        return jsonify({"status": "error", "message": f"Unsupported broker: {broker}"}), 404

    # Before anything is read or looked up: a postback with no proof of its
    # sender is never normalized, never published, and is answered the same
    # whichever broker is logged in.
    if broker not in VERIFIED_BROKERS:
        logger.info(
            f"Postback for '{broker}' not accepted: its postbacks carry no proof of the sender"
        )
        return jsonify(_REFUSED[0]), _REFUSED[1]

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        # Some brokers POST form-encoded payloads with a JSON body field.
        data = request.form.to_dict() or None
    if not isinstance(data, dict) or not data:
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    if broker == "zerodha" and not _validate_zerodha_checksum(data):
        logger.warning("Zerodha postback rejected: checksum validation failed")
        return jsonify(_REFUSED[0]), _REFUSED[1]

    session_obj = _get_active_session()
    if session_obj is None or (session_obj.broker or "").lower() != broker:
        logger.warning(f"Postback for '{broker}' rejected: no matching active broker session")
        return jsonify(_REFUSED[0]), _REFUSED[1]

    try:
        fields = _NORMALIZERS[broker](data)
    except Exception:
        logger.exception(f"Postback normalization failed for {broker}")
        return jsonify({"status": "error", "message": "Payload normalization failed"}), 400

    if fields:
        _publish(session_obj.name, broker, fields)
        logger.info(
            f"Postback order update ({broker}): orderid={fields.get('orderid')} "
            f"status={fields.get('order_status')}"
        )

    return jsonify({"status": "success"}), 200
