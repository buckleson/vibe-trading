"""End-to-end smoke test of a running Buckleson app (Sandbox mode, paper broker).

Usage:
    uv run python scripts/bk_smoke.py [--url http://127.0.0.1:5000]

Every check prints one line: PASS, FAIL or SKIP, its name and a short detail.
The exit code is 0 only when no check failed. The checks place orders in the
Sandbox only (each order response must say mode 'analyze'); they square off
and cancel what they create at the end.

The API key comes from GET /auth/session-status, which local mode answers
with the operator's key. Session routes (close_position, Historify) send the
CSRF token from GET /auth/csrf-token.

test/test_bk_sandbox_smoke.py runs the same checks under pytest, and skips
them all when no server answers.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone

import httpx

IST = timezone(timedelta(hours=5, minutes=30))
STRATEGY = "bk-smoke"
REMOVED_BROKERS_SAMPLE = ("angel", "dhan", "fyers", "upstox", "shoonya", "fivepaisa")


class Skip(Exception):
    """The check does not apply now (for example, inside market hours)."""


class CheckFailed(AssertionError):
    pass


def expect(condition, message):
    if not condition:
        raise CheckFailed(message)


@dataclass
class Smoke:
    url: str
    client: httpx.Client = field(init=False)
    api_key: str = ""
    csrf: str = ""
    lot_sizes: dict = field(default_factory=dict)
    created_orders: list = field(default_factory=list)

    def __post_init__(self):
        self.url = self.url.rstrip("/")
        self.client = httpx.Client(base_url=self.url, timeout=60.0, follow_redirects=False)

    # -- transport ---------------------------------------------------------------

    def api(self, path, payload=None, expect_ok=True):
        body = {"apikey": self.api_key, **(payload or {})}
        res = self.client.post(f"/api/v1/{path}", json=body)
        try:
            data = res.json()
        except ValueError as exc:
            raise CheckFailed(f"{path}: HTTP {res.status_code}, not JSON") from exc
        if expect_ok:
            expect(
                res.status_code == 200 and data.get("status") == "success",
                f"{path}: HTTP {res.status_code} {str(data.get('message'))[:200]}",
            )
        return res, data

    def session_post(self, path, payload=None):
        if not self.csrf:
            self.csrf = self.client.get("/auth/csrf-token").json()["csrf_token"]
        return self.client.post(path, json=payload or {}, headers={"X-CSRFToken": self.csrf, "Accept": "application/json"})

    def session_get(self, path, params=None):
        res = self.client.get(path, params=params, headers={"Accept": "application/json"})
        expect(res.status_code == 200, f"{path}: HTTP {res.status_code} {res.text[:200]}")
        return res.json()

    def session_delete(self, path, payload=None):
        if not self.csrf:
            self.csrf = self.client.get("/auth/csrf-token").json()["csrf_token"]
        return self.client.request("DELETE", path, json=payload, headers={"X-CSRFToken": self.csrf, "Accept": "application/json"})

    def order(self, **fields):
        payload = {"strategy": STRATEGY, "pricetype": "MARKET", "price": 0, **fields}
        res, data = self.api("placeorder", payload, expect_ok=False)
        if data.get("orderid"):
            self.created_orders.append(data["orderid"])
        return res, data

    def lot_size(self, symbol, exchange):
        key = (symbol, exchange)
        if key not in self.lot_sizes:
            _, data = self.api("symbol", {"symbol": symbol, "exchange": exchange})
            self.lot_sizes[key] = int(float(data["data"]["lotsize"]))
        return self.lot_sizes[key]

    def position_qty(self, symbol, exchange, product):
        _, data = self.api("positionbook")
        for row in data.get("data") or []:
            if (row["symbol"], row["exchange"], row["product"]) == (symbol, exchange, product):
                return float(row["quantity"])
        return 0.0

    def nifty_future(self):
        _, data = self.api("expiry", {"symbol": "NIFTY", "exchange": "NFO", "instrumenttype": "futures"})
        day, mon, yr = data["data"][0].split("-")
        return f"NIFTY{day}{mon}{yr}FUT"

    def first_option_expiry(self):
        _, data = self.api("expiry", {"symbol": "NIFTY", "exchange": "NFO", "instrumenttype": "options"})
        day, mon, yr = data["data"][0].split("-")
        return f"{day}{mon}{yr}"


def _weekend(dates):
    return [d for d in dates if date.fromisoformat(str(d)[:10]).weekday() >= 5]


def _analyze(data, what):
    expect(data.get("mode") == "analyze", f"{what} answered mode {data.get('mode')!r}, not 'analyze'")


def _gone(res):
    """A removed route: a 404/405, or the React app's HTML fallback, never a JSON answer."""
    if res.status_code in (404, 405):
        return True
    return "application/json" not in res.headers.get("content-type", "")


