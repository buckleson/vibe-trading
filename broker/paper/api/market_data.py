"""Market data for the paper broker: Yahoo Finance when reachable, else simulated.

Two sources, chosen per call:

- **Yahoo Finance (live, delayed by the exchange feed Yahoo carries).** Equity
  and index quotes and candles are read from Yahoo's public chart endpoint
  through the shared pooled HTTP client (``utils.httpx_client``) with a short
  timeout. The yfinance package reads the same endpoint, but it is only in the
  optional ``analysis`` dependency group and its curl transport waits inside C
  code, which would stall the eventlet worker; the shared client does neither.
- **Simulated.** A deterministic feed: every symbol's log price is a sum of
  smooth value-noise octaves (from a year down to a few seconds) seeded by the
  symbol name and evaluated on the wall clock, so prices move second by second,
  every process sees the same price at the same moment, and candles are
  consistent with the quotes.

Futures are priced at cost of carry off the underlying, and options with
Black-Scholes off the underlying (live or simulated) with a volatility smile.

``PAPER_DATA_SOURCE`` (read at call time) picks the source: ``auto`` (default:
Yahoo, falling back to simulated while Yahoo is unreachable), ``simulated`` or
``yahoo`` (Yahoo only, still falling back per symbol it does not carry).

``PAPER_MARKET_HOURS`` picks when the simulated market trades: ``always``
(default: prices move around the clock, every day, so Sandbox mode can be
exercised at any hour, and candles cover the whole day) or ``exchange``
(prices move only from 09:15 to 15:30 IST on weekdays and hold the last
price in between, and candles follow that session). Exchange holidays are not
modelled.
"""

import math
import os
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from broker.paper.database import instruments as inst
from utils.logging import get_logger
from utils.real_threading import Lock
from utils.thread_safe_cache import MISSING, LockedTTLCache

logger = get_logger(__name__)

SOURCE_LIVE = "live"
SOURCE_SIMULATED = "simulated"

RISK_FREE_RATE = 0.065
YEAR_SECONDS = 365.0 * 86400.0
SESSION_OPEN = (9, 15)
SESSION_SECONDS = 22500  # 09:15 to 15:30

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_TIMEOUT = 3.0
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
#: How long a failed reach of Yahoo keeps every call on the simulated feed.
YAHOO_RETRY_SECONDS = 300

# (period in seconds, amplitude of log price). Value noise in [-1, 1] per
# octave; the sum keeps a symbol within roughly +-10% of its reference.
_OCTAVES = (
    (365 * 86400, 0.030),
    (90 * 86400, 0.025),
    (20 * 86400, 0.020),
    (5 * 86400, 0.012),
    (86400, 0.007),
    (7200, 0.0030),
    (900, 0.0015),
    (120, 0.0006),
    (15, 0.00025),
    (3, 0.00010),
)

_quote_cache = LockedTTLCache(maxsize=2048, ttl=15)
_history_cache = LockedTTLCache(maxsize=256, ttl=60)
_status_lock = Lock()
_status = {
    "yahoo_down_until": 0.0,
    "last_live_at": None,
    "last_error": None,
    "last_source": None,
}


# ---------------------------------------------------------------------------
# Deterministic noise
# ---------------------------------------------------------------------------

_M1 = np.uint64(0x9E3779B97F4A7C15)
_M2 = np.uint64(0xBF58476D1CE4E5B9)
_M3 = np.uint64(0x94D049BB133111EB)


def _mix(x: np.ndarray) -> np.ndarray:
    """splitmix64 finaliser over a uint64 array (wraps on overflow by design)."""
    with np.errstate(over="ignore"):
        x = x + _M1
        x = (x ^ (x >> np.uint64(30))) * _M2
        x = (x ^ (x >> np.uint64(27))) * _M3
        return x ^ (x >> np.uint64(31))


def _uniform(seed: int, octave: int, bucket: np.ndarray) -> np.ndarray:
    """A uniform value in [-1, 1) for each (seed, octave, bucket)."""
    key = np.uint64((seed * 1_000_003 + octave * 7919) & 0xFFFFFFFFFFFFFFFF)
    with np.errstate(over="ignore"):
        mixed = _mix(bucket.astype(np.int64).view(np.uint64) * _M2 ^ key)
    return (mixed >> np.uint64(11)).astype(np.float64) * (2.0 / 9007199254740992.0) - 1.0


