"""T10: the backtesting surfaces run on the paper broker's history.

In process, no server and no network: the history service is replaced by the
paper broker's own BrokerData (simulated feed), and Historify by an in-memory
DuckDB table, so the portfolio, SIP and sector rotation services are run
exactly as the REST endpoints run them.

Weekend checks depend on T07 (past-day history follows exchange sessions).
"""

from __future__ import annotations

import contextlib
import math
from datetime import date

import pandas as pd
import pytest

from broker.paper.api import market_data as md
from broker.paper.api.data import BrokerData

START, END = "2023-01-01", "2024-12-31"


@pytest.fixture(autouse=True)
def paper_history(monkeypatch):
    """Route every history request to the paper broker, and count them."""
    monkeypatch.setenv("PAPER_DATA_SOURCE", "simulated")
    monkeypatch.setenv("PAPER_MARKET_HOURS", "always")
    md.reset_state()
    calls = []

    def fake_get_history(symbol, exchange, interval, start_date, end_date, **kwargs):
        calls.append((symbol, exchange, interval, kwargs.get("source", "api")))
        try:
            df = BrokerData("paper-session").get_history(symbol, exchange, interval, start_date, end_date)
        except Exception as exc:  # the real service answers in words, never raises
            return False, {"status": "error", "message": str(exc)}, 400
        return True, {"status": "success", "data": df.to_dict(orient="records")}, 200

    import portfolio.data as pdata

    monkeypatch.setattr(pdata, "get_history", fake_get_history)
    pdata.clear_price_cache()
    from services import sector_rotation_service as srs

    srs._CLOSES_CACHE.clear()
    yield calls
    pdata.clear_price_cache()
    srs._CLOSES_CACHE.clear()
    md.reset_state()


@pytest.fixture
def historify(monkeypatch):
    """An in-memory Historify. ``load(symbol, exchange)`` fills it from the paper broker."""
    import duckdb

    conn = duckdb.connect(":memory:")
    conn.execute(
        "create table market_data (symbol varchar, exchange varchar, interval varchar, "
        "timestamp bigint, open double, high double, low double, close double, volume bigint, oi bigint)"
    )

    @contextlib.contextmanager
    def get_connection(*args, **kwargs):
        yield conn

    monkeypatch.setattr("database.historify_db.get_connection", get_connection)

    def load(symbol, exchange, start=START, end=END):
        df = BrokerData("paper-session").get_history(symbol, exchange, "D", start, end)
        df = df.assign(symbol=symbol, exchange=exchange, interval="D")
        conn.register("bars", df)
        conn.execute(
            "insert into market_data select symbol, exchange, interval, timestamp, open, high, low, "
            "close, volume, oi from bars"
        )
        conn.unregister("bars")

    yield load
    conn.close()


def _weekend(dates):
    return [d for d in dates if pd.Timestamp(d).weekday() >= 5]


def _finite(value):
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


# -- Portfolio Backtester -----------------------------------------------------------


def _portfolio(source="api", holdings=None, **kw):
    from services.portfolio_service import run_portfolio_backtest

    return run_portfolio_backtest(
        holdings=holdings
        if holdings is not None
        else [{"symbol": "RELIANCE", "exchange": "NSE", "weight": 0.5}, {"symbol": "TCS", "exchange": "NSE", "weight": 0.5}],
        start_date=kw.pop("start", START),
        end_date=kw.pop("end", END),
        benchmark=kw.pop("benchmark", "NIFTY"),
        source=source,
        api_key="k",
        auth_token="paper-session",
        broker="paper",
        mc_simulations=50,
        **kw,
    )


def test_portfolio_backtest_on_paper_history(paper_history):
    ok, body, status = _portfolio()
    assert ok and status == 200, body.get("message")
    for key in ("cagr", "sharpe", "max_drawdown", "volatility"):
        assert _finite(body["metrics"][key]), key
    dates = [p["date"] for p in body["equity"]]
    assert len(dates) > 400
    assert _weekend(dates) == []
    assert _weekend(body["allocation"]["dates"]) == []
    assert {c[0] for c in paper_history} >= {"RELIANCE", "TCS", "NIFTY"}


