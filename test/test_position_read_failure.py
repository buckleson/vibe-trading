"""A smart order must place nothing when the broker's position read fails.

Every broker plugin's place_smartorder_api reads the open position, compares it
with the target and places the difference. Most of them used to read a failed
position read (a network error, an HTTP error, an error envelope in the body,
a body that would not parse) as a net quantity of 0, which is what an empty
book reads as, so the order was sized against a flat position the account did
not have: an entry or a flip placed the full quantity on top of the real
position, doubling or reversing it.

These tests drive each plugin's real smart-order code against a mocked HTTP
layer (the shared httpx client is swapped for one on an httpx.MockTransport),
with no broker account and no network. Only place_order_api is replaced, by a
recorder, so the tests see exactly which order would have been sent. For every
broker:

- each failure kind sends nothing and returns the trader-facing sentence,
- an empty position book is still flat, exactly as before,
- a real position produces the same order as before.
"""

import importlib
import os
import time
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

import utils.httpx_client as httpx_client
from utils.broker_backpressure import BrokerBusyError
from utils.lazy import LazyInit
from utils.position_read import (
    EMPTY_BOOK_MESSAGE_FIELDS,
    PositionReadError,
    position_read_failed_message,
    read_position_book,
    refuse_smart_order_on_read_failure,
    says_no_positions,
)
from utils.smart_order_guard import PositionBookCache
from utils.thread_safe_cache import LockedTTLCache

# Plugins with no broker account behind them: they read no position book and
# refuse every live order before reading one (broker/paper/api/order_api.py,
# covered by test/test_paper_broker.py).
NO_LIVE_ORDER_BROKERS = {"paper"}

BROKERS = sorted(
    name
    for name in os.listdir("broker")
    if os.path.exists(os.path.join("broker", name, "api", "order_api.py"))
    and name not in NO_LIVE_ORDER_BROKERS
)

FAILURES = ("exception", "http_error", "error_status", "unparseable")

TOKEN = "3045"
HELD = 10  # the position the account really holds
TARGET = -5  # the smart order's position_size: flip from long 10 to short 5


@dataclass
class Spec:
    """How one broker answers its position book, and what its session needs."""

    path: str  # a substring of the position-book URL
    book: Any  # book(qty) -> response body; qty None means an empty book
    error: Any  # the broker's own error envelope, sent with HTTP 200
    br_symbol: str = "SBIN"
    symbol: str = "SBIN"
    exchange: str = "NSE"
    auth: str = "access-token"
    # Pre-existing and not changed here: the plugin reads every position as
    # flat, even when the read works. test_held_position_is_read documents it.
    reads_flat: bool = False
    patches: dict = field(default_factory=dict)  # module attribute -> replacement
    fail_path: str | None = None  # narrower failure target than `path`


SPECS = {
    "zerodha": Spec(
        path="/portfolio/positions",
        book=lambda q: {
            "status": "success",
            "data": {
                "net": []
                if q is None
                else [
                    {"tradingsymbol": "SBIN", "exchange": "NSE", "product": "MIS", "quantity": q}
                ],
                "day": [],
            },
        },
        error={
            "status": "error",
            "message": "Incorrect `api_key` or `access_token`.",
            "error_type": "TokenException",
        },
    ),
}

def test_every_broker_plugin_is_covered():
    assert set(SPECS) == set(BROKERS)


class _NoSleep:
    """The time module, minus sleep: retries in the plugins must not slow the suite."""

    def __getattr__(self, name):
        return getattr(time, name)

    @staticmethod
    def sleep(_seconds):
        return None