# --------------------------------------------------------------------------- #
# Checks. Each takes the Smoke and returns a one-line detail, raises Skip or fails.
# --------------------------------------------------------------------------- #


def check_server_and_key(s: Smoke):
    res = s.client.get("/auth/session-status")
    expect(res.status_code == 200, f"session-status HTTP {res.status_code}")
    data = res.json()
    s.api_key = data.get("api_key") or ""
    expect(s.api_key, "session-status gave no api_key (local mode off?)")
    expect(data.get("broker") == "paper", f"logged-in broker is {data.get('broker')!r}, expected 'paper'")
    return f"user {data.get('user')}, broker paper"


def check_sandbox_mode(s: Smoke):
    _, data = s.api("analyzer")
    expect(data["data"]["analyze_mode"] is True, "Sandbox (analyzer) mode is off")
    return "analyze mode on"


def check_broker_list(s: Smoke):
    res = s.client.get("/api/broker/list")
    expect(res.status_code == 200, f"HTTP {res.status_code}")
    ids = [b["id"] for b in res.json()["data"]["brokers"]]
    expect(sorted(ids) == ["paper", "zerodha"], f"brokers listed: {ids}")
    return "paper, zerodha"


def check_quotes(s: Smoke):
    _, data = s.api("quotes", {"symbol": "SBIN", "exchange": "NSE"})
    ltp = data["data"]["ltp"]
    expect(ltp and ltp > 0, f"SBIN ltp {ltp}")
    return f"SBIN ltp {ltp}"


def check_multiquotes(s: Smoke):
    symbols = [
        {"symbol": "SBIN", "exchange": "NSE"},
        {"symbol": "RELIANCE", "exchange": "BSE"},
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
    ]
    _, data = s.api("multiquotes", {"symbols": symbols})
    results = data.get("results") or data.get("data") or []
    expect(len(results) == 3, f"{len(results)} results")
    expect(all((r.get("data") or {}).get("ltp", 0) > 0 for r in results), "a symbol has no ltp")
    return "3 quotes"


def check_depth(s: Smoke):
    _, data = s.api("depth", {"symbol": "INFY", "exchange": "NSE"})
    expect(len(data["data"]["bids"]) == 5 and len(data["data"]["asks"]) == 5, "depth is not 5 levels")
    return "5 levels"


def check_bad_symbol_quote_refused(s: Smoke):
    res, data = s.api("quotes", {"symbol": "NOSUCHSYMBOL", "exchange": "NSE"}, expect_ok=False)
    expect(data.get("status") == "error" and res.status_code >= 400, f"HTTP {res.status_code} {data}")
    return f"HTTP {res.status_code}"


def check_history_daily(s: Smoke):
    _, data = s.api("history", {"symbol": "RELIANCE", "exchange": "NSE", "interval": "D",
                                "start_date": "2024-01-01", "end_date": "2024-03-31"})
    rows = data["data"]
    expect(rows, "no daily bars")
    days = [datetime.fromtimestamp(r["timestamp"], UTC).date().isoformat() for r in rows]
    expect(_weekend(days) == [], f"weekend daily bars: {_weekend(days)[:3]}")
    return f"{len(rows)} daily bars, no weekends"


