"""The paper broker plugin: market data without a broker account, live orders refused.

Covers the bundled master contract (symbol format, expiries, lot sizes), the
simulated feed (quotes, depth, history, option pricing), the fall back from
Yahoo Finance to the simulator, the order refusals and the streaming adapter's
ticks on the ZeroMQ bus.
"""

import json
import socket
import time
from datetime import date, datetime

import pytest

from broker.paper.api import market_data as md
from broker.paper.database import instruments as inst

FIXED_NOW = datetime(2026, 11, 13, 11, 0, tzinfo=inst.IST).timestamp()


@pytest.fixture(autouse=True)
def simulated(monkeypatch):
    monkeypatch.setenv("PAPER_DATA_SOURCE", "simulated")
    monkeypatch.setenv("PAPER_MARKET_HOURS", "always")
    md.reset_state()
    yield
    md.reset_state()


# -- symbols and the master contract -----------------------------------------


def test_option_and_future_symbols_use_the_openalgo_format():
    assert inst.option_symbol("NIFTY", date(2025, 11, 28), 24000, "CE") == "NIFTY28NOV2524000CE"
    assert inst.option_symbol("BANKNIFTY", date(2026, 12, 29), 58500.0, "PE") == "BANKNIFTY29DEC2658500PE"
    assert inst.option_symbol("VEDL", date(2024, 4, 25), 292.5, "CE") == "VEDL25APR24292.5CE"
    assert inst.future_symbol("NIFTY", date(2026, 11, 24)) == "NIFTY24NOV26FUT"
    assert inst.parse_option("NIFTY28NOV2524000CE") == ("NIFTY", date(2025, 11, 28), 24000.0, "CE")
    assert inst.parse_future("BANKNIFTY24NOV26FUT") == ("BANKNIFTY", date(2026, 11, 24))
    assert inst.parse_option("RELIANCE") is None


def test_expiries_are_tuesdays_and_monthlies_are_the_last_tuesday():
    now = datetime(2026, 11, 13, 10, 0, tzinfo=inst.IST)
    weekly = inst.weekly_expiries(4, now)
    monthly = inst.monthly_expiries(3, now)
    assert weekly == [date(2026, 11, 17), date(2026, 11, 24), date(2026, 12, 1), date(2026, 12, 8)]
    assert monthly == [date(2026, 11, 24), date(2026, 12, 29), date(2027, 1, 26)]
    # On expiry day after the close, that expiry is no longer listed.
    after_close = datetime(2026, 11, 24, 16, 0, tzinfo=inst.IST)
    assert inst.monthly_expiries(1, after_close) == [date(2026, 12, 29)]


def test_sector_rotation_symbols_are_in_the_paper_master_contract():
    import services.sector_rotation_service as srs

    rows = inst.build_instruments(spot_of=lambda u: 1000.0, now=datetime(2026, 11, 13, 10, 0, tzinfo=inst.IST))
    have = {(r["symbol"], r["exchange"]) for r in rows}
    wanted = [(i.symbol, i.exchange) for i in (*srs.SECTORS, *srs.OPTIONAL_SECTORS, *srs.BENCHMARKS)]
    missing = [w for w in wanted if w not in have]
    assert not missing, f"not in the paper master contract: {missing}"