@dataclass
class Harness:
    broker: str
    spec: Spec
    module: Any
    monkeypatch: Any = None
    requests: list = field(default_factory=list)
    orders: list = field(default_factory=list)

    def serve(self, respond):
        """Answer every request with respond(url) instead of the scenario's book."""

        def handler(request):
            url = str(request.url)
            self.requests.append((request.method, url))
            return respond(url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        _use_client(self.monkeypatch, client)

    def smart_order(self, position_size=TARGET, quantity=abs(TARGET)):
        data = {
            "strategy": "test",
            "symbol": self.spec.symbol,
            "exchange": self.spec.exchange,
            "product": "MIS",
            "action": "SELL",
            "quantity": str(quantity),
            "position_size": str(position_size),
            "pricetype": "MARKET",
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0",
        }
        return self.module.place_smartorder_api(data, self.spec.auth)

    def position_reads(self):
        return [url for method, url in self.requests if self.spec.path in url]

    def other_requests(self):
        return [(method, url) for method, url in self.requests if self.spec.path not in url]


def _use_client(monkeypatch, client):
    """Make every plugin's shared httpx client this one for the test.

    The shared client is built once through a LazyInit, so a fresh LazyInit
    that hands out the mock is swapped in; plugins call get_httpx_client()
    on every request, which reads it by name.
    """
    monkeypatch.setattr(httpx_client, "_client", LazyInit(lambda: client, name="mock-httpx"))


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "USER01:::CLIENT01:::CODE01")
    monkeypatch.setenv("BROKER_API_SECRET", "SECRET01")

    def build(broker, scenario, held=HELD):
        spec = SPECS[broker]
        module = importlib.import_module(f"broker.{broker}.api.order_api")

        # Symbol master lookups, everywhere a plugin might reach them.
        import database.token_db as token_db

        lookups = {
            "get_br_symbol": lambda symbol, exchange: spec.br_symbol,
            "get_token": lambda symbol, exchange: TOKEN,
            "get_oa_symbol": lambda *args, **kwargs: spec.symbol,
            "get_symbol": lambda *args, **kwargs: spec.symbol,
        }
        for name, fake in lookups.items():
            monkeypatch.setattr(token_db, name, fake)
            if hasattr(module, name):
                monkeypatch.setattr(module, name, fake)
        for name, fake in spec.patches.items():
            monkeypatch.setattr(module, name, fake)
        if getattr(module, "time", None) is time:
            monkeypatch.setattr(module, "time", _NoSleep())

        # Nothing may carry over from another test: no cached book. A plugin
        # keeps it in a plain dict, a PositionBookCache or a LockedTTLCache,
        # under one of two names; each gets a fresh, empty one of its kind.
        for name in ("_position_cache", "_POSITION_BOOK"):
            cache = getattr(module, name, None)
            if isinstance(cache, dict):
                monkeypatch.setattr(module, name, {})
            elif isinstance(cache, PositionBookCache):
                monkeypatch.setattr(module, name, PositionBookCache())
            elif isinstance(cache, LockedTTLCache):
                monkeypatch.setattr(
                    module, name, LockedTTLCache(maxsize=cache.maxsize, ttl=cache.ttl)
                )

        h = Harness(broker=broker, spec=spec, module=module, monkeypatch=monkeypatch)

        def place_order_api(order_data, auth):
            h.orders.append((order_data["action"], int(float(order_data["quantity"]))))
            response = SimpleNamespace(status=200, status_code=200)
            return response, {"status": "success", "orderid": "OID1"}, "OID1"

        monkeypatch.setattr(module, "place_order_api", place_order_api)

        def body_for(request, qty):
            return spec.book(qty)

        def handler(request):
            url = str(request.url)
            h.requests.append((request.method, url))
            if spec.path not in url:
                return httpx.Response(404, json={"message": "not mocked"})
            fails_here = spec.fail_path is None or spec.fail_path in url
            if scenario in FAILURES and fails_here:
                if scenario == "exception":
                    raise httpx.ConnectError("connection refused", request=request)
                if scenario == "http_error":
                    return httpx.Response(500, json={"message": "Internal Server Error"})
                if scenario == "error_status":
                    return httpx.Response(200, json=spec.error)
                return httpx.Response(
                    200,
                    text="<html><body>502 Bad Gateway</body></html>",
                    headers={"content-type": "text/html"},
                )
            qty = held if scenario == "held" else None
            return httpx.Response(200, json=body_for(request, qty))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        _use_client(monkeypatch, client)
        return h

    return build


# ---------------------------------------------------------------------------
# The three behaviours, for every broker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("broker", BROKERS)
def test_failed_read_sends_no_order(harness, broker, failure):
    h = harness(broker, failure)

    res, data, orderid = h.smart_order()

    assert h.orders == [], "no order may be sized against a position that was never read"
    assert orderid is None
    assert res is None
    assert data == {"status": "error", "message": position_read_failed_message(broker)}
    assert h.position_reads(), "the plugin never asked for the position book"
    assert h.other_requests() == [], "nothing but the position read may reach the broker"