def check_history_intraday(s: Smoke):
    day = datetime.now(IST).date() - timedelta(days=7)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    _, data = s.api("history", {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m",
                                "start_date": day.isoformat(), "end_date": day.isoformat()})
    rows = data["data"]
    expect(rows, "no 5m bars")
    times = [datetime.fromtimestamp(r["timestamp"], IST).strftime("%H:%M") for r in rows]
    expect(times[0] == "09:15" and times[-1] <= "15:25", f"session {times[0]}..{times[-1]}")
    return f"{len(rows)} bars {times[0]}..{times[-1]} IST"


def check_history_unsupported_interval(s: Smoke):
    res, data = s.api("history", {"symbol": "RELIANCE", "exchange": "NSE", "interval": "W",
                                  "start_date": "2024-01-01", "end_date": "2024-03-31"}, expect_ok=False)
    expect(data.get("status") == "error", f"interval W answered {data.get('status')}")
    return f"refused, HTTP {res.status_code}"


def check_cnc_order_fills_and_updates_books(s: Smoke):
    _, before = s.api("funds")
    cash_before = float(before["data"]["availablecash"])
    qty_before = s.position_qty("SBIN", "NSE", "CNC")
    res, data = s.order(symbol="SBIN", exchange="NSE", action="BUY", quantity=1, product="CNC")
    expect(data.get("status") == "success", f"placeorder: {data.get('message')}")
    _analyze(data, "placeorder")
    orderid = data["orderid"]
    _, status = s.api("orderstatus", {"strategy": STRATEGY, "orderid": orderid})
    expect(status["data"]["order_status"] == "complete", f"order status {status['data'].get('order_status')}")
    expect(s.position_qty("SBIN", "NSE", "CNC") == qty_before + 1, "position did not grow by 1")
    _, trades = s.api("tradebook")
    expect(any(str(t.get("orderid")) == str(orderid) for t in trades["data"]), "trade missing from tradebook")
    _, after = s.api("funds")
    expect(float(after["data"]["availablecash"]) < cash_before, "available cash did not drop")
    return f"order {orderid} complete, position and funds updated"


def check_nrml_future_order(s: Smoke):
    symbol = s.nifty_future()
    lot = s.lot_size(symbol, "NFO")
    _, data = s.order(symbol=symbol, exchange="NFO", action="BUY", quantity=lot, product="NRML")
    expect(data.get("status") == "success", f"{symbol}: {data.get('message')}")
    _analyze(data, "placeorder NRML")
    expect(s.position_qty(symbol, "NFO", "NRML") >= lot, "NRML position missing")
    return f"{symbol} x{lot} filled"


def check_options_order(s: Smoke):
    expiry = s.first_option_expiry()
    _, chain = s.api("optionchain", {"underlying": "NIFTY", "exchange": "NSE_INDEX",
                                     "expiry_date": expiry, "strike_count": 2})
    expect(chain.get("chain") or chain.get("data"), "empty option chain")
    payload = {"strategy": STRATEGY, "underlying": "NIFTY", "exchange": "NSE_INDEX", "expiry_date": expiry,
               "offset": "ATM", "option_type": "CE", "action": "BUY", "pricetype": "MARKET", "product": "NRML"}
    probe, sym = s.api("optionsymbol", {k: payload[k] for k in ("underlying", "exchange", "expiry_date",
                                                                  "offset", "option_type")})
    lot = int(float(sym.get("lotsize") or sym.get("data", {}).get("lotsize") or 0)) or s.lot_size(sym["symbol"], "NFO")
    _, data = s.api("optionsorder", {**payload, "quantity": lot}, expect_ok=False)
    expect(data.get("status") == "success", f"optionsorder: {data.get('message')}")
    _analyze(data, "optionsorder")
    if data.get("orderid"):
        s.created_orders.append(data["orderid"])
    return f"{data.get('symbol')} x{lot}"