def test_master_contract_rows_match_the_symtoken_schema():
    now = datetime(2026, 11, 13, 10, 0, tzinfo=inst.IST)
    rows = inst.build_instruments(spot_of=lambda u: {"NIFTY": 26012.0, "BANKNIFTY": 58460.0}.get(u, 1000.0), now=now)
    columns = {"symbol", "brsymbol", "name", "exchange", "brexchange", "token", "expiry",
               "strike", "lotsize", "instrumenttype", "tick_size", "contract_value"}
    assert all(set(row) == columns for row in rows)
    assert len({row["token"] for row in rows}) == len(rows)
    assert {row["instrumenttype"] for row in rows} == {"EQ", "FUT", "CE", "PE"}

    by_key = {(row["symbol"], row["exchange"]): row for row in rows}
    assert by_key[("RELIANCE", "NSE")]["instrumenttype"] == "EQ"
    assert by_key[("RELIANCE", "BSE")]["expiry"] == ""
    assert by_key[("NIFTY", "NSE_INDEX")]["brsymbol"] == "NIFTY"
    assert by_key[("SENSEX", "BSE_INDEX")]["instrumenttype"] == "EQ"

    nifty_ce = [r for r in rows if r["name"] == "NIFTY" and r["instrumenttype"] == "CE"]
    assert {r["expiry"] for r in nifty_ce} == {
        "17-NOV-26", "24-NOV-26", "01-DEC-26", "08-DEC-26", "29-DEC-26", "26-JAN-27"
    }
    strikes = sorted({r["strike"] for r in nifty_ce})
    assert strikes[len(strikes) // 2] == 26000.0  # centred on the spot given
    assert all(r["lotsize"] == 65 and r["tick_size"] == 0.05 for r in nifty_ce)
    atm = by_key[("NIFTY17NOV2626000CE", "NFO")]
    assert atm["expiry"] == "17-NOV-26" and atm["strike"] == 26000.0

    bank = [r for r in rows if r["name"] == "BANKNIFTY" and r["instrumenttype"] == "PE"]
    assert {r["expiry"] for r in bank} == {"24-NOV-26", "29-DEC-26", "26-JAN-27"}
    assert all(r["lotsize"] == 30 for r in bank)
    assert ("BANKNIFTY24NOV26FUT", "NFO") in by_key


def test_master_contract_download_fills_the_symtoken_table(monkeypatch):
    from broker.paper.database import master_contract_db as mc

    emitted = []
    monkeypatch.setattr(mc.socketio, "emit", lambda *args, **kwargs: emitted.append(args))
    mc.master_contract_download()
    assert emitted[-1][1]["status"] == "success"
    try:
        assert mc.SymToken.query.filter_by(symbol="RELIANCE", exchange="NSE").count() == 1
        assert mc.SymToken.query.filter_by(exchange="NFO", instrumenttype="CE").count() > 500
        assert len(mc.search_symbols("BANKNIFTY", "NSE_INDEX")) == 1
    finally:
        mc.db_session.remove()


# -- quotes, depth and history -------------------------------------------------


def _handler():
    from broker.paper.api.data import BrokerData

    return BrokerData("paper-session")


def test_quote_has_the_common_fields_and_is_coherent():
    quote = _handler().get_quotes("RELIANCE", "NSE")
    assert set(quote) == {"ask", "bid", "ask_qty", "bid_qty", "high", "low", "ltp", "open",
                          "prev_close", "volume", "oi"}
    assert quote["low"] <= quote["ltp"] <= quote["high"]
    assert 0 < quote["bid"] < quote["ask"]
    assert 1000 < quote["ltp"] < 2000  # near the 1500 reference
    assert round(quote["ltp"] / 0.05, 6).is_integer()


def test_simulated_prices_are_deterministic_and_move_with_the_clock():
    first = md.snapshot("SBIN", "NSE", now=FIXED_NOW)
    again = md.snapshot("SBIN", "NSE", now=FIXED_NOW)
    later = md.snapshot("SBIN", "NSE", now=FIXED_NOW + 120)
    assert first["ltp"] == again["ltp"]
    assert first["ltp"] != later["ltp"]
    assert first["source"] == md.SOURCE_SIMULATED


def test_index_quote_has_no_book():
    quote = _handler().get_quotes("NIFTY", "NSE_INDEX")
    assert quote["bid"] == quote["ask"] == 0
    assert 20000 < quote["ltp"] < 32000


def test_option_quotes_follow_the_underlying_and_put_call_parity():
    spot, source = md.underlying_spot("NIFTY", now=FIXED_NOW)
    assert source == md.SOURCE_SIMULATED
    expiry = inst.weekly_expiries(1, datetime.fromtimestamp(FIXED_NOW, inst.IST))[0]
    strike = inst.atm_strike(spot, 50)
    call = md.snapshot(inst.option_symbol("NIFTY", expiry, strike, "CE"), "NFO", now=FIXED_NOW)
    put = md.snapshot(inst.option_symbol("NIFTY", expiry, strike, "PE"), "NFO", now=FIXED_NOW)
    years = (inst.expiry_datetime(expiry).timestamp() - FIXED_NOW) / md.YEAR_SECONDS
    forward_gap = spot - strike * pow(2.718281828459045, -md.RISK_FREE_RATE * years)
    assert call["ltp"] - put["ltp"] == pytest.approx(forward_gap, abs=0.2)
    assert call["ltp"] > 0.05 and put["ltp"] > 0.05
    assert call["oi"] > 0 and call["lotsize"] == 65

    deep_itm = md.snapshot(inst.option_symbol("NIFTY", expiry, strike - 1000, "CE"), "NFO", now=FIXED_NOW)
    assert deep_itm["ltp"] >= spot - (strike - 1000) - 1
    future = md.snapshot(inst.future_symbol("NIFTY", inst.monthly_expiries(1)[0]), "NFO", now=FIXED_NOW)
    assert future["ltp"] > spot


def test_multiquotes_returns_one_entry_per_symbol():
    results = _handler().get_multiquotes(
        [{"symbol": "RELIANCE", "exchange": "NSE"}, {"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    )
    assert [(r["symbol"], r["exchange"]) for r in results] == [("RELIANCE", "NSE"), ("NIFTY", "NSE_INDEX")]
    assert all("ltp" in r["data"] for r in results)


def test_depth_has_five_ordered_levels_each_side():
    depth = _handler().get_depth("INFY", "NSE")
    bids = [level["price"] for level in depth["bids"]]
    asks = [level["price"] for level in depth["asks"]]
    assert len(bids) == len(asks) == 5
    assert bids == sorted(bids, reverse=True) and asks == sorted(asks)
    assert bids[0] < asks[0]
    assert depth["totalbuyqty"] == sum(level["quantity"] for level in depth["bids"])


def test_intraday_history_is_ordered_ohlc():
    df = _handler().get_history("RELIANCE", "NSE", "5m", "2026-11-10", "2026-11-12")
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "oi"]
    assert len(df) == 3 * 75  # three past weekdays of 5 minute candles, 09:15-15:30 IST
    assert df["timestamp"].is_monotonic_increasing
    assert set(df["timestamp"].diff().dropna()) <= {300, 64200}  # overnight gaps between sessions
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()


def test_exchange_hours_history_follows_the_session(monkeypatch):
    monkeypatch.setenv("PAPER_MARKET_HOURS", "exchange")
    df = _handler().get_history("RELIANCE", "NSE", "15m", "2026-11-13", "2026-11-16")
    stamps = [datetime.fromtimestamp(t, inst.IST) for t in df["timestamp"]]
    assert {s.date() for s in stamps} <= {date(2026, 11, 13), date(2026, 11, 16)}  # no weekend
    assert min(s.time() for s in stamps).strftime("%H:%M") == "09:15"
    assert max(s.time() for s in stamps).strftime("%H:%M") <= "15:15"


def test_daily_history_is_stamped_at_utc_midnight_and_skips_nothing_it_should_not():
    df = _handler().get_history("NIFTY", "NSE_INDEX", "D", "2026-11-02", "2026-11-06")
    assert len(df) == 5
    assert all(int(t) % 86400 == 0 for t in df["timestamp"])
    assert datetime.utcfromtimestamp(int(df["timestamp"].iloc[0])).date() == date(2026, 11, 2)


def test_option_history_is_priced_off_the_underlying():
    expiry = inst.monthly_expiries(1)[0]
    symbol = inst.option_symbol("NIFTY", expiry, 26000, "CE")
    df = _handler().get_history(symbol, "NFO", "15m", "2026-11-12", "2026-11-12")
    assert len(df) == 25  # one past session of 15 minute candles
    assert (df["close"] >= 0.05).all() and (df["oi"] > 0).all()


def test_unsupported_interval_is_refused_in_words():
    from broker.paper.api.data import PaperDataError

    with pytest.raises(PaperDataError, match="not available"):
        _handler().get_history("RELIANCE", "NSE", "7m", "2026-11-12", "2026-11-12")
    assert "1m" in _handler().timeframe_map and "D" in _handler().timeframe_map


# -- Yahoo Finance and the fall back -----------------------------------------


class _Reply:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_unreachable_yahoo_falls_back_to_the_simulator(monkeypatch):
    import utils.httpx_client as httpx_client

    calls = []

    class Blocked:
        def get(self, url, **kwargs):
            calls.append(url)
            raise ConnectionError("proxy refused")

    monkeypatch.setenv("PAPER_DATA_SOURCE", "auto")
    monkeypatch.setattr(httpx_client, "get_httpx_client", lambda: Blocked())
    first = md.snapshot("TCS", "NSE")
    second = md.snapshot("INFY", "NSE")
    assert first["source"] == second["source"] == md.SOURCE_SIMULATED
    assert len(calls) == 1  # Yahoo is not asked again while it is down
    status = md.data_source_status()
    assert status["source"] == "simulated" and status["retry_at"] is not None
    assert "cannot be reached" in status["message"]


def test_reachable_yahoo_is_used_for_spot_and_options(monkeypatch):
    import utils.httpx_client as httpx_client

    chart = {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketPrice": 26100.0, "chartPreviousClose": 26000.0,
                             "regularMarketDayHigh": 26150.0, "regularMarketDayLow": 25980.0},
                    "timestamp": [1, 2],
                    "indicators": {"quote": [{"open": [26010.0, 26050.0], "high": [26150.0, 26120.0],
                                              "low": [25980.0, 26040.0], "close": [26050.0, 26100.0],
                                              "volume": [0, 0]}]},
                }
            ]
        }
    }
    seen = []

    class Yahoo:
        def get(self, url, **kwargs):
            seen.append(url)
            return _Reply(200, chart)

    monkeypatch.setenv("PAPER_DATA_SOURCE", "auto")
    monkeypatch.setattr(httpx_client, "get_httpx_client", lambda: Yahoo())
    quote = md.snapshot("NIFTY", "NSE_INDEX")
    assert quote["source"] == md.SOURCE_LIVE
    assert (quote["ltp"], quote["open"], quote["prev_close"]) == (26100.0, 26010.0, 26000.0)
    assert seen[0].endswith("/%5ENSEI") or seen[0].endswith("/^NSEI")
    option = md.snapshot(inst.option_symbol("NIFTY", inst.monthly_expiries(1)[0], 26100, "CE"), "NFO")
    assert option["source"] == md.SOURCE_LIVE
    assert md.data_source_status()["source"] == "live"