def _noise(seed: int, times: np.ndarray, octaves=_OCTAVES) -> np.ndarray:
    """Sum of smoothly interpolated value noise at each epoch second in ``times``."""
    total = np.zeros_like(times, dtype=np.float64)
    for index, (period, amplitude) in enumerate(octaves):
        scaled = times / period
        bucket = np.floor(scaled)
        frac = scaled - bucket
        frac = frac * frac * (3.0 - 2.0 * frac)
        v0 = _uniform(seed, index, bucket)
        v1 = _uniform(seed, index, bucket + 1)
        total += amplitude * (v0 + (v1 - v0) * frac)
    return total


def _volatility_multiplier(symbol: str, exchange: str) -> float:
    if symbol == "INDIAVIX":
        return 4.0
    if exchange in ("NSE_INDEX", "BSE_INDEX"):
        return 0.8
    return 1.0 + (inst.stable_hash(symbol + "|vol") % 60) / 100.0


def _seed(symbol: str) -> int:
    # NSE and BSE listings of one company share a seed so they agree.
    return inst.stable_hash(symbol)


def _sim_prices(symbol: str, exchange: str, reference: float, times) -> np.ndarray:
    """Simulated prices of a spot instrument (equity or index) at ``times``."""
    times = np.atleast_1d(np.asarray(times, dtype=np.float64))
    offset = _noise(_seed(symbol), times) * _volatility_multiplier(symbol, exchange)
    prices = reference * np.exp(offset)
    if exchange == "BSE":
        # A BSE quote sits a tick or two away from NSE.
        prices = prices * (1.0 + 0.0002 * _uniform(_seed(symbol) + 1, 99, np.floor(times / 5)))
    return prices


# ---------------------------------------------------------------------------
# Black-Scholes
# ---------------------------------------------------------------------------

_erf = np.frompyfunc(math.erf, 1, 1)


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=np.float64) / math.sqrt(2.0)).astype(np.float64))


def implied_vol(underlying: str, spot, strike, years) -> np.ndarray:
    """The simulator's volatility for a strike: a skewed smile around the ATM level."""
    base = inst.underlying_iv(underlying)
    moneyness = np.log(np.asarray(strike, dtype=np.float64) / np.asarray(spot, dtype=np.float64))
    scale = np.sqrt(np.maximum(np.asarray(years, dtype=np.float64), 1.0 / 365.0) * 12.0)
    m = moneyness / np.maximum(scale, 0.05)
    vol = base * (1.0 - 0.35 * m + 2.0 * m * m)
    return np.clip(vol, base * 0.6, base * 4.0)


def black_scholes(spot, strike, years, vol, kind: str, rate: float = RISK_FREE_RATE) -> np.ndarray:
    """European option value; intrinsic value at or past expiry."""
    spot = np.asarray(spot, dtype=np.float64)
    strike = np.asarray(strike, dtype=np.float64)
    years = np.maximum(np.asarray(years, dtype=np.float64), 0.0)
    vol = np.asarray(vol, dtype=np.float64)
    intrinsic = np.maximum(spot - strike, 0.0) if kind == "CE" else np.maximum(strike - spot, 0.0)
    live = years > 1e-9
    safe_years = np.where(live, years, 1.0)
    root = vol * np.sqrt(safe_years)
    d1 = (np.log(spot / strike) + (rate + 0.5 * vol * vol) * safe_years) / root
    d2 = d1 - root
    discount = np.exp(-rate * safe_years)
    if kind == "CE":
        value = spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
    else:
        value = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return np.where(live, np.maximum(value, intrinsic * discount), intrinsic)


def _round_tick(value: float, tick: float) -> float:
    return round(round(float(value) / tick) * tick, 2)


# ---------------------------------------------------------------------------
# Yahoo Finance
# ---------------------------------------------------------------------------


def _source_setting() -> str:
    value = (os.getenv("PAPER_DATA_SOURCE") or "auto").strip().lower()
    return value if value in ("auto", "simulated", "yahoo") else "auto"


def yahoo_ticker(symbol: str, exchange: str) -> str | None:
    """The Yahoo ticker of an equity or index, None for derivatives."""
    if exchange in ("NSE_INDEX", "BSE_INDEX"):
        entry = inst.INDICES.get(symbol)
        return entry[3] if entry else None
    if exchange == "NSE":
        return f"{symbol}.NS"
    if exchange == "BSE":
        return f"{symbol}.BO"
    return None