def test_portfolio_annualises_on_trading_sessions(paper_history):
    """About 250 sessions a year: a calendar-day series would show ~365."""
    ok, body, _ = _portfolio()
    assert ok
    per_year = len(body["equity"]) / 2.0
    assert 240 <= per_year <= 265


def test_portfolio_rejects_empty_holdings():
    ok, body, status = _portfolio(holdings=[])
    assert not ok and status == 400
    assert body["message"] == "no holdings supplied"


def test_portfolio_rejects_duplicate_symbols():
    ok, body, status = _portfolio(holdings=[{"symbol": "TCS", "exchange": "NSE", "weight": 1},
                                            {"symbol": "TCS", "exchange": "NSE", "weight": 1}])
    assert not ok and status == 400


def test_portfolio_unknown_symbol_is_a_trader_message(monkeypatch, paper_history):
    import portfolio.data as pdata

    def none(*a, **k):
        return False, {"status": "error", "message": "No history is available for NOSUCH on NSE"}, 400

    monkeypatch.setattr(pdata, "get_history", none)
    ok, body, status = _portfolio(holdings=[{"symbol": "NOSUCH", "exchange": "NSE", "weight": 1}])
    assert not ok and status in (400, 422)
    assert "NOSUCH" in body["message"]


def test_portfolio_range_with_no_sessions(paper_history):
    ok, body, status = _portfolio(start="2023-01-07", end="2023-01-08")
    assert not ok and status in (400, 422)
    assert body["message"]


def test_portfolio_db_with_empty_historify_says_download(paper_history, historify):
    ok, body, status = _portfolio(source="db")
    assert not ok and status == 422
    assert "Historify" in body["message"]
    # No silent fall back to the broker.
    assert paper_history == []


def test_portfolio_db_after_download(paper_history, historify):
    for symbol, exchange in (("RELIANCE", "NSE"), ("TCS", "NSE"), ("NIFTY", "NSE_INDEX")):
        historify(symbol, exchange)
    ok, body, status = _portfolio(source="db")
    assert ok and status == 200, body.get("message")
    assert _weekend([p["date"] for p in body["equity"]]) == []
    assert _finite(body["metrics"]["cagr"])


# -- SIP Backtester ---------------------------------------------------------------------


def _sip(source="api", **kw):
    from services.sip_service import run_sip_backtest

    return run_sip_backtest(
        kw.pop("symbol", "RELIANCE"),
        kw.pop("exchange", "NSE"),
        kw.pop("start", "2022-01-01"),
        kw.pop("end", END),
        kw.pop("amount", 5000),
        frequency=kw.pop("frequency", "monthly"),
        day_of_month=kw.pop("day_of_month", 1),
        source=source,
        api_key="k",
        auth_token="paper-session",
        broker="paper",
        **kw,
    )


def test_sip_backtest_on_paper_history():
    ok, body, status = _sip()
    assert ok and status == 200, body.get("message")
    executed = [i["executed"] for i in body["installments"]]
    assert len(executed) == 36
    assert _weekend(executed) == []
    assert _finite(body["headline"]["xirr"])
    assert body["headline"]["invested"] == pytest.approx(36 * 5000, rel=0.01)


def test_sip_installment_on_a_weekend_moves_to_a_session():
    ok, body, _ = _sip(start="2022-01-01", end="2022-03-31")  # 1 Jan 2022 is a Saturday
    assert ok
    first = body["installments"][0]
    assert first["requested"] == "2022-01-01"
    assert pd.Timestamp(first["executed"]).weekday() < 5
    assert first["executed"] >= "2022-01-03"


@pytest.mark.parametrize("frequency", ["weekly", "monthly", "quarterly"])
def test_sip_frequencies_on_paper(frequency):
    ok, body, _ = _sip(frequency=frequency, start="2023-01-01", end="2023-12-31")
    assert ok, body.get("message")
    assert _weekend([i["executed"] for i in body["installments"]]) == []


@pytest.mark.parametrize("amount", [0, -100])
def test_sip_rejects_non_positive_amount(amount):
    ok, body, status = _sip(amount=amount)
    assert not ok and status == 400