def test_yahoo_tickers():
    assert md.yahoo_ticker("RELIANCE", "NSE") == "RELIANCE.NS"
    assert md.yahoo_ticker("RELIANCE", "BSE") == "RELIANCE.BO"
    assert md.yahoo_ticker("NIFTY", "NSE_INDEX") == "^NSEI"
    assert md.yahoo_ticker("BANKNIFTY", "NSE_INDEX") == "^NSEBANK"
    assert md.yahoo_ticker("SENSEX", "BSE_INDEX") == "^BSESN"
    assert md.yahoo_ticker("NIFTY24NOV26FUT", "NFO") is None


# -- orders, funds, margin -------------------------------------------------------


def test_live_orders_are_refused_with_a_sentence():
    from broker.paper.api import order_api

    response, data, orderid = order_api.place_order_api({"symbol": "SBIN"}, "paper-session")
    assert response.status == 400 and orderid is None
    assert data["status"] == "error" and "Sandbox mode" in data["message"]
    response, data, orderid = order_api.place_smartorder_api({"symbol": "SBIN"}, "paper-session")
    assert response.status == 400 and "Sandbox mode" in data["message"]
    for result in (
        order_api.cancel_order("1", "paper-session"),
        order_api.modify_order({"orderid": "1"}, "paper-session"),
        order_api.close_all_positions("key", "paper-session"),
    ):
        assert result[1] == 400 and "Sandbox mode" in result[0]["message"]
    assert order_api.cancel_all_orders_api({}, "paper-session") == ([], [])
    assert order_api.get_open_position("SBIN", "NSE", "MIS", "paper-session") == "0"


