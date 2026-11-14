# websocket_proxy/__init__.py

import logging

from .base_adapter import (
    ENABLE_CONNECTION_POOLING,
    MAX_SYMBOLS_PER_WEBSOCKET,
    MAX_WEBSOCKET_CONNECTIONS,
    BaseBrokerWebSocketAdapter,
)
from .broker_factory import (
    cleanup_all_pools,
    create_broker_adapter,
    get_pool_stats,
    get_resource_health,
    register_adapter,
)
from .connection_manager import (
    ConnectionPool,
    SharedZmqPublisher,
    get_max_symbols_per_websocket,
    get_max_websocket_connections,
)
from .server import WebSocketProxy
from .server import main as websocket_main

# Set up logger
logger = logging.getLogger(__name__)

# Import the zerodha_adapter
# Import the paper (no broker account) adapter
from broker.paper.streaming.paper_adapter import PaperWebSocketAdapter
from broker.zerodha.streaming.zerodha_adapter import ZerodhaWebSocketAdapter

# Register adapters
register_adapter("zerodha", ZerodhaWebSocketAdapter)
register_adapter("paper", PaperWebSocketAdapter)

__all__ = [
    # Core classes
    "WebSocketProxy",
    "websocket_main",
    "register_adapter",
    "create_broker_adapter",
    # Base adapter (for cleanup utilities)
    "BaseBrokerWebSocketAdapter",
    # Connection pooling (multi-websocket support)
    "ConnectionPool",
    "SharedZmqPublisher",
    "get_pool_stats",
    "get_resource_health",
    "cleanup_all_pools",
    "get_max_symbols_per_websocket",
    "get_max_websocket_connections",
    # Configuration constants
    "MAX_SYMBOLS_PER_WEBSOCKET",
    "MAX_WEBSOCKET_CONNECTIONS",
    "ENABLE_CONNECTION_POOLING",
    # Broker adapters
    "ZerodhaWebSocketAdapter",
    "PaperWebSocketAdapter",
]
