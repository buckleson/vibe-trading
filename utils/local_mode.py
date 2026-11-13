"""Buckleson local mode: a single-operator install with no sign-in screens.

When ``BUCKLESON_LOCAL_MODE`` is true (the default in this distribution), the
platform runs as a personal desk on the operator's own machine:

* One local operator account is created on first start. Its password is random
  and never shown, because nothing asks for it.
* The built-in ``paper`` broker is logged in automatically, so every page,
  the Sandbox engine and the REST API work without a broker account.
* Sandbox mode is switched on, so every order is simulated.
* An API key is generated so external clients (the Claude Code MCP server,
  scripts) can reach ``/api/v1/`` at once. ``/claude/connect`` shows it.
* Every browser request is given the operator's session before any route runs,
  so the login, setup and broker pages are never needed.

Bind the app to 127.0.0.1 (the default). Local mode trusts every visitor who
can reach the port, exactly as a desktop app trusts whoever sits at it.
"""

from __future__ import annotations

import os
import secrets
import threading
from datetime import UTC, datetime

from flask import request, session

from utils.logging import get_logger

logger = get_logger(__name__)

LOCAL_USER = os.getenv("BUCKLESON_LOCAL_USER", "buckleson")
LOCAL_EMAIL = os.getenv("BUCKLESON_LOCAL_EMAIL", "operator@buckleson.local")
PAPER_BROKER = "paper"
PAPER_AUTH_TOKEN = "paper-session"
PAPER_FEED_TOKEN = "paper-feed"

_bootstrap_lock = threading.Lock()
_bootstrapped = threading.Event()


def enabled() -> bool:
    """Whether local mode is on. On unless the .env turns it off."""
    return os.getenv("BUCKLESON_LOCAL_MODE", "true").strip().lower() in ("1", "true", "yes", "on")


def local_broker() -> str:
    """The broker local mode signs in to: ``paper`` unless .env names another."""
    return os.getenv("BUCKLESON_LOCAL_BROKER", PAPER_BROKER).strip() or PAPER_BROKER


def ensure_api_key() -> str | None:
    """Return the operator's API key, creating one if none exists."""
    from database.auth_db import get_api_key_for_tradingview, upsert_api_key

    key = get_api_key_for_tradingview(LOCAL_USER)
    if key:
        return key
    key = secrets.token_hex(32)
    if upsert_api_key(LOCAL_USER, key) is None:
        logger.error("Local mode could not store the operator API key")
        return None
    logger.info("Local mode generated an API key for the operator")
    return key


def bootstrap() -> bool:
    """Create the operator, the paper broker session, the API key; switch Sandbox on.

    Idempotent and safe to call from the background DB init thread. Returns
    True once the platform is ready to serve the operator.
    """
    if not enabled():
        return False
    if _bootstrapped.is_set():
        return True
    with _bootstrap_lock:
        if _bootstrapped.is_set():
            return True
        try:
            from database.auth_db import get_auth_token, upsert_auth
            from database.settings_db import get_analyze_mode, set_analyze_mode
            from database.user_db import add_user, find_user_by_exact_username

            if find_user_by_exact_username(LOCAL_USER) is None:
                add_user(LOCAL_USER, LOCAL_EMAIL, secrets.token_urlsafe(32), is_admin=True)
                logger.info(f"Local mode created the operator account '{LOCAL_USER}'")

            broker = local_broker()
            if broker == PAPER_BROKER and get_auth_token(LOCAL_USER, bypass_cache=True) is None:
                upsert_auth(
                    LOCAL_USER,
                    PAPER_AUTH_TOKEN,
                    PAPER_BROKER,
                    feed_token=PAPER_FEED_TOKEN,
                    user_id=LOCAL_USER,
                )
                logger.info("Local mode signed in to the paper broker")

            ensure_api_key()

            if not get_analyze_mode():
                set_analyze_mode(True)
                logger.info("Local mode switched Sandbox mode on")

            if broker == PAPER_BROKER:
                _load_master_contract(broker)

            _bootstrapped.set()
            return True
        except Exception:
            logger.exception("Local mode bootstrap failed")
            return False


def _load_master_contract(broker: str) -> None:
    """Download (or load the cached) master contract for the local broker."""
    try:
        from utils.auth_utils import (
            should_download_master_contract,
            try_start_cached_master_contract_load,
            try_start_master_contract_download,
        )

        should_download, reason = should_download_master_contract(broker)
        if should_download:
            try_start_master_contract_download(broker, reset_status=True)
        else:
            logger.info(f"Local mode using cached {broker} master contract: {reason}")
            try_start_cached_master_contract_load(broker)
    except Exception:
        logger.exception(f"Local mode could not load the {broker} master contract")


_SKIP_PREFIXES = ("/static/", "/assets/", "/api/v1/", "/socket.io", "/_reload-ws", "/mcp")


def attach_operator_session() -> None:
    """Before-request hook: give this browser the operator's session.

    Runs before any session check, so every page and SPA endpoint sees a
    signed-in operator with the local broker logged in.
    """
    if not enabled():
        return
    path = request.path or "/"
    if path.startswith(_SKIP_PREFIXES):
        return
    if session.get("logged_in") and session.get("user") == LOCAL_USER and session.get("local_mode"):
        return
    if not _bootstrapped.is_set() and not bootstrap():
        return

    from utils.session import mark_signed_in, set_session_login_time

    session.clear()
    session["user"] = LOCAL_USER
    session["user_session_key"] = LOCAL_USER
    session["broker"] = local_broker()
    session["logged_in"] = True
    session["local_mode"] = True
    session["FEED_TOKEN"] = PAPER_FEED_TOKEN
    session["USER_ID"] = LOCAL_USER
    session["session_id"] = secrets.token_hex(32)
    session.permanent = True
    set_session_login_time()
    mark_signed_in()
    try:
        from database.auth_db import register_session

        register_session(
            username=LOCAL_USER,
            session_id=session["session_id"],
            device_info=request.headers.get("User-Agent", "")[:500],
            ip_address=request.remote_addr or "127.0.0.1",
            broker=session["broker"],
        )
    except Exception:
        logger.debug("Local mode could not register the browser session", exc_info=True)


def status() -> dict:
    """A small summary for the UI."""
    return {
        "enabled": enabled(),
        "user": LOCAL_USER,
        "broker": local_broker(),
        "ready": _bootstrapped.is_set(),
        "checked_at": datetime.now(UTC).isoformat(),
    }