def test_live_books_are_empty_through_the_services(monkeypatch):
    import database.settings_db as settings_db

    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    from services.orderbook_service import get_orderbook_with_auth
    from services.positionbook_service import get_positionbook_with_auth

    ok, response, status = get_orderbook_with_auth("paper-session", "paper", None)
    assert ok and status == 200 and response["data"]["orders"] == []
    assert response["data"]["statistics"]["total_buy_orders"] == 0
    ok, response, status = get_positionbook_with_auth("paper-session", "paper", None)
    assert ok and response["data"] == []


def test_funds_report_the_sandbox_capital():
    from broker.paper.api import funds

    assert funds.get_margin_data("paper-session")["availablecash"] == "10000000.00"
    assert funds.get_margin_data("") == {}


def test_margin_is_estimated_locally():
    from broker.paper.api import margin_api

    response, data = margin_api.calculate_margin_api(
        [{"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": "10",
          "product": "CNC", "pricetype": "LIMIT", "price": "900"}],
        "paper-session",
    )
    assert response.status == 200
    assert data["data"]["total_margin_required"] == 9000.0


def test_authenticate_broker_needs_no_keys():
    from broker.paper.api.auth_api import authenticate_broker

    assert authenticate_broker("paper") == ("paper-session", None)


def test_paper_resolves_with_no_keys():
    from utils.broker_keys import resolve

    keys = resolve("paper")
    assert keys is not None and keys.source == "none" and keys.api_key == ""