def check_zero_quantity_refused(s: Smoke):
    res, data = s.order(symbol="SBIN", exchange="NSE", action="BUY", quantity=0, product="CNC")
    expect(data.get("status") == "error" and res.status_code == 400, f"HTTP {res.status_code} {data}")
    return "HTTP 400"


def check_bad_symbol_order_refused(s: Smoke):
    res, data = s.order(symbol="NOSUCHSYMBOL", exchange="NSE", action="BUY", quantity=1, product="CNC")
    expect(data.get("status") == "error" and res.status_code >= 400, f"HTTP {res.status_code} {data}")
    return f"HTTP {res.status_code}"


def check_mis_refused_after_square_off(s: Smoke):
    now = datetime.now(IST)
    if "09:00" <= now.strftime("%H:%M") < "15:15":
        raise Skip(f"inside the MIS window ({now:%H:%M} IST)")
    res, data = s.order(symbol="SBIN", exchange="NSE", action="BUY", quantity=1, product="MIS")
    expect(data.get("status") == "error", f"MIS order accepted at {now:%H:%M} IST")
    expect("square-off" in str(data.get("message")), f"message: {data.get('message')}")
    _analyze(data, "MIS refusal")
    return f"refused at {now:%H:%M} IST"


def check_limit_modify_cancel(s: Smoke):
    _, quote = s.api("quotes", {"symbol": "SBIN", "exchange": "NSE"})
    price = round(quote["data"]["ltp"] * 0.5, 1)
    _, data = s.order(symbol="SBIN", exchange="NSE", action="BUY", quantity=1, product="CNC",
                      pricetype="LIMIT", price=price)
    expect(data.get("status") == "success", f"limit order: {data.get('message')}")
    orderid = data["orderid"]
    _, mod = s.api("modifyorder", {"strategy": STRATEGY, "orderid": orderid, "symbol": "SBIN", "exchange": "NSE",
                                   "action": "BUY", "product": "CNC", "pricetype": "LIMIT",
                                   "price": round(price * 0.9, 1), "quantity": 2,
                                   "disclosed_quantity": 0, "trigger_price": 0})
    _analyze(mod, "modifyorder")
    _, can = s.api("cancelorder", {"strategy": STRATEGY, "orderid": orderid})
    _analyze(can, "cancelorder")
    _, status = s.api("orderstatus", {"strategy": STRATEGY, "orderid": orderid})
    expect(status["data"]["order_status"] == "cancelled", f"status {status['data'].get('order_status')}")
    return f"order {orderid} modified and cancelled"


def check_session_close_position(s: Smoke):
    if s.position_qty("SBIN", "NSE", "CNC") == 0:
        s.order(symbol="SBIN", exchange="NSE", action="BUY", quantity=1, product="CNC")
    res = s.session_post("/close_position", {"symbol": "SBIN", "exchange": "NSE", "product": "CNC"})
    expect(res.status_code == 200 and res.json().get("status") == "success", f"HTTP {res.status_code} {res.text[:200]}")
    expect(s.position_qty("SBIN", "NSE", "CNC") == 0, "SBIN CNC still open")
    return "SBIN CNC closed from the Positions route"


def check_session_cancel_all(s: Smoke):
    _, quote = s.api("quotes", {"symbol": "TCS", "exchange": "NSE"})
    s.order(symbol="TCS", exchange="NSE", action="BUY", quantity=1, product="CNC", pricetype="LIMIT",
            price=round(quote["data"]["ltp"] * 0.5, 1))
    res = s.session_post("/cancel_all_orders")
    expect(res.status_code == 200, f"HTTP {res.status_code} {res.text[:200]}")
    _, book = s.api("orderbook")
    still_open = [o for o in book["data"]["orders"] if o.get("order_status") == "open"]
    expect(still_open == [], f"{len(still_open)} orders still open")
    return "no open orders"