def _yahoo_allowed() -> bool:
    if _source_setting() == "simulated":
        return False
    with _status_lock:
        return time.time() >= _status["yahoo_down_until"]


def _mark_yahoo_down(reason: str) -> None:
    with _status_lock:
        first = _status["yahoo_down_until"] <= time.time()
        _status["yahoo_down_until"] = time.time() + YAHOO_RETRY_SECONDS
        _status["last_error"] = reason
    if first:
        logger.info(
            "Yahoo Finance is not reachable (%s); using simulated market data for the next %s s",
            reason,
            YAHOO_RETRY_SECONDS,
        )


def _mark_yahoo_up() -> None:
    with _status_lock:
        _status["yahoo_down_until"] = 0.0
        _status["last_live_at"] = time.time()
        _status["last_error"] = None


def _yahoo_chart(ticker: str, params: dict) -> dict | None:
    """One chart response, or None. Marks Yahoo down on a transport failure."""
    if not _yahoo_allowed():
        return None
    from utils.httpx_client import get_httpx_client

    try:
        response = get_httpx_client().get(
            YAHOO_CHART_URL.format(ticker=ticker),
            params=params,
            headers=YAHOO_HEADERS,
            timeout=YAHOO_TIMEOUT,
        )
    except Exception as exc:
        _mark_yahoo_down(type(exc).__name__)
        return None
    if response.status_code == 404:
        return None  # Yahoo does not carry this ticker: this symbol only.
    if response.status_code != 200:
        _mark_yahoo_down(f"HTTP {response.status_code}")
        return None
    try:
        payload = response.json()
        result = (payload.get("chart") or {}).get("result") or []
    except ValueError:
        _mark_yahoo_down("unreadable reply")
        return None
    if not result:
        return None
    _mark_yahoo_up()
    return result[0]


def _yahoo_quote(symbol: str, exchange: str) -> dict | None:
    ticker = yahoo_ticker(symbol, exchange)
    if not ticker:
        return None

    def load():
        chart = _yahoo_chart(ticker, {"range": "1d", "interval": "5m"})
        if not chart:
            return None
        meta = chart.get("meta") or {}
        ltp = meta.get("regularMarketPrice")
        if not ltp:
            return None
        quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
        opens = [v for v in (quote.get("open") or []) if v is not None]
        highs = [v for v in (quote.get("high") or []) if v is not None]
        lows = [v for v in (quote.get("low") or []) if v is not None]
        volumes = [v for v in (quote.get("volume") or []) if v is not None]
        prev = meta.get("chartPreviousClose") or meta.get("previousClose") or ltp
        return {
            "ltp": float(ltp),
            "open": float(opens[0]) if opens else float(ltp),
            "high": float(meta.get("regularMarketDayHigh") or (max(highs) if highs else ltp)),
            "low": float(meta.get("regularMarketDayLow") or (min(lows) if lows else ltp)),
            "prev_close": float(prev),
            "volume": int(meta.get("regularMarketVolume") or sum(volumes)),
        }

    key = ("yq", symbol, exchange)
    value = _quote_cache.get(key, MISSING)
    if value is not MISSING:
        return value
    value = load()
    if value is not None:
        _quote_cache[key] = value
    return value


_YAHOO_INTERVALS = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "60m", 86400: "1d"}
# How far back Yahoo serves each interval.
_YAHOO_LOOKBACK_DAYS = {60: 7, 300: 59, 900: 59, 1800: 59, 3600: 729, 86400: 36500}


def _yahoo_history(symbol, exchange, seconds, start: datetime, end: datetime) -> pd.DataFrame | None:
    ticker = yahoo_ticker(symbol, exchange)
    if not ticker:
        return None
    native = seconds if seconds in _YAHOO_INTERVALS else (60 if seconds < 300 else 300)
    if seconds % native:
        return None
    oldest = datetime.now(UTC) - timedelta(days=_YAHOO_LOOKBACK_DAYS[native])
    if start < oldest:
        return None
    chart = _yahoo_chart(
        ticker,
        {
            "period1": int(start.timestamp()),
            "period2": int((end + timedelta(days=1)).timestamp()),
            "interval": _YAHOO_INTERVALS[native],
        },
    )
    if not chart or not chart.get("timestamp"):
        return None
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    df = pd.DataFrame(
        {
            "timestamp": chart["timestamp"],
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        }
    ).dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return None
    df["volume"] = df["volume"].fillna(0)
    if native == 86400:
        # Daily bars at 00:00 UTC of their date, as the other plugins return them.
        days = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(inst.IST).dt.date
        df["timestamp"] = [int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) for d in days]
    if native != seconds:
        df = _resample(df, seconds)
    return df


