"""T07: simulated history of past days follows exchange sessions.

Before T07, PAPER_MARKET_HOURS=always (the default) produced Saturday and
Sunday daily bars and round-the-clock intraday bars for every past day, which
distorts every backtest. Past days must be weekdays 09:15-15:30 IST whatever
the setting; today keeps following the live setting. Simulated data only, no
network.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from broker.paper.api import market_data as md
from broker.paper.api.data import BrokerData, PaperDataError
from broker.paper.database import instruments as inst


@pytest.fixture(autouse=True)
def simulated(monkeypatch):
    monkeypatch.setenv("PAPER_DATA_SOURCE", "simulated")
    monkeypatch.setenv("PAPER_MARKET_HOURS", "always")
    md.reset_state()
    yield
    md.reset_state()


def _h():
    return BrokerData("paper-session")


def _utc_days(df):
    return [datetime.fromtimestamp(int(t), UTC).date() for t in df["timestamp"]]


def _ist(df):
    return [datetime.fromtimestamp(int(t), inst.IST) for t in df["timestamp"]]


def _past_weekday(back=7):
    day = datetime.now(inst.IST).date() - timedelta(days=back)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _past_weekend_day(back=7):
    day = datetime.now(inst.IST).date() - timedelta(days=back)
    while day.weekday() != 5:
        day -= timedelta(days=1)
    return day


HOURS = ["always", "exchange"]


# -- daily bars ---------------------------------------------------------------


@pytest.mark.parametrize("hours", HOURS)
def test_daily_history_skips_weekends(monkeypatch, hours):
    monkeypatch.setenv("PAPER_MARKET_HOURS", hours)
    df = _h().get_history("RELIANCE", "NSE", "D", "2023-01-01", "2023-01-15")
    days = _utc_days(df)
    assert len(df) == 10
    assert all(d.weekday() < 5 for d in days)
    assert days[0] == date(2023, 1, 2) and days[-1] == date(2023, 1, 13)
    assert all(int(t) % 86400 == 0 for t in df["timestamp"])


@pytest.mark.parametrize("hours", HOURS)
def test_daily_index_history_over_two_years_has_no_weekends(monkeypatch, hours):
    monkeypatch.setenv("PAPER_MARKET_HOURS", hours)
    df = _h().get_history("NIFTY", "NSE_INDEX", "D", "2023-01-01", "2024-12-31")
    days = _utc_days(df)
    assert days and all(d.weekday() < 5 for d in days)
    # 2023 and 2024 hold 260 + 262 weekdays (holidays are not modelled).
    assert len(days) == 522


def test_daily_range_entirely_on_a_weekend_is_empty():
    df = _h().get_history("RELIANCE", "NSE", "D", "2023-01-07", "2023-01-08")
    assert df.empty
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "oi"]


def test_end_before_start_is_empty():
    df = _h().get_history("RELIANCE", "NSE", "D", "2023-02-10", "2023-02-01")
    assert df.empty


def test_daily_bars_are_ohlc_consistent():
    df = _h().get_history("TCS", "NSE", "D", "2024-03-01", "2024-03-31")
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
    assert (df["volume"] > 0).all()


# -- intraday bars of past days ------------------------------------------------


@pytest.mark.parametrize("hours", HOURS)
def test_hourly_bars_of_a_past_weekday_sit_in_the_session(monkeypatch, hours):
    monkeypatch.setenv("PAPER_MARKET_HOURS", hours)
    day = _past_weekday()
    df = _h().get_history("RELIANCE", "NSE", "1h", day.isoformat(), day.isoformat())
    stamps = _ist(df)
    assert [s.strftime("%H:%M") for s in stamps] == [
        "09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15",
    ]
    assert all(s.date() == day for s in stamps)


@pytest.mark.parametrize("hours", HOURS)
def test_one_minute_bars_of_a_past_weekday(monkeypatch, hours):
    monkeypatch.setenv("PAPER_MARKET_HOURS", hours)
    day = _past_weekday()
    df = _h().get_history("SBIN", "NSE", "1m", day.isoformat(), day.isoformat())
    stamps = _ist(df)
    assert len(df) == 375  # 09:15 to 15:29
    assert stamps[0].strftime("%H:%M") == "09:15" and stamps[-1].strftime("%H:%M") == "15:29"


@pytest.mark.parametrize("hours", HOURS)
def test_past_weekend_intraday_is_empty(monkeypatch, hours):
    monkeypatch.setenv("PAPER_MARKET_HOURS", hours)
    saturday = _past_weekend_day()
    sunday = saturday + timedelta(days=1)
    df = _h().get_history("RELIANCE", "NSE", "5m", saturday.isoformat(), sunday.isoformat())
    assert df.empty


def test_five_minute_bars_over_a_past_week():
    df = _h().get_history("RELIANCE", "NSE", "5m", "2026-11-02", "2026-11-08")
    stamps = _ist(df)
    assert {s.date() for s in stamps} == {date(2026, 11, d) for d in (2, 3, 4, 5, 6)}
    assert len(df) == 5 * 75
    assert all("09:15" <= s.strftime("%H:%M") <= "15:25" for s in stamps)


def test_past_day_volume_does_not_depend_on_the_live_setting(monkeypatch):
    day = _past_weekday()
    always = _h().get_history("RELIANCE", "NSE", "15m", day.isoformat(), day.isoformat())
    md.reset_state()
    monkeypatch.setenv("PAPER_MARKET_HOURS", "exchange")
    exchange = _h().get_history("RELIANCE", "NSE", "15m", day.isoformat(), day.isoformat())
    pd.testing.assert_frame_equal(always, exchange)
    assert always["volume"].sum() > 0


# -- today follows the live setting ---------------------------------------------


def test_today_under_always_runs_around_the_clock():
    today = datetime.now(inst.IST).date()
    df = _h().get_history("RELIANCE", "NSE", "1h", today.isoformat(), today.isoformat())
    stamps = _ist(df)
    assert stamps, "always: today's bars begin at midnight IST"
    assert stamps[0].strftime("%H:%M") == "00:00"
    assert all(s.date() == today for s in stamps)


def test_today_under_exchange_starts_at_the_open(monkeypatch):
    monkeypatch.setenv("PAPER_MARKET_HOURS", "exchange")
    now = datetime.now(inst.IST)
    df = _h().get_history("RELIANCE", "NSE", "15m", now.date().isoformat(), now.date().isoformat())
    stamps = _ist(df)
    if now.weekday() >= 5 or now.strftime("%H:%M") < "09:15":
        assert stamps == []
    else:
        assert stamps[0].strftime("%H:%M") == "09:15"
        assert all("09:15" <= s.strftime("%H:%M") <= "15:15" for s in stamps)


def test_history_never_runs_past_now():
    today = datetime.now(inst.IST).date()
    df = _h().get_history("RELIANCE", "NSE", "5m", today.isoformat(), (today + timedelta(days=3)).isoformat())
    now = datetime.now(UTC).timestamp()
    assert (df["timestamp"] <= now).all()


# -- derivatives ---------------------------------------------------------------


def _range_with_weekend_before(expiry: date):
    end = min(expiry, datetime.now(inst.IST).date()) - timedelta(days=1)
    start = end - timedelta(days=10)
    return start, end


@pytest.mark.parametrize("hours", HOURS)
def test_option_daily_history_has_no_weekends(monkeypatch, hours):
    monkeypatch.setenv("PAPER_MARKET_HOURS", hours)
    expiry = inst.monthly_expiries(1)[0]
    start, end = _range_with_weekend_before(expiry)
    symbol = inst.option_symbol("NIFTY", expiry, 26000, "CE")
    df = _h().get_history(symbol, "NFO", "D", start.isoformat(), end.isoformat())
    days = _utc_days(df)
    assert days and all(d.weekday() < 5 for d in days)
    assert (df["close"] >= 0.05).all() and (df["oi"] > 0).all()


@pytest.mark.parametrize("hours", HOURS)
def test_index_future_daily_history_has_no_weekends(monkeypatch, hours):
    monkeypatch.setenv("PAPER_MARKET_HOURS", hours)
    expiry = inst.monthly_expiries(1)[0]
    start, end = _range_with_weekend_before(expiry)
    symbol = inst.future_symbol("NIFTY", expiry)
    df = _h().get_history(symbol, "NFO", "D", start.isoformat(), end.isoformat())
    days = _utc_days(df)
    assert days and all(d.weekday() < 5 for d in days)


def test_option_intraday_of_a_past_day_is_session_only_and_setting_independent(monkeypatch):
    expiry = inst.monthly_expiries(1)[0]
    day = _past_weekday()
    symbol = inst.option_symbol("NIFTY", expiry, 26000, "PE")
    always = _h().get_history(symbol, "NFO", "15m", day.isoformat(), day.isoformat())
    assert len(always) == 25  # 09:15 to 15:15
    md.reset_state()
    monkeypatch.setenv("PAPER_MARKET_HOURS", "exchange")
    exchange = _h().get_history(symbol, "NFO", "15m", day.isoformat(), day.isoformat())
    pd.testing.assert_frame_equal(always, exchange)


# -- determinism, intervals, symbols --------------------------------------------


def test_history_is_deterministic():
    first = _h().get_history("INFY", "NSE", "D", "2023-06-01", "2023-08-31")
    md.reset_state()
    again = _h().get_history("INFY", "NSE", "D", "2023-06-01", "2023-08-31")
    pd.testing.assert_frame_equal(first, again)


@pytest.mark.parametrize("interval", ["W", "M", "1d", "2h", "7m", ""])
def test_unsupported_interval_is_refused_in_words(interval):
    with pytest.raises(PaperDataError, match="not available"):
        _h().get_history("RELIANCE", "NSE", interval, "2024-01-01", "2024-01-31")


def test_intervals_offered():
    assert _h().get_intervals() == ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "D"]


def test_bse_and_index_symbols_have_history():
    for symbol, exchange in (("RELIANCE", "BSE"), ("SENSEX", "BSE_INDEX"), ("BANKNIFTY", "NSE_INDEX")):
        df = _h().get_history(symbol, exchange, "D", "2024-01-01", "2024-01-31")
        assert len(df) == 23, f"{exchange}:{symbol}"