def check_rest_close_all(s: Smoke):
    _, data = s.api("closeposition", {"strategy": STRATEGY})
    _analyze(data, "closeposition")
    _, book = s.api("positionbook")
    open_rows = [p for p in book["data"] if float(p["quantity"]) != 0]
    expect(open_rows == [], f"still open: {[p['symbol'] for p in open_rows]}")
    return "flat"


def check_portfolio_backtest(s: Smoke):
    payload = {"holdings": [{"symbol": "RELIANCE", "exchange": "NSE", "weight": 0.5},
                            {"symbol": "TCS", "exchange": "NSE", "weight": 0.5}],
               "start_date": "2023-01-01", "end_date": "2024-12-31", "benchmark": "NIFTY", "source": "api"}
    _, data = s.api("portfolio/backtest", payload)
    for key in ("cagr", "sharpe", "max_drawdown"):
        value = data["metrics"][key]
        expect(isinstance(value, (int, float)) and math.isfinite(value), f"{key} = {value}")
    dates = [p["date"] for p in data["equity"]]
    expect(_weekend(dates) == [], f"{len(_weekend(dates))} weekend dates in the equity curve")
    return f"cagr {data['metrics']['cagr']:.4f}, {len(dates)} sessions"


def check_sip_backtest(s: Smoke):
    payload = {"symbol": "RELIANCE", "exchange": "NSE", "start_date": "2022-01-01", "end_date": "2024-12-31",
               "amount": 5000, "frequency": "monthly", "day_of_month": 1, "source": "api"}
    _, data = s.api("sip/backtest", payload)
    executed = [i["executed"] for i in data["installments"]]
    expect(len(executed) == 36, f"{len(executed)} installments")
    expect(_weekend(executed) == [], f"weekend installments: {_weekend(executed)[:3]}")
    xirr = data["headline"]["xirr"]
    expect(isinstance(xirr, (int, float)) and math.isfinite(xirr), f"xirr {xirr}")
    return f"36 installments, xirr {xirr:.4f}"


def check_sector_rotation(s: Smoke):
    _, data = s.api("sectorrotation", {"benchmark": "NIFTY", "timeframe": "weekly", "source": "api"})
    unavailable = [u["symbol"] for u in data["data"]["unavailable"]]
    expect(unavailable == [], f"not placed: {unavailable}")
    return f"{len(data['data']['instruments'])} sectors placed"


def check_historify_download(s: Smoke):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=60)
    # Start from a clean slate: upsert never removes rows stored by earlier runs.
    res = s.session_delete("/historify/api/delete", {"symbol": "RELIANCE", "exchange": "NSE", "interval": "D"})
    expect(res.status_code == 200, f"historify delete HTTP {res.status_code} {res.text[:200]}")
    res = s.session_post("/historify/api/download", {"symbol": "RELIANCE", "exchange": "NSE", "interval": "D",
                                                     "start_date": start.isoformat(), "end_date": end.isoformat()})
    expect(res.status_code == 200 and res.json().get("status") == "success", f"HTTP {res.status_code} {res.text[:200]}")
    data = s.client.get("/historify/api/data", params={"symbol": "RELIANCE", "exchange": "NSE", "interval": "D",
                                                        "start_date": start.isoformat(), "end_date": end.isoformat()},
                        headers={"Accept": "application/json"}).json()
    rows = data.get("data") or []
    expect(rows, "Historify returned no rows after the download")
    days = [datetime.fromtimestamp(r.get("time") or r.get("timestamp"), UTC).date().isoformat() for r in rows]
    expect(_weekend(days) == [], f"weekend rows in Historify: {_weekend(days)[:3]}")
    return f"{len(rows)} daily rows stored"