def _resample(df: pd.DataFrame, seconds: int) -> pd.DataFrame:
    """Aggregate candles into ``seconds`` buckets anchored at the 09:15 IST session open."""
    anchor = 9 * 3600 + 15 * 60 - 19800  # 09:15 IST in seconds after UTC midnight
    group = (df["timestamp"] - anchor) // seconds * seconds + anchor
    out = df.groupby(group).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    out.index.name = "timestamp"
    return out.reset_index()


# ---------------------------------------------------------------------------
# Instruments and sessions
# ---------------------------------------------------------------------------


def classify(symbol: str, exchange: str):
    """("index"|"equity"|"future"|"option", details) for an OpenAlgo symbol."""
    if exchange in ("NSE_INDEX", "BSE_INDEX"):
        return "index", {"reference": inst.index_reference(symbol)}
    if exchange in ("NFO", "BFO"):
        option = inst.parse_option(symbol)
        if option:
            underlying, expiry, strike, kind = option
            return "option", {
                "underlying": underlying,
                "expiry": expiry,
                "strike": strike,
                "kind": kind,
            }
        future = inst.parse_future(symbol)
        if future:
            return "future", {"underlying": future[0], "expiry": future[1]}
    return "equity", {"reference": inst.equity_reference(symbol)}


def _hours_setting() -> str:
    value = (os.getenv("PAPER_MARKET_HOURS") or "always").strip().lower()
    return value if value in ("always", "exchange") else "always"


def _session(day) -> tuple[float, float] | None:
    """(open, close) epoch seconds of a day's simulated session, None if it does not trade."""
    if _hours_setting() == "always":
        opening = inst.IST.localize(datetime(day.year, day.month, day.day)).timestamp()
        return opening, opening + 86400.0
    if day.weekday() >= 5:
        return None
    opening = inst.IST.localize(datetime(day.year, day.month, day.day, *SESSION_OPEN)).timestamp()
    return opening, opening + SESSION_SECONDS


def _previous_session(day):
    for back in range(1, 8):
        earlier = day - timedelta(days=back)
        bounds = _session(earlier)
        if bounds:
            return bounds
    return None


def market_time(now: float) -> float:
    """The moment the simulated market shows at ``now``: ``now`` while it trades,
    else the close of the last session."""
    day = datetime.fromtimestamp(now, inst.IST).date()
    bounds = _session(day)
    if bounds and bounds[0] <= now:
        return min(now, bounds[1])
    previous = _previous_session(day)
    return previous[1] if previous else now


def _day_window(now: float) -> tuple[float, float, float]:
    """(open, close, previous close) of the session ``now`` belongs to, epoch seconds."""
    shown = market_time(now)
    day = datetime.fromtimestamp(shown - 1e-6, inst.IST).date()
    bounds = _session(day) or (shown, shown)
    previous = _previous_session(day)
    return bounds[0], bounds[1], previous[1] if previous else bounds[0]


def _years_to_expiry(expiry, times) -> np.ndarray:
    expires = inst.expiry_datetime(expiry).timestamp()
    return np.maximum(expires - np.atleast_1d(np.asarray(times, dtype=np.float64)), 0.0) / YEAR_SECONDS


# ---------------------------------------------------------------------------
# Spot prices
# ---------------------------------------------------------------------------


