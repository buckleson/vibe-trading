"""Sign-in of the paper broker: no broker account, nothing to exchange.

``authenticate_broker`` returns the fixed session token the rest of the plugin
expects, in the ``(auth_token, error)`` shape ``blueprints/brlogin.py`` and
``utils/plugin_loader.py`` require.
"""

from utils.logging import get_logger

logger = get_logger(__name__)

#: The broker token stored for a paper session.
PAPER_AUTH_TOKEN = "paper-session"
#: The feed token stored beside it.
PAPER_FEED_TOKEN = "paper-feed"


def authenticate_broker(code=None, *args, **kwargs):
    """Start a paper session. Never fails and calls no network.

    Args:
        code: Ignored; accepted so the generic callback path can call it.

    Returns:
        tuple[str, None]: (auth token, no error).
    """
    logger.info("Paper broker session started (no broker account, Sandbox mode only)")
    return PAPER_AUTH_TOKEN, None


def is_paper_token(auth_token) -> bool:
    """Whether a stored token is a paper session token."""
    return bool(auth_token) and str(auth_token).startswith("paper")