def check_platform_routes_gone(s: Smoke):
    probes = [
        ("post", "/chartink/webhook/smoke-test", {"stocks": "SBIN"}),
        ("get", "/chartink/api/strategies", None),
        ("get", "/chartink/search?q=REL", None),
        ("post", "/tradingview/", {"symbol": "SBIN"}),
        ("post", "/gocharting/", {"symbol": "SBIN"}),
        ("get", "/platforms/", None),
    ]
    alive = []
    for method, path, body in probes:
        kwargs = {"headers": {"Accept": "application/json"}}
        if body is not None:
            kwargs["json"] = body
        res = getattr(s.client, method)(path, **kwargs)
        if not _gone(res):
            alive.append(f"{method.upper()} {path} -> {res.status_code}")
    expect(alive == [], f"still answering: {alive}")
    return f"{len(probes)} removed routes gone"


def check_removed_broker_login_gone(s: Smoke):
    for name in REMOVED_BROKERS_SAMPLE:
        res = s.client.get(f"/{name}/callback", headers={"Accept": "application/json"})
        expect(res.status_code != 200 or "application/json" not in res.headers.get("content-type", "")
               or res.json().get("status") != "success", f"/{name}/callback answered success")
    for path in ("/dhan/initiate-oauth", "/samco/ip-status", "/nubra/ip-status"):
        res = s.client.get(path, headers={"Accept": "application/json"})
        expect(_gone(res), f"{path} still answers HTTP {res.status_code}")
    return "removed broker routes gone"


def check_claude_status(s: Smoke):
    res = s.client.get("/claude/api/status", headers={"Accept": "application/json"})
    expect(res.status_code == 200, f"HTTP {res.status_code}")
    data = res.json()
    cli = data["cli"]
    expect("installed" in cli and "logged_in" in cli, "cli block incomplete")
    expect("plan" in cli, "cli.plan missing")
    if cli["logged_in"]:
        expect((cli["plan"] or {}).get("label"), "signed in but no plan label")
    expect(data.get("install", {}).get("platform") in ("windows", "mac", "linux"), "install.platform missing")
    expect(data.get("login", {}).get("state") in ("idle", "starting", "waiting", "connected", "failed"),
           "login.state missing")
    label = (cli.get("plan") or {}).get("label")
    return f"installed={cli['installed']} signed_in={cli['logged_in']} plan={label}"


def check_scalping(s: Smoke):
    under = s.session_get("/scalping/api/underlyings")
    expect(any(u["underlying"] == "NIFTY" for u in under["data"]), "NIFTY not offered")
    expiries = s.session_get("/scalping/api/expiry", {"underlying": "NIFTY", "exchange": "NFO"})["data"]
    expect(expiries, "no scalping expiries")
    chain = s.session_get("/scalping/api/strikes", {"underlying": "NIFTY", "exchange": "NFO", "expiry": expiries[0]})
    atm = next(row for row in chain["chain"] if row["strike"] == chain["atm_strike"])
    symbol, lot = atm["ce"]["symbol"], int(atm["ce"]["lotsize"])
    res = s.session_post("/scalping/api/order", {"symbol": symbol, "exchange": "NFO", "action": "BUY",
                                                 "product": "NRML", "quantity": lot})
    data = res.json()
    expect(res.status_code == 200 and data.get("status") == "success", f"scalping order: {data.get('message')}")
    _analyze(data, "scalping order")
    refused = s.session_post("/scalping/api/order", {"symbol": symbol, "exchange": "NFO", "action": "BUY",
                                                     "product": "CNC", "quantity": lot}).json()
    expect(refused.get("status") == "error", "scalping accepted CNC on NFO")
    closed = s.session_post("/scalping/api/close_all").json()
    expect(closed.get("status") == "success", f"close_all: {closed.get('message')}")
    expect(s.position_qty(symbol, "NFO", "NRML") == 0, f"{symbol} still open after close_all")
    cancelled = s.session_post("/scalping/api/cancel_all").json()
    expect(cancelled.get("status") == "success", f"cancel_all: {cancelled.get('message')}")
    return f"{symbol} x{lot} NRML in and out"