def _spot_snapshot(symbol: str, exchange: str, now: float) -> tuple[dict, str]:
    """Day statistics of an equity or index, and the source they came from."""
    live = _yahoo_quote(symbol, exchange) if _yahoo_allowed() else None
    if live:
        return live, SOURCE_LIVE
    reference = (
        inst.index_reference(symbol)
        if exchange in ("NSE_INDEX", "BSE_INDEX")
        else inst.equity_reference(symbol)
    )
    opening, closing, previous_close = _day_window(now)
    shown = market_time(now)
    samples = np.append(np.arange(opening, shown, 300.0), shown)
    prices = _sim_prices(symbol, exchange, reference, samples)
    prev = float(_sim_prices(symbol, exchange, reference, [previous_close])[0])
    return (
        {
            "ltp": float(prices[-1]),
            "open": float(prices[0]),
            "high": float(prices.max()),
            "low": float(prices.min()),
            "prev_close": prev,
            "volume": _day_volume(symbol, exchange, opening, closing, shown),
        },
        SOURCE_SIMULATED,
    )


def _day_volume(symbol: str, exchange: str, opening: float, closing: float, now: float) -> int:
    if exchange in ("NSE_INDEX", "BSE_INDEX"):
        return 0
    base = inst.EQUITIES.get(symbol, (None, None, 1_000_000))[2]
    if exchange == "BSE":
        base *= 0.08
    length = max(closing - opening, 1.0)
    elapsed = min(max(now - opening, 0.0), length) / length
    day_factor = 0.7 + 0.6 * (inst.stable_hash(f"{symbol}|{int(opening)}") % 1000) / 1000.0
    return int(base * day_factor * elapsed)


def underlying_spot(underlying: str, now: float | None = None) -> tuple[float, str]:
    """The current price of a derivative's underlying, and its source."""
    now = time.time() if now is None else now
    snapshot, source = _spot_snapshot(underlying, inst.underlying_exchange(underlying), now)
    return snapshot["ltp"], source


# ---------------------------------------------------------------------------
# Quotes and depth
# ---------------------------------------------------------------------------


def _derivative_activity(kind: str, details: dict, symbol: str, spot) -> tuple[np.ndarray, np.ndarray]:
    """(full-day volume, open interest) in units, for the underlying at ``spot``.

    Futures carry a steady book; options peak at the money and thin out with
    distance, as a real chain does.
    """
    spot = np.atleast_1d(np.asarray(spot, dtype=np.float64))
    lotsize = inst.INDEX_DERIVATIVES.get(details["underlying"], {}).get("lotsize", 1)
    jitter = 0.6 + 0.8 * (inst.stable_hash(symbol) % 1000) / 1000.0
    if kind == "future":
        oi = lotsize * (150_000 + inst.stable_hash(symbol) % 100_000) * np.ones_like(spot)
        volume = lotsize * (20_000 + inst.stable_hash(f"{symbol}|v") % 20_000) * np.ones_like(spot)
        return volume, oi
    distance = (details["strike"] - spot) / np.maximum(spot * 0.02, 1.0)
    shape = np.exp(-0.5 * distance * distance)
    oi = lotsize * (2_000 + 120_000 * shape) * jitter
    volume = lotsize * (5_000 + 900_000 * shape) * jitter
    return volume, oi


def _derivative_snapshot(kind: str, details: dict, symbol: str, now: float) -> tuple[dict, str]:
    underlying = details["underlying"]
    exchange = inst.underlying_exchange(underlying)
    spot_day, source = _spot_snapshot(underlying, exchange, now)
    opening, _closing, previous_close = _day_window(now)
    now = market_time(now) if source == SOURCE_SIMULATED else now
    expiry = details["expiry"]
    points = {
        "ltp": (spot_day["ltp"], now),
        "open": (spot_day["open"], opening),
        "high": (spot_day["high"], now),
        "low": (spot_day["low"], now),
        "prev_close": (spot_day["prev_close"], previous_close),
    }
    values = {}
    if kind == "future":
        for field, (spot, at) in points.items():
            years = float(_years_to_expiry(expiry, at)[0])
            values[field] = spot * math.exp(RISK_FREE_RATE * years)
    else:
        strike, option_kind = details["strike"], details["kind"]
        for field, (spot, at) in points.items():
            years = _years_to_expiry(expiry, at)
            vol = implied_vol(underlying, spot, strike, years)
            values[field] = float(black_scholes(spot, strike, years, vol, option_kind)[0])
        if option_kind == "PE":
            # A put's high comes with the underlying's low and the other way round.
            spot_high, spot_low = spot_day["high"], spot_day["low"]
            years = _years_to_expiry(expiry, now)
            values["high"] = float(
                black_scholes(spot_low, strike, years, implied_vol(underlying, spot_low, strike, years), "PE")[0]
            )
            values["low"] = float(
                black_scholes(spot_high, strike, years, implied_vol(underlying, spot_high, strike, years), "PE")[0]
            )
    day_volume, oi = _derivative_activity(kind, details, symbol, spot_day["ltp"])
    opening, closing, _previous = _day_window(now)
    elapsed = min(max(now - opening, 0.0), closing - opening) / max(closing - opening, 1.0)
    values["oi"] = int(oi[0])
    values["volume"] = int(day_volume[0] * elapsed)
    values["high"] = max(values["high"], values["ltp"], values["open"])
    values["low"] = min(values["low"], values["ltp"], values["open"])
    return values, source