@pytest.mark.parametrize("broker", BROKERS)
def test_failed_read_refuses_an_exit_too(harness, broker):
    """A close with the read down used to report "no open position" and walk away."""
    h = harness(broker, "error_status")

    res, data, orderid = h.smart_order(position_size=0, quantity=0)

    assert h.orders == []
    assert data["status"] == "error"
    assert data["message"] == position_read_failed_message(broker)


@pytest.mark.parametrize("broker", BROKERS)
def test_empty_book_is_still_flat(harness, broker):
    h = harness(broker, "empty")

    h.smart_order()

    assert h.orders == [("SELL", abs(TARGET))]


@pytest.mark.parametrize("broker", BROKERS)
def test_held_position_gives_the_same_order_as_before(harness, broker):
    h = harness(broker, "held")

    h.smart_order()

    if SPECS[broker].reads_flat:
        # Unchanged by this fix: see test_held_position_is_read.
        expected = ("SELL", abs(TARGET))
    else:
        expected = ("SELL", HELD - TARGET)
    assert h.orders == [expected]


@pytest.mark.parametrize("broker", [b for b in BROKERS if SPECS[b].reads_flat])
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Pre-existing, not changed by this fix: the plugin reads every position as "
        "flat even when the read works (XTS brokers match on keys the XTS book does "
        "not carry)."
    ),
)
def test_held_position_is_read(harness, broker):
    h = harness(broker, "held")

    h.smart_order()

    assert h.orders == [("SELL", HELD - TARGET)]


@pytest.mark.parametrize("broker", BROKERS)
def test_a_failed_read_is_not_cached(harness, broker):
    """The next smart order must read again, not replay the failure or a stale book."""
    h = harness(broker, "error_status")
    h.smart_order()
    reads_after_failure = len(h.position_reads())

    h.smart_order()

    assert len(h.position_reads()) > reads_after_failure


# ---------------------------------------------------------------------------
# Specific plugins
# ---------------------------------------------------------------------------


def test_error_envelope_saying_no_data_refuses_where_the_empty_book_is_a_success(harness):
    """Zerodha answers an empty book with a success envelope, which its own check
    already accepts, so an error envelope is a failed read whatever it says."""
    assert "zerodha" not in EMPTY_BOOK_MESSAGE_FIELDS
    h = harness("zerodha", "held")
    h.serve(
        lambda url: httpx.Response(
            200, json={"status": "error", "message": "No data available", "error_type": "General"}
        )
    )

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("zerodha")


def test_service_layer_reports_the_sentence(harness, monkeypatch):
    """The refusal reaches the API caller as a failed order carrying the sentence."""
    import services.place_smart_order_service as service

    harness("zerodha", "exception")
    published = []
    monkeypatch.setattr(service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(service.bus, "publish", published.append)

    ok, body, status = service.place_smart_order_with_auth(
        {
            "apikey": "k",
            "strategy": "test",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "SELL",
            "product": "MIS",
            "pricetype": "MARKET",
            "quantity": "5",
            "position_size": "-5",
        },
        "token",
        "zerodha",
        {"apikey": "k"},
    )

    assert ok is False
    assert body == {"status": "error", "message": position_read_failed_message("zerodha")}
    assert status == 500
    assert [type(event).__name__ for event in published] == ["OrderFailedEvent"]


# ---------------------------------------------------------------------------
# The shared helper
# ---------------------------------------------------------------------------


def test_message_names_the_broker_and_the_next_step():
    message = position_read_failed_message("zerodha")
    assert message == (
        "OpenAlgo could not read your open position from Zerodha, so no order "
        "was sent. Check your positions and try again."
    )


def test_unknown_broker_falls_back_to_its_plugin_name():
    assert "from newbroker," in position_read_failed_message("newbroker")


@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Not_Ok", "emsg": "no data"},
        {"status": "Failure", "statusMessage": "No Positions Found"},
        {"status": "error", "message": "You do not have any positions"},
        {"s": "no-data"},
    ],
)
def test_empty_book_answers_are_recognised(response):
    assert says_no_positions(response)