def check_strategy_module_sandbox_run(s: Smoke):
    config = {"name": "bk smoke", "underlying": "NIFTY", "underlying_exchange": "NSE_INDEX",
              "strategy_type": "positional", "entry_time": "09:20", "exit_time": "15:10",
              "legs": [{"segment": "options", "position": "B", "lots": 1, "option_type": "CE",
                        "strike_mode": "atm", "atm_offset": "ATM", "expiry": "weekly"}]}
    res = s.session_post("/strategy/api/strategies", config)
    expect(res.status_code in (200, 201), f"create: HTTP {res.status_code} {res.text[:200]}")
    sid = res.json()["data"]["id"]
    try:
        started = s.session_post(f"/strategy/api/strategies/{sid}/start", {"mode": "sandbox"}).json()
        expect(started.get("status") == "success", f"start: {started.get('message')}")
        expect(all(leg.get("ok") for leg in started.get("legs", [])), f"a leg failed: {started.get('legs')}")
        positions = s.session_get(f"/strategy/api/strategies/{sid}/positions")
        _analyze(positions, "strategy positions")
        expect(any(p["quantity"] for p in positions["data"]), "no leg position")
        closed = s.session_post(f"/strategy/api/strategies/{sid}/close_all").json()
        expect(closed.get("status") == "success", f"close_all: {closed.get('message')}")
        s.session_post(f"/strategy/api/strategies/{sid}/stop")  # already stopped by close_all is fine
    finally:
        s.session_delete(f"/strategy/api/strategies/{sid}")
    return f"strategy {sid}: started in sandbox, leg filled, closed, deleted"


def check_flow_order_node(s: Smoke):
    graph = {"name": "bk smoke flow",
             "nodes": [{"id": "s", "type": "start", "position": {"x": 0, "y": 0}, "data": {"scheduleType": "once"}},
                       {"id": "o", "type": "placeOrder", "position": {"x": 0, "y": 100},
                        "data": {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 1,
                                 "priceType": "MARKET", "product": "CNC"}}],
             "edges": [{"id": "e", "source": "s", "target": "o"}]}
    res = s.session_post("/flow/api/workflows", graph)
    expect(res.status_code in (200, 201), f"create: HTTP {res.status_code} {res.text[:200]}")
    wid = res.json().get("id")
    try:
        run = s.session_post(f"/flow/api/workflows/{wid}/execute").json()
        expect(run.get("status") == "success", f"execute: {run.get('message') or run.get('error')}")
        logs = " ".join(entry.get("message", "") for entry in run.get("logs", []))
        expect("'mode': 'analyze'" in logs and "'status': 'success'" in logs, f"order log: {logs[-200:]}")
        executions = s.session_get(f"/flow/api/workflows/{wid}/executions")
        expect(executions, "no execution recorded")
    finally:
        s.session_delete(f"/flow/api/workflows/{wid}")
    return f"workflow {wid} placed an analyze-mode order"