def _tick_for(kind: str, symbol: str, price: float) -> float:
    if kind == "future":
        return 0.10
    if kind == "option":
        return 0.05
    return inst.tick_size_for(price)


def snapshot(symbol: str, exchange: str, now: float | None = None) -> dict:
    """Full quote of any paper instrument, rounded to its tick.

    Returns:
        dict: ltp, open, high, low, prev_close, volume, oi, bid, ask, bid_qty,
        ask_qty, tick, lotsize, source.
    """
    now = time.time() if now is None else now
    kind, details = classify(symbol, exchange)
    if kind in ("future", "option"):
        values, source = _derivative_snapshot(kind, details, symbol, now)
        lotsize = inst.INDEX_DERIVATIVES.get(details["underlying"], {}).get("lotsize", 1)
    else:
        values, source = _spot_snapshot(symbol, exchange, now)
        values = dict(values)
        values["oi"] = 0
        lotsize = 1
    tick = _tick_for(kind, symbol, values["ltp"])
    floor = tick if kind == "option" else 0.0
    for field in ("ltp", "open", "high", "low", "prev_close"):
        values[field] = max(_round_tick(values[field], tick), floor)

    if kind == "index":
        bid = ask = 0.0
        bid_qty = ask_qty = 0
    else:
        ltp = values["ltp"]
        half = max(tick, _round_tick(ltp * 0.00015, tick))
        bid = max(_round_tick(ltp - half, tick), floor)
        ask = _round_tick(ltp + half, tick)
        if ask <= bid:
            ask = round(bid + tick, 2)
        size = lotsize if lotsize > 1 else 1
        second = int(now)
        bid_qty = size * (1 + inst.stable_hash(f"{symbol}|b|{second}") % 40)
        ask_qty = size * (1 + inst.stable_hash(f"{symbol}|a|{second}") % 40)
    values.update(
        {
            "bid": bid,
            "ask": ask,
            "bid_qty": int(bid_qty),
            "ask_qty": int(ask_qty),
            "tick": tick,
            "lotsize": lotsize,
            "source": source,
            "kind": kind,
        }
    )
    with _status_lock:
        _status["last_source"] = source
    return values


def depth_levels(symbol: str, exchange: str, snap: dict, levels: int = 5, now: float | None = None):
    """Five bid and ask levels around a snapshot's best bid and ask."""
    now = time.time() if now is None else now
    if snap["kind"] == "index":
        empty = [{"price": 0, "quantity": 0, "orders": 0} for _ in range(levels)]
        return empty, [dict(level) for level in empty]
    tick = snap["tick"]
    size = snap["lotsize"] if snap["lotsize"] > 1 else 1
    second = int(now)
    bids, asks = [], []
    for level in range(levels):
        bid_price = snap["bid"] - level * tick
        ask_price = snap["ask"] + level * tick
        bid_qty = snap["bid_qty"] if level == 0 else size * (1 + inst.stable_hash(f"{symbol}|B{level}|{second}") % 80)
        ask_qty = snap["ask_qty"] if level == 0 else size * (1 + inst.stable_hash(f"{symbol}|A{level}|{second}") % 80)
        bids.append(
            {
                "price": round(max(bid_price, 0.0), 2),
                "quantity": int(bid_qty),
                "orders": 1 + inst.stable_hash(f"{symbol}|bo{level}|{second}") % 25,
            }
        )
        asks.append(
            {
                "price": round(ask_price, 2),
                "quantity": int(ask_qty),
                "orders": 1 + inst.stable_hash(f"{symbol}|ao{level}|{second}") % 25,
            }
        )
    return bids, asks


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