# -- streaming ---------------------------------------------------------------------


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_streaming_adapter_publishes_ticks_to_the_bus(monkeypatch):
    import zmq

    import websocket_proxy  # noqa: F401  (the proxy package imports and registers the adapters)
    from broker.paper.streaming.paper_adapter import PaperWebSocketAdapter
    from websocket_proxy.broker_factory import BROKER_ADAPTERS

    assert BROKER_ADAPTERS["paper"] is PaperWebSocketAdapter

    port = _free_port()
    monkeypatch.setenv("ZMQ_HOST", "127.0.0.1")
    monkeypatch.setenv("ZMQ_PORT", str(port))
    context = zmq.Context.instance()
    sub = context.socket(zmq.SUB)
    sub.bind(f"tcp://127.0.0.1:{port}")  # the proxy's SUB binds; the adapter connects
    sub.setsockopt(zmq.SUBSCRIBE, b"")
    adapter = PaperWebSocketAdapter()
    try:
        assert adapter.initialize("paper", "trader")["status"] == "success"
        assert adapter.connect()["status"] == "success"
        time.sleep(0.3)  # let the PUB connection settle before the first tick
        assert adapter.subscribe("RELIANCE", "NSE", mode=1)["status"] == "success"
        assert adapter.subscribe("NIFTY", "NSE_INDEX", mode=3)["status"] == "success"
        topics = {}
        deadline = time.time() + 5
        while time.time() < deadline and len(topics) < 2:
            if sub.poll(500):
                topic, payload = sub.recv_multipart()
                topics[topic.decode()] = json.loads(payload)
        assert set(topics) == {"NSE_RELIANCE_LTP", "NSE_INDEX_NIFTY_DEPTH"}
        assert topics["NSE_RELIANCE_LTP"]["ltp"] > 0
        assert topics["NSE_RELIANCE_LTP"]["mode"] == "ltp"
        assert len(topics["NSE_INDEX_NIFTY_DEPTH"]["depth"]["buy"]) == 5
        assert adapter.unsubscribe("RELIANCE", "NSE", mode=1)["status"] == "success"
    finally:
        adapter.disconnect()
        sub.close(linger=0)
