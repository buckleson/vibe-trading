"""Funds of the paper broker.

There is no broker account, so the live funds view reports the same capital
the Sandbox starts with (1 Crore) and nothing used. Sandbox mode keeps its own
funds in sandbox.db and never calls this; it is also what a resumed session is
validated with (a non-empty answer means the session is usable).
"""

from broker.paper.api.auth_api import is_paper_token
from utils.logging import get_logger

logger = get_logger(__name__)

PAPER_CAPITAL = 10_000_000.0


def get_margin_data(auth_token):
    """Funds in OpenAlgo's common shape; empty for a token that is not a paper session."""
    if not is_paper_token(auth_token):
        logger.warning("Paper funds requested with a token that is not a paper session")
        return {}
    return {
        "availablecash": f"{PAPER_CAPITAL:.2f}",
        "collateral": "0.00",
        "m2munrealized": "0.00",
        "m2mrealized": "0.00",
        "utiliseddebits": "0.00",
    }


def test_auth_token(auth_token):
    """(valid, error) for a stored token, as some session checks ask for it."""
    if is_paper_token(auth_token):
        return True, None
    return False, "This is not a paper session. Log in again."