def _session_starts(start: datetime, end: datetime, seconds: int, now: float) -> np.ndarray:
    """Candle start times (epoch seconds) of every weekday session in [start, end]."""
    starts = []
    day = start.date()
    last = end.date()
    while day <= last:
        bounds = _session(day)
        if bounds:
            stamps = np.arange(bounds[0], bounds[1], seconds, dtype=np.float64)
            starts.append(stamps[stamps <= now])
        day += timedelta(days=1)
    return np.concatenate(starts) if starts else np.array([], dtype=np.float64)


def _sim_spot_history(symbol, exchange, reference, seconds, start, end, now) -> pd.DataFrame:
    if seconds >= 86400:
        rows = []
        for d in pd.date_range(start.date(), end.date(), freq="D"):
            bounds = _session(d.date())
            if not bounds or bounds[0] > now:
                continue
            opening, closing = bounds
            last = min(closing, now)
            samples = np.append(np.arange(opening, last, 900.0), last)
            prices = _sim_prices(symbol, exchange, reference, samples)
            rows.append(
                {
                    "timestamp": int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()),
                    "open": prices[0],
                    "high": prices.max(),
                    "low": prices.min(),
                    "close": prices[-1],
                    "volume": _day_volume(symbol, exchange, opening, closing, last),
                }
            )
        return pd.DataFrame(rows, columns=HISTORY_COLUMNS[:-1])

    starts = _session_starts(start, end, seconds, now)
    if starts.size == 0:
        return pd.DataFrame(columns=HISTORY_COLUMNS[:-1])
    fractions = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    grid = starts[:, None] + fractions[None, :] * (seconds - 1)
    grid = np.minimum(grid, now)
    prices = _sim_prices(symbol, exchange, reference, grid.ravel()).reshape(grid.shape)
    base = inst.EQUITIES.get(symbol, (None, None, 1_000_000))[2]
    if exchange in ("NSE_INDEX", "BSE_INDEX"):
        volume = np.zeros(starts.size)
    else:
        noise = (_uniform(_seed(symbol), 77, starts) + 1.0) / 2.0
        day_length = 86400.0 if _hours_setting() == "always" else SESSION_SECONDS
        volume = base * seconds / day_length * (0.4 + 1.2 * noise)
    return pd.DataFrame(
        {
            "timestamp": starts.astype(np.int64),
            "open": prices[:, 0],
            "high": prices.max(axis=1),
            "low": prices.min(axis=1),
            "close": prices[:, -1],
            "volume": volume,
        }
    )


def _spot_history(symbol, exchange, seconds, start, end, now) -> tuple[pd.DataFrame, str]:
    if _yahoo_allowed():
        live = _yahoo_history(symbol, exchange, seconds, start, end)
        if live is not None and not live.empty:
            return live, SOURCE_LIVE
    reference = (
        inst.index_reference(symbol)
        if exchange in ("NSE_INDEX", "BSE_INDEX")
        else inst.equity_reference(symbol)
    )
    return _sim_spot_history(symbol, exchange, reference, seconds, start, end, now), SOURCE_SIMULATED


