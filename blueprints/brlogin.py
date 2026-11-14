
from flask import Blueprint, g, jsonify, redirect, request, session, url_for
from flask import current_app as app

from limiter import limiter  # Import the limiter instance
from utils.auth_utils import (
    begin_broker_login,
    end_broker_login,
    handle_auth_failure,
    handle_auth_success,
    is_ajax_request,
    login_error_address,
)
from utils.broker_keys import BrokerKeysRefused
from utils.broker_login import (
    BrokerLoginRefused,
    has_pending_login,
    is_broker_site_post,
    verify_broker_return,
)
from utils.config import (
    get_login_rate_limit_hour,
    get_login_rate_limit_min,
)
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

LOGIN_RATE_LIMIT_MIN = get_login_rate_limit_min()
LOGIN_RATE_LIMIT_HOUR = get_login_rate_limit_hour()

brlogin_bp = Blueprint("brlogin", __name__, url_prefix="/")


@brlogin_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429


#: Codes the broker login page turns into a message (frontend BrokerSelect).
#: A code rather than the text, so nobody can put words of their own on the page.
LOGIN_NOT_STARTED = "login_not_started"
FORM_EXPIRED = "form_expired"


def _refuse_login(code, message, status=403):
    """Answer a refused broker login: JSON for our pages, the login page otherwise."""
    from_our_form = request.method == "POST" and not is_broker_site_post(
        request.view_args.get("broker") if request.view_args else None, request.method
    )
    if is_ajax_request() or from_our_form:
        return jsonify({"status": "error", "code": code, "message": message}), status
    return redirect(login_error_address(code))


def _form_csrf_ok():
    """Whether a POST from OpenAlgo's broker login form carries a valid CSRF token.

    The callback is exempt from the app-wide CSRF check because two brokers post
    their answer to it from their own site, so the form posts are checked here.
    """
    if not app.config.get("WTF_CSRF_ENABLED", True):
        return True
    from flask_wtf.csrf import validate_csrf
    from wtforms.validators import ValidationError

    token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    try:
        validate_csrf(token)
        return True
    except ValidationError:
        return False


@brlogin_bp.route("/<broker>/callback", methods=["POST", "GET"])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_callback(broker, para=None):
    """Complete a broker login, refusing one this browser did not start.

    The endpoint name is what app.py exempts from the app-wide CSRF check, so
    the work lives in _broker_callback and this wrapper turns a refusal into an
    answer the trader can act on.
    """
    had_user = "user" in session
    try:
        return _broker_callback(broker, para)
    except BrokerKeysRefused as exc:
        logger.info(f"Broker login for {broker} refused: {exc}")
        return _refuse_login("broker_unavailable", str(exc), status=409)
    except BrokerLoginRefused:
        logger.warning(f"Refused a {broker} login answer that no login started from this browser")
        return _refuse_login(
            LOGIN_NOT_STARTED,
            "This broker login was not started from OpenAlgo, or it took longer than "
            "10 minutes. Start the broker login again.",
        )
    finally:
        # A browser that arrived without a sign-in (the XTS post-back, which
        # carries no cookie) is given one only by a login that completed: a
        # refused, failed or unfinished one leaves it signed out.
        if not _end_login_request() and not had_user:
            session.pop("user", None)


def _begin_login_request(broker):
    """This broker's keys, staged for this request under the broker slot."""
    return begin_broker_login(broker)


def _end_login_request():
    """Drop the staged keys and give the slot back, however the request ended.

    Returns:
        bool: Whether the login completed.
    """
    return end_broker_login()


def _claim_login(broker):
    """Use up the pending login this answer completes, once per request.

    Every completion goes through here, the broker's answer and OpenAlgo's own
    login form alike: the login must have been started from Select Broker,
    within ten minutes, and is used once. When it started is kept, so a
    sign-out since then stops it from being stored.
    """
    if g.get("broker_login_started_at") is None:
        g.broker_login_started_at = verify_broker_return(broker, state=request.args.get("state"))


def _complete_login(auth_token, username, broker, feed_token=None, user_id=None):
    """Store a broker login, once it is matched to the login it completes."""
    _claim_login(broker)
    return handle_auth_success(auth_token, username, broker, feed_token=feed_token, user_id=user_id)


def _broker_callback(broker, para=None):
    logger.info(f"Broker callback initiated for: {broker}")
    logger.debug("Session keys: %s", sorted(session.keys()))
    logger.info(f"Session has user key: {'user' in session}")

    if "user" not in session:
        logger.warning(f"User not in session for {broker} callback, redirecting to login")
        return redirect(url_for("auth.login"))

    if session.get("logged_in") and session.get("broker") == broker:
        # Already logged in to this broker: nothing to do here. A login to
        # another broker goes on: it is the switch the trader confirmed on
        # Select Broker, and it needs a login started there like any other.
        return redirect(url_for("dashboard_bp.dashboard"))

    # A POST from OpenAlgo's own login form (PIN, password, TOTP) must carry
    # the page's CSRF token. The broker-site posts are checked below, by the
    # state they bring back.
    if request.method == "POST" and not is_broker_site_post(broker, request.method):
        if not _form_csrf_ok():
            return _refuse_login(
                FORM_EXPIRED, "This login form has expired. Reload the page and try again.", 400
            )

    # Everything arriving here (a broker's answer, our own login form, or a
    # sign-in that starts at the callback) must belong to a login started from
    # Select Broker, checked before any code is exchanged or OTP requested. It
    # is used up only when the login completes (_claim_login).
    if not has_pending_login(broker, state=request.args.get("state")):
        raise BrokerLoginRefused(broker)

    # This broker's keys (.env first, then the keys saved in OpenAlgo), for
    # this request only, under the slot that keeps another broker's login
    # from committing in the middle of this one.
    keys = _begin_login_request(broker)

    broker_auth_functions = app.broker_auth_functions
    auth_function = broker_auth_functions.get(f"{broker}_auth")

    if not auth_function:
        return jsonify(error="Broker authentication function not found."), 404

    # Initialize optional outputs used by different broker auth flows
    feed_token = None

    if broker == "paper":
        # No broker account: the session token is fixed and the login never fails.
        from broker.paper.api.auth_api import PAPER_FEED_TOKEN

        auth_token, error_message = auth_function("paper")
        feed_token = PAPER_FEED_TOKEN
        forward_url = "broker.html"

    else:
        code = request.args.get("code") or request.args.get("request_token")
        logger.debug("Generic broker - callback code present: %s", bool(code))
        auth_token, error_message = auth_function(code)
        forward_url = "broker.html"

    if auth_token:
        # A broker's answer (a GET, or a post from the broker's own site)
        # completes a login only when this browser started it from OpenAlgo.
        # Before session["user"] is set for the brokers that answer without it.
        _claim_login(broker)
        # Store broker in session
        session["broker"] = broker
        logger.info(f"Successfully connected broker: {broker}")
        if broker == "zerodha":
            auth_token = f"{keys.api_key}:{auth_token}"

        # Pass just the feed token to handle_auth_success
        return _complete_login(auth_token, session["user"], broker, feed_token=feed_token)
    else:
        return handle_auth_failure(error_message, forward_url=forward_url)
