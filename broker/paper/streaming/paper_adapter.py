"""Streaming adapter of the paper broker.

There is no broker WebSocket to connect to: one background thread per adapter
publishes a tick every second for each subscribed symbol, taken from the same
source as the REST quotes (``broker.paper.api.market_data``: Yahoo Finance when
reachable, the simulated feed otherwise), so a streamed price and a quote
agree.

Ticks go to the ZeroMQ bus through ``BaseBrokerWebSocketAdapter``, whose PUB
socket CONNECTs to the proxy's bound SUB (or the pool's shared publisher):
this adapter never binds. Topics follow the common format
``{EXCHANGE}_{SYMBOL}_{LTP|QUOTE|DEPTH}``.
"""

import threading
import time
from typing import Any

from broker.paper.api import market_data
from utils import real_threading
from utils.logging import get_logger
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

logger = get_logger("paper_websocket")

TICK_SECONDS = 1.0
MODE_TOPICS = {1: "LTP", 2: "QUOTE", 3: "DEPTH", 4: "DEPTH"}
SUPPORTED_DEPTH = 5


class PaperWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Publishes ticks of the paper feed for the subscribed symbols."""

    def __init__(self):
        super().__init__()
        self.broker_name = "paper"
        self.user_id = None
        self.running = False
        self.connected = False
        self.lock = real_threading.Lock()
        self._stop = real_threading.Event()
        self._thread = None
        # (exchange, symbol) -> set of subscribed modes
        self._modes: dict[tuple[str, str], set[int]] = {}

    # -- lifecycle ------------------------------------------------------------

    def initialize(self, broker_name: str, user_id: str, auth_data: dict | None = None) -> dict[str, Any]:
        self.user_id = user_id
        logger.info(f"Paper feed initialized for user {user_id}")
        return {"status": "success", "message": "Paper feed initialized"}

    def connect(self) -> dict[str, Any]:
        with self.lock:
            if self.running:
                return {"status": "success", "message": "Already connected"}
            self.running = True
            self.connected = True
            self._stop.clear()
            self._thread = real_threading.Thread(
                target=self._run, name="PaperFeed", daemon=True
            )
            self._thread.start()
        logger.info("Paper feed started")
        return {"status": "success", "message": "Connected successfully"}

    def disconnect(self) -> dict[str, Any]:
        with self.lock:
            self.running = False
            self.connected = False
            thread, self._thread = self._thread, None
            self._modes.clear()
            self.subscriptions.clear()
        self._stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        self.cleanup_zmq()
        logger.info("Paper feed stopped")
        return {"status": "success", "message": "Disconnected"}

    # -- subscriptions --------------------------------------------------------

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> dict[str, Any]:
        if mode not in MODE_TOPICS:
            return self._create_error_response("INVALID_MODE", f"Unsupported mode {mode}")
        with self.lock:
            self._modes.setdefault((exchange, symbol), set()).add(mode)
            self.subscriptions[f"{exchange}_{symbol}_{mode}"] = {
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "depth_level": depth_level,
            }
        # Answer the first tick at once rather than on the next loop.
        self._publish(exchange, symbol, {mode})
        return {
            "status": "success",
            "message": f"Subscribed to {symbol}",
            "broker": self.broker_name,
            "exchange": exchange,
            "requested_depth": depth_level,
            "actual_depth": SUPPORTED_DEPTH,
            "supported_depth": SUPPORTED_DEPTH,
            "fallback_depth": SUPPORTED_DEPTH,
            "is_fallback": depth_level != SUPPORTED_DEPTH,
        }

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        with self.lock:
            modes = self._modes.get((exchange, symbol))
            if modes is not None:
                modes.discard(mode)
                if not modes:
                    del self._modes[(exchange, symbol)]
            self.subscriptions.pop(f"{exchange}_{symbol}_{mode}", None)
        return {"status": "success", "message": f"Unsubscribed from {symbol}"}

    def unsubscribe_all(self) -> dict[str, Any]:
        with self.lock:
            self._modes.clear()
            self.subscriptions.clear()
        return {"status": "success", "message": "Unsubscribed from all symbols"}

    # -- publishing -----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            with self.lock:
                work = [(key, set(modes)) for key, modes in self._modes.items()]
            for (exchange, symbol), modes in work:
                if self._stop.is_set():
                    break
                self._publish(exchange, symbol, modes)
            self._stop.wait(max(0.05, TICK_SECONDS - (time.monotonic() - started)))

    def _publish(self, exchange: str, symbol: str, modes: set[int]) -> None:
        try:
            now = time.time()
            snap = market_data.snapshot(symbol, exchange, now=now)
        except Exception:
            logger.exception(f"Paper feed could not price {exchange}:{symbol}")
            return
        now_ms = int(now * 1000)
        base = {
            "symbol": symbol,
            "exchange": exchange,
            "ltp": snap["ltp"],
            "ltt": now_ms,
            "timestamp": now_ms,
        }
        for mode in modes:
            topic_mode = MODE_TOPICS[mode]
            if topic_mode == "LTP":
                tick = {**base, "mode": "ltp"}
            else:
                tick = {
                    **base,
                    "mode": "quote" if topic_mode == "QUOTE" else "full",
                    "open": snap["open"],
                    "high": snap["high"],
                    "low": snap["low"],
                    "close": snap["prev_close"],
                    "prev_close": snap["prev_close"],
                    "volume": snap["volume"],
                    "oi": snap["oi"],
                    "last_quantity": snap["lotsize"] if snap["kind"] != "index" else 0,
                    "average_price": round((snap["high"] + snap["low"] + snap["ltp"]) / 3, 2),
                    "total_buy_quantity": snap["bid_qty"] * 25,
                    "total_sell_quantity": snap["ask_qty"] * 25,
                    "bid": snap["bid"],
                    "ask": snap["ask"],
                }
                if topic_mode == "DEPTH":
                    bids, asks = market_data.depth_levels(symbol, exchange, snap, now=now)
                    tick["depth"] = {"buy": bids, "sell": asks}
            self.publish_market_data(f"{exchange}_{symbol}_{topic_mode}", tick)