def history(symbol: str, exchange: str, seconds: int, start: datetime, end: datetime) -> pd.DataFrame:
    """Candles with the OpenAlgo history columns, epoch-second timestamps.

    Args:
        symbol: OpenAlgo symbol.
        exchange: OpenAlgo exchange.
        seconds: Candle length in seconds (86400 for daily).
        start: First day (IST), inclusive.
        end: Last day (IST), inclusive.
    """
    now = time.time()
    key = (symbol, exchange, seconds, start.isoformat(), end.isoformat(), int(now // 30))
    cached = _history_cache.get(key, MISSING)
    if cached is not MISSING:
        return cached.copy()

    kind, details = classify(symbol, exchange)
    if kind in ("future", "option"):
        underlying = details["underlying"]
        expiry = details["expiry"]
        expires = inst.expiry_datetime(expiry).timestamp()
        end = min(end, datetime.fromtimestamp(expires, inst.IST))
        base, _source = _spot_history(underlying, inst.underlying_exchange(underlying), seconds, start, end, now)
        if base.empty:
            df = base
        else:
            base = base.copy()
            stamp = base["timestamp"].to_numpy(dtype=np.float64)
            # Daily bars carry a 00:00 UTC stamp; price them at that day's 15:30 IST close.
            at = stamp + (10 * 3600 if seconds >= 86400 else seconds)
            at = np.minimum(at, now)
            years = _years_to_expiry(expiry, at)
            day_volume, oi = _derivative_activity(
                kind, details, symbol, base["close"].to_numpy(dtype=np.float64)
            )
            day_length = 86400.0 if _hours_setting() == "always" else SESSION_SECONDS
            share = 1.0 if seconds >= 86400 else seconds / day_length
            noise = 0.4 + 0.6 * (_uniform(_seed(symbol), 5, stamp) + 1.0)
            if kind == "future":
                carry = np.exp(RISK_FREE_RATE * years)
                for column in ("open", "high", "low", "close"):
                    base[column] = base[column].to_numpy(dtype=np.float64) * carry
            else:
                strike, option_kind = details["strike"], details["kind"]

                def price(column):
                    spot = base[column].to_numpy(dtype=np.float64)
                    vol = implied_vol(underlying, spot, strike, years)
                    return black_scholes(spot, strike, years, vol, option_kind)

                opens, closes = price("open"), price("close")
                from_high, from_low = price("high"), price("low")
                highs = np.maximum.reduce([opens, closes, from_high, from_low])
                lows = np.minimum.reduce([opens, closes, from_high, from_low])
                base["open"], base["close"], base["high"], base["low"] = opens, closes, highs, lows
            base["volume"] = day_volume * share * noise
            base["oi"] = oi
            df = base[base["timestamp"] <= expires]
        tick = _tick_for(kind, symbol, 1.0)
    else:
        df, _source = _spot_history(symbol, exchange, seconds, start, end, now)
        df = df.copy()
        df["oi"] = 0
        tick = inst.tick_size_for(float(df["close"].iloc[-1])) if not df.empty else 0.05

    if df.empty:
        df = pd.DataFrame(columns=HISTORY_COLUMNS)
    else:
        floor = tick if kind == "option" else 0.0
        for column in ("open", "high", "low", "close"):
            df[column] = np.maximum(np.round(df[column].astype(float) / tick) * tick, floor).round(2)
        df["timestamp"] = df["timestamp"].astype(np.int64)
        df["volume"] = df["volume"].astype(float).round().astype(np.int64)
        df["oi"] = df["oi"].astype(float).round().astype(np.int64)
        df = df[HISTORY_COLUMNS].sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    _history_cache[key] = df
    return df.copy()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def data_source_status(probe: bool = False) -> dict:
    """Whether quotes come from Yahoo Finance ("live") or the simulator.

    Args:
        probe: Ask Yahoo now (one short request) instead of reporting the last
            known state.

    Returns:
        dict: ``source`` ("live" or "simulated"), ``provider``, ``setting``,
        ``message`` for a trader, ``last_live_at`` and ``retry_at`` (epoch
        seconds or None).
    """
    setting = _source_setting()
    if probe and setting != "simulated":
        with _status_lock:
            _status["yahoo_down_until"] = 0.0
        _yahoo_quote("NIFTY", "NSE_INDEX")
    with _status_lock:
        down_until = _status["yahoo_down_until"]
        last_live = _status["last_live_at"]
        last_source = _status["last_source"]
    now = time.time()
    if setting == "simulated":
        live = False
        message = "Simulated market data: prices are generated, not taken from the exchange."
    elif down_until > now:
        live = False
        message = (
            "Simulated market data: Yahoo Finance cannot be reached from this server, "
            "so prices are generated. Buckleson tries Yahoo again every few minutes."
        )
    elif last_live is not None and last_source != SOURCE_SIMULATED:
        live = True
        message = "Delayed market data from Yahoo Finance."
    else:
        live = False
        message = "Simulated market data until Yahoo Finance answers."
    return {
        "source": SOURCE_LIVE if live else SOURCE_SIMULATED,
        "provider": "Yahoo Finance" if live else "Simulator",
        "setting": setting,
        "message": message,
        "last_live_at": last_live,
        "retry_at": down_until if down_until > now else None,
    }


def reset_state() -> None:
    """Forget the cached quotes and Yahoo's state (tests)."""
    _quote_cache.clear()
    _history_cache.clear()
    with _status_lock:
        _status.update(
            {"yahoo_down_until": 0.0, "last_live_at": None, "last_error": None, "last_source": None}
        )