def test_sip_db_with_empty_historify_says_download(paper_history, historify):
    ok, body, status = _sip(source="db")
    assert not ok and status in (400, 422)
    assert "historify" in body["message"].lower()
    assert paper_history == []


def test_sip_db_after_download(historify):
    historify("RELIANCE", "NSE", "2022-01-01", END)
    ok, body, status = _sip(source="db")
    assert ok and status == 200, body.get("message")
    assert _weekend([i["executed"] for i in body["installments"]]) == []


# -- Sector Rotation ------------------------------------------------------------------------


def test_every_sector_and_benchmark_is_in_the_paper_master_contract():
    """Sector Rotation resolves symbols through the master contract, not only history."""
    from broker.paper.database import instruments as inst
    from services.sector_rotation_service import BENCHMARKS, OPTIONAL_SECTORS, SECTORS

    rows = inst.build_instruments(spot_of=lambda underlying: 1000.0)
    keys = {(r["symbol"], r["exchange"]) for r in rows}
    missing = [s.symbol for s in (*SECTORS, *OPTIONAL_SECTORS, *BENCHMARKS) if (s.symbol, s.exchange) not in keys]
    assert missing == []


@pytest.mark.parametrize("timeframe", ["daily", "weekly"])
def test_sector_rotation_places_every_default_sector(timeframe):
    from services.sector_rotation_service import SECTORS, compute_sector_rotation

    ok, body, status = compute_sector_rotation(
        "NIFTY", timeframe, "api", api_key="k", auth_token="paper-session", broker="paper", end_date=date(2024, 12, 31)
    )
    assert ok and status == 200, body.get("message")
    data = body["data"]
    placed = {i["symbol"] for i in data["instruments"]}
    assert placed == {s.symbol for s in SECTORS}, data["unavailable"]
    for inst_row in data["instruments"]:
        assert _weekend([p["date"] for p in inst_row["tail"]]) == []
    if timeframe == "weekly":
        # Weekly points sit on a session (the week's last trading day), never a Sunday.
        assert all(pd.Timestamp(p["date"]).weekday() < 5 for p in data["instruments"][0]["tail"])


def test_sector_rotation_benchmark_is_left_off_its_own_map():
    from services.sector_rotation_service import compute_sector_rotation

    ok, body, _ = compute_sector_rotation(
        "NIFTY", "daily", "api", instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"},
                                               {"symbol": "RELIANCE", "exchange": "NSE"}],
        api_key="k", auth_token="paper-session", broker="paper", end_date=date(2024, 12, 31),
    )
    assert ok
    assert [u["symbol"] for u in body["data"]["unavailable"]] == ["NIFTY"]


def test_sector_rotation_db_with_empty_historify_says_download(paper_history, historify):
    from services.sector_rotation_service import compute_sector_rotation

    ok, body, status = compute_sector_rotation("NIFTY", "daily", "db", end_date=date(2024, 12, 31))
    assert not ok and status == 422
    assert "Download it in Historify, or switch the data source to Broker API." in body["message"]
    assert paper_history == []


@pytest.mark.parametrize("bad", [{"benchmark": "NOPE"}, {"timeframe": "monthly"}, {"source": "yahoo"}])
def test_sector_rotation_refuses_bad_arguments(bad):
    from services.sector_rotation_service import compute_sector_rotation

    args = {"benchmark": "NIFTY", "timeframe": "daily", "source": "api", **bad}
    ok, _body, status = compute_sector_rotation(args["benchmark"], args["timeframe"], args["source"])
    assert not ok and status == 400


# -- intervals the paper broker does not offer ---------------------------------------


def test_consumers_ask_the_paper_broker_only_for_intervals_it_offers(paper_history):
    offered = set(BrokerData("paper-session").get_intervals())
    _portfolio()
    _sip()
    from services.sector_rotation_service import compute_sector_rotation

    compute_sector_rotation("NIFTY", "weekly", "api", api_key="k", auth_token="t", broker="paper",
                            end_date=date(2024, 12, 31))
    asked = {interval for _s, _e, interval, _src in paper_history}
    assert asked and asked <= offered, asked - offered
