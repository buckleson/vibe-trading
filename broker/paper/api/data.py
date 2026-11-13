"""Quotes, depth and candles of the paper broker (OpenAlgo's common data contract).

Prices come from ``broker.paper.api.market_data``: Yahoo Finance when it can be
reached, a deterministic simulated feed otherwise. ``data_source_status()``
says which one is in use, so a page can show it.
"""

from datetime import datetime, timedelta

import pandas as pd

from broker.paper.api import market_data
from broker.paper.database import instruments as inst
from utils.logging import get_logger

logger = get_logger(__name__)


def data_source_status(probe: bool = False) -> dict:
    """Whether market data is "live" (Yahoo Finance) or "simulated".

    See ``market_data.data_source_status`` for the fields.
    """
    return market_data.data_source_status(probe=probe)


class PaperDataError(Exception):
    """A market-data request the paper broker cannot answer."""


def _quote_fields(snap: dict) -> dict:
    return {
        "ask": snap["ask"],
        "bid": snap["bid"],
        "ask_qty": snap["ask_qty"],
        "bid_qty": snap["bid_qty"],
        "high": snap["high"],
        "low": snap["low"],
        "ltp": snap["ltp"],
        "open": snap["open"],
        "prev_close": snap["prev_close"],
        "volume": snap["volume"],
        "oi": snap["oi"],
    }


class BrokerData:
    """Market data handler with the same interface as every broker plugin."""

    #: Candle length in seconds per OpenAlgo interval.
    INTERVAL_SECONDS = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "10m": 600,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "D": 86400,
    }

    def __init__(self, auth_token):
        self.auth_token = auth_token
        # OpenAlgo interval -> what this plugin calls it (the candle length).
        self.timeframe_map = {key: str(value) for key, value in self.INTERVAL_SECONDS.items()}

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """Quote of one symbol: ltp, OHLC, previous close, volume, OI, best bid/ask."""
        try:
            return _quote_fields(market_data.snapshot(symbol, exchange))
        except Exception as exc:
            logger.exception(f"Paper quote failed for {exchange}:{symbol}")
            raise PaperDataError(f"No quote is available for {symbol} on {exchange}") from exc

    def get_multiquotes(self, symbols: list) -> list:
        """Quotes of many symbols: ``[{"symbol", "exchange", "data"}]``."""
        results = []
        for item in symbols:
            symbol, exchange = item.get("symbol"), item.get("exchange")
            try:
                data = _quote_fields(market_data.snapshot(symbol, exchange))
                results.append({"symbol": symbol, "exchange": exchange, "data": data})
            except Exception:
                logger.exception(f"Paper multiquote failed for {exchange}:{symbol}")
                results.append(
                    {"symbol": symbol, "exchange": exchange, "error": "No quote is available"}
                )
        return results

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """Five-level market depth."""
        try:
            snap = market_data.snapshot(symbol, exchange)
            bids, asks = market_data.depth_levels(symbol, exchange, snap)
        except Exception as exc:
            logger.exception(f"Paper depth failed for {exchange}:{symbol}")
            raise PaperDataError(f"No market depth is available for {symbol} on {exchange}") from exc
        return {
            "asks": [{"price": a["price"], "quantity": a["quantity"]} for a in asks],
            "bids": [{"price": b["price"], "quantity": b["quantity"]} for b in bids],
            "high": snap["high"],
            "low": snap["low"],
            "ltp": snap["ltp"],
            "ltq": snap["lotsize"] if snap["kind"] != "index" else 0,
            "oi": snap["oi"],
            "open": snap["open"],
            "prev_close": snap["prev_close"],
            "totalbuyqty": sum(b["quantity"] for b in bids),
            "totalsellqty": sum(a["quantity"] for a in asks),
            "volume": snap["volume"],
        }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias of get_market_depth, the name the depth service calls."""
        return self.get_market_depth(symbol, exchange)

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Candles between two dates (inclusive, YYYY-MM-DD).

        Returns:
            pd.DataFrame: timestamp (epoch seconds; daily bars at 00:00 UTC of
            their date, as the other plugins return them), open, high, low,
            close, volume, oi.
        """
        seconds = self.INTERVAL_SECONDS.get(interval)
        if not seconds:
            raise PaperDataError(
                f"The {interval} interval is not available. "
                f"Use one of: {', '.join(self.INTERVAL_SECONDS)}"
            )
        start = _parse_day(start_date)
        end = _parse_day(end_date)
        if end < start:
            return pd.DataFrame(columns=market_data.HISTORY_COLUMNS)
        try:
            return market_data.history(symbol, exchange, seconds, start, end)
        except Exception as exc:
            logger.exception(f"Paper history failed for {exchange}:{symbol}")
            raise PaperDataError(f"No history is available for {symbol} on {exchange}") from exc

    def get_intervals(self) -> list:
        """The intervals get_history accepts."""
        return list(self.INTERVAL_SECONDS)


def _parse_day(value) -> datetime:
    """A date (string, date or datetime) as IST midnight of that day."""
    if isinstance(value, datetime):
        day = value.date()
    elif hasattr(value, "year") and hasattr(value, "month"):
        day = value
    else:
        day = pd.to_datetime(str(value)).date()
    return inst.IST.localize(datetime(day.year, day.month, day.day)) + timedelta(0)