_MCP_PROBE = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("bk_mcpserver", sys.argv[3])
m = importlib.util.module_from_spec(spec)
sys.modules["bk_mcpserver"] = m
sys.argv = ["mcpserver", sys.argv[1], sys.argv[2]]
spec.loader.exec_module(m)
out = {}
out["place_order"] = json.loads(m.place_order(symbol="SBIN", exchange="NSE", action="BUY", quantity=1, product="CNC"))["data"]
out["get_order_book"] = json.loads(m.get_order_book())["data"]
out["get_position_book"] = json.loads(m.get_position_book())["data"]
out["close_all_positions"] = json.loads(m.close_all_positions())["data"]
sys.stdout.write("BKRESULT " + json.dumps(out) + chr(10))
"""


def check_claude_mcp_tools(s: Smoke):
    here = os.path.dirname(os.path.abspath(__file__))
    server = os.path.join(os.path.dirname(here), "mcp", "mcpserver.py")
    proc = subprocess.run([sys.executable, "-c", _MCP_PROBE, s.api_key, s.url, server], cwd=here,
                          capture_output=True, text=True, timeout=120)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("BKRESULT ")), None)
    expect(line, f"MCP probe failed: {(proc.stderr or proc.stdout)[-300:]}")
    out = json.loads(line[len("BKRESULT "):])
    for tool, data in out.items():
        expect(data.get("status") == "success", f"{tool}: {str(data.get('message'))[:120]}")
    _analyze(out["place_order"], "MCP place_order")
    _analyze(out["close_all_positions"], "MCP close_all_positions")
    return "place_order, get_order_book, get_position_book, close_all_positions"


CHECKS: list[tuple[str, Callable[[Smoke], str]]] = [
    ("server and API key", check_server_and_key),
    ("Sandbox mode on", check_sandbox_mode),
    ("broker list is paper and zerodha", check_broker_list),
    ("quotes", check_quotes),
    ("multiquotes", check_multiquotes),
    ("depth", check_depth),
    ("bad symbol quote refused", check_bad_symbol_quote_refused),
    ("daily history, no weekends", check_history_daily),
    ("intraday history in session", check_history_intraday),
    ("unsupported interval refused", check_history_unsupported_interval),
    ("CNC order fills, books and funds update", check_cnc_order_fills_and_updates_books),
    ("NRML future order fills", check_nrml_future_order),
    ("options order fills", check_options_order),
    ("zero quantity refused", check_zero_quantity_refused),
    ("bad symbol order refused", check_bad_symbol_order_refused),
    ("MIS refused after square-off", check_mis_refused_after_square_off),
    ("LIMIT order modify and cancel", check_limit_modify_cancel),
    ("close position (session route)", check_session_close_position),
    ("cancel all orders (session route)", check_session_cancel_all),
    ("close all positions (REST)", check_rest_close_all),
    ("scalping NRML order and flatten", check_scalping),
    ("Strategy module sandbox run", check_strategy_module_sandbox_run),
    ("Flow order node", check_flow_order_node),
    ("Claude MCP tools", check_claude_mcp_tools),
    ("Portfolio Backtester on paper", check_portfolio_backtest),
    ("SIP Backtester on paper", check_sip_backtest),
    ("Sector Rotation on paper", check_sector_rotation),
    ("Historify download", check_historify_download),
    ("platform routes gone", check_platform_routes_gone),
    ("removed broker routes gone", check_removed_broker_login_gone),
    ("Claude status", check_claude_status),
]


def cleanup(s: Smoke) -> None:
    if not s.api_key:
        return
    try:
        s.api("cancelallorder", {"strategy": STRATEGY}, expect_ok=False)
        s.api("closeposition", {"strategy": STRATEGY}, expect_ok=False)
    except Exception:  # noqa: BLE001 - best effort; the checks already reported
        pass


def run(url: str, out=sys.stdout) -> dict[str, tuple[str, str]]:
    """Run every check in order. Returns {name: (PASS|FAIL|SKIP, detail)}."""
    smoke = Smoke(url)
    results: dict[str, tuple[str, str]] = {}
    try:
        for name, check in CHECKS:
            started = time.monotonic()
            try:
                detail = check(smoke)
                outcome = "PASS"
            except Skip as exc:
                outcome, detail = "SKIP", str(exc)
            except Exception as exc:  # noqa: BLE001 - one line per check, keep going
                outcome, detail = "FAIL", f"{type(exc).__name__}: {exc}"
            results[name] = (outcome, detail)
            out.write(f"{outcome} {name}: {detail} ({time.monotonic() - started:.1f}s)\n")
            out.flush()
            if name == "server and API key" and outcome != "PASS":
                break
    finally:
        cleanup(smoke)
        smoke.client.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.getenv("BUCKLESON_SMOKE_URL", "http://127.0.0.1:5000"))
    args = parser.parse_args()
    results = run(args.url)
    failed = [n for n, (outcome, _) in results.items() if outcome == "FAIL"]
    sys.stdout.write(f"{len(results) - len(failed)} of {len(results)} checks passed or skipped; {len(failed)} failed\n")
    return 1 if failed or len(results) < len(CHECKS) else 0


if __name__ == "__main__":
    sys.exit(main())