@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Not_Ok", "emsg": "Session Expired :  Invalid Session Key"},
        {"status": "error", "message": "HTTP error: Server error '500 Internal Server Error'"},
        {"type": "error", "description": "Invalid Token"},
        None,
        "<html>" + "no data " * 500 + "</html>",
    ],
)
def test_failures_are_not_mistaken_for_an_empty_book(response):
    assert not says_no_positions(response)


def test_read_position_book_returns_a_good_read_unchanged():
    book = {"status": "success", "data": [1]}
    assert read_position_book("zerodha", lambda: book, lambda d: True) is book


def test_read_position_book_raises_on_an_exception():
    def fetch():
        raise ValueError("boom")

    with pytest.raises(PositionReadError) as exc:
        read_position_book("zerodha", fetch, lambda d: True)
    assert str(exc.value) == position_read_failed_message("zerodha")
    assert "ValueError: boom" in exc.value.detail


def test_read_position_book_lets_a_pacer_refusal_through():
    """A read the broker pacer refused (gthread only) keeps its busy answer.

    Folded into PositionReadError it would lose the sentence about pacing and
    the 429 that the plugin or the smart order service answers with.
    """
    refusal = BrokerBusyError("OpenAlgo is pacing requests. Try again in a few seconds.")

    def fetch():
        raise refusal

    with pytest.raises(BrokerBusyError) as exc:
        read_position_book("zerodha", fetch, lambda d: True)
    assert exc.value is refusal


def test_says_no_positions_reads_only_the_message_fields():
    # The phrase outside a message field: a failure, not an empty book.
    assert not says_no_positions({"status": "error", "message": "Busy", "detail": "no data"})
    assert not says_no_positions({"stat": "Not_Ok", "emsg": "Invalid session"}, ("message",))
    # Only the named fields count.
    assert says_no_positions({"stat": "Not_Ok", "emsg": "no data"}, ("emsg",))
    assert not says_no_positions({"stat": "Not_Ok", "emsg": "no data"}, ("message",))
    # A nested message.
    assert says_no_positions(
        {"status": "failed", "error": {"message": "No Data"}}, ("error.message",)
    )
    # A long message is not a one-line "no data" answer.
    assert not says_no_positions({"emsg": "no data " * 500}, ("emsg",))


def test_read_position_book_uses_the_empty_book_check_only_where_registered(monkeypatch):
    envelope = {"stat": "Not_Ok", "emsg": "no data"}
    monkeypatch.setitem(EMPTY_BOOK_MESSAGE_FIELDS, "registered", ("emsg",))
    assert read_position_book("registered", lambda: envelope, lambda d: False) is envelope
    with pytest.raises(PositionReadError):
        read_position_book("zerodha", lambda: envelope, lambda d: False)


def test_read_position_book_takes_an_explicit_empty_book_check():
    envelope = {"status": "error", "message": "nothing here"}
    assert (
        read_position_book("zerodha", lambda: envelope, lambda d: False, is_empty=lambda d: True)
        is envelope
    )

    def broken(data):
        raise KeyError("x")

    with pytest.raises(PositionReadError):
        read_position_book("shoonya", lambda: envelope, lambda d: False, is_empty=broken)


def test_read_position_book_raises_when_the_check_fails_or_raises():
    with pytest.raises(PositionReadError):
        read_position_book("zerodha", lambda: {"status": "error"}, lambda d: False)

    def broken_check(data):
        raise KeyError("x")

    with pytest.raises(PositionReadError):
        read_position_book("zerodha", lambda: {"status": "error"}, broken_check)


def test_refusal_decorator_keeps_the_three_part_shape():
    @refuse_smart_order_on_read_failure
    def smart(data, auth):
        raise PositionReadError("angel", "detail")

    assert smart({}, "t") == (
        None,
        {"status": "error", "message": position_read_failed_message("angel")},
        None,
    )


def test_refusal_decorator_leaves_other_errors_alone():
    @refuse_smart_order_on_read_failure
    def smart(data, auth):
        raise RuntimeError("not ours")

    with pytest.raises(RuntimeError):
        smart({}, "t")
