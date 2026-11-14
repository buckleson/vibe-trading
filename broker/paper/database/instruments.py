"""The bundled instrument universe of the paper broker, built with no network.

Everything the master contract holds is derived here from constants and
today's date: NIFTY 50 and other liquid NSE equities (also listed on BSE), the
main NSE and BSE indices, near-month index futures, and NIFTY / BANKNIFTY
option chains with strikes around the current underlying price.

Reference prices are approximate levels used to seed the simulated feed and to
centre the option strikes when no live price is available. Nothing in this
module touches the database or the network, so the market-data simulator and
the tests use it directly.
"""

import calendar
import re
import zlib
from datetime import date, datetime, time, timedelta

import pytz

IST = pytz.timezone("Asia/Kolkata")

#: Index options and futures stop trading at this IST time on expiry day.
EXPIRY_CUTOFF = time(15, 30)

# symbol: (company name, reference price, base daily volume)
EQUITIES = {
    "ADANIENT": ("Adani Enterprises", 2400.0, 1_500_000),
    "ADANIPORTS": ("Adani Ports and SEZ", 1450.0, 2_500_000),
    "APOLLOHOSP": ("Apollo Hospitals", 7600.0, 400_000),
    "ASIANPAINT": ("Asian Paints", 2900.0, 1_200_000),
    "AXISBANK": ("Axis Bank", 1230.0, 7_000_000),
    "BAJAJ-AUTO": ("Bajaj Auto", 8900.0, 400_000),
    "BAJFINANCE": ("Bajaj Finance", 1020.0, 6_000_000),
    "BAJAJFINSV": ("Bajaj Finserv", 2050.0, 1_200_000),
    "BEL": ("Bharat Electronics", 420.0, 18_000_000),
    "BHARTIARTL": ("Bharti Airtel", 2100.0, 6_000_000),
    "CIPLA": ("Cipla", 1520.0, 1_800_000),
    "COALINDIA": ("Coal India", 380.0, 9_000_000),
    "DRREDDY": ("Dr. Reddy's Laboratories", 1250.0, 2_000_000),
    "EICHERMOT": ("Eicher Motors", 7000.0, 500_000),
    "ETERNAL": ("Eternal", 300.0, 35_000_000),
    "GRASIM": ("Grasim Industries", 2750.0, 800_000),
    "HCLTECH": ("HCL Technologies", 1600.0, 3_500_000),
    "HDFCBANK": ("HDFC Bank", 990.0, 18_000_000),
    "HDFCLIFE": ("HDFC Life Insurance", 760.0, 3_000_000),
    "HINDALCO": ("Hindalco Industries", 800.0, 7_000_000),
    "HINDUNILVR": ("Hindustan Unilever", 2450.0, 1_500_000),
    "ICICIBANK": ("ICICI Bank", 1380.0, 12_000_000),
    "INDIGO": ("InterGlobe Aviation", 5800.0, 800_000),
    "INFY": ("Infosys", 1550.0, 8_000_000),
    "ITC": ("ITC", 405.0, 14_000_000),
    "JIOFIN": ("Jio Financial Services", 310.0, 15_000_000),
    "JSWSTEEL": ("JSW Steel", 1180.0, 2_000_000),
    "KOTAKBANK": ("Kotak Mahindra Bank", 2100.0, 4_000_000),
    "LT": ("Larsen & Toubro", 4000.0, 2_000_000),
    "M&M": ("Mahindra & Mahindra", 3700.0, 2_500_000),
    "MARUTI": ("Maruti Suzuki India", 16000.0, 400_000),
    "MAXHEALTH": ("Max Healthcare Institute", 1150.0, 2_000_000),
    "NESTLEIND": ("Nestle India", 1270.0, 1_000_000),
    "NTPC": ("NTPC", 330.0, 12_000_000),
    "ONGC": ("Oil and Natural Gas Corporation", 250.0, 12_000_000),
    "POWERGRID": ("Power Grid Corporation of India", 280.0, 10_000_000),
    "RELIANCE": ("Reliance Industries", 1500.0, 10_000_000),
    "SBILIFE": ("SBI Life Insurance", 2000.0, 1_000_000),
    "SBIN": ("State Bank of India", 950.0, 12_000_000),
    "SHRIRAMFIN": ("Shriram Finance", 800.0, 4_000_000),
    "SUNPHARMA": ("Sun Pharmaceutical Industries", 1750.0, 2_500_000),
    "TATACONSUM": ("Tata Consumer Products", 1150.0, 1_500_000),
    "TMPV": ("Tata Motors Passenger Vehicles", 400.0, 12_000_000),
    "TATASTEEL": ("Tata Steel", 175.0, 30_000_000),
    "TCS": ("Tata Consultancy Services", 3100.0, 3_000_000),
    "TECHM": ("Tech Mahindra", 1450.0, 2_000_000),
    "TITAN": ("Titan Company", 3800.0, 1_000_000),
    "TRENT": ("Trent", 4500.0, 1_000_000),
    "ULTRACEMCO": ("UltraTech Cement", 12000.0, 300_000),
    "WIPRO": ("Wipro", 245.0, 10_000_000),
    # Other liquid NSE names
    "ADANIGREEN": ("Adani Green Energy", 1050.0, 2_000_000),
    "BANKBARODA": ("Bank of Baroda", 280.0, 10_000_000),
    "BPCL": ("Bharat Petroleum Corporation", 360.0, 6_000_000),
    "CANBK": ("Canara Bank", 140.0, 15_000_000),
    "DLF": ("DLF", 760.0, 4_000_000),
    "DMART": ("Avenue Supermarts", 4200.0, 400_000),
    "GAIL": ("GAIL (India)", 180.0, 10_000_000),
    "HAL": ("Hindustan Aeronautics", 4700.0, 1_500_000),
    "HINDZINC": ("Hindustan Zinc", 480.0, 3_000_000),
    "IDEA": ("Vodafone Idea", 9.0, 300_000_000),
    "IOC": ("Indian Oil Corporation", 165.0, 12_000_000),
    "IRFC": ("Indian Railway Finance Corporation", 125.0, 20_000_000),
    "LODHA": ("Lodha Developers", 1200.0, 1_500_000),
    "PIDILITIND": ("Pidilite Industries", 1500.0, 800_000),
    "PNB": ("Punjab National Bank", 120.0, 25_000_000),
    "SIEMENS": ("Siemens", 3200.0, 500_000),
    "TATAELXSI": ("Tata Elxsi", 5400.0, 300_000),
    "TATAPOWER": ("Tata Power", 400.0, 10_000_000),
    "VEDL": ("Vedanta", 500.0, 10_000_000),
    "YESBANK": ("Yes Bank", 22.0, 100_000_000),
    "ZYDUSLIFE": ("Zydus Lifesciences", 1000.0, 1_200_000),
}

# symbol: (exchange, display name, reference price, Yahoo ticker)
INDICES = {
    "NIFTY": ("NSE_INDEX", "NIFTY 50", 25900.0, "^NSEI"),
    "BANKNIFTY": ("NSE_INDEX", "NIFTY BANK", 58500.0, "^NSEBANK"),
    "FINNIFTY": ("NSE_INDEX", "NIFTY FIN SERVICE", 27500.0, "NIFTY_FIN_SERVICE.NS"),
    "MIDCPNIFTY": ("NSE_INDEX", "NIFTY MID SELECT", 13500.0, "NIFTY_MID_SELECT.NS"),
    "NIFTYNXT50": ("NSE_INDEX", "NIFTY NEXT 50", 69000.0, "^NSMIDCP"),
    "NIFTYIT": ("NSE_INDEX", "NIFTY IT", 36000.0, "^CNXIT"),
    "NIFTY500": ("NSE_INDEX", "NIFTY 500", 23500.0, "^CRSLDX"),
    "NIFTYAUTO": ("NSE_INDEX", "NIFTY AUTO", 26500.0, "^CNXAUTO"),
    "NIFTYCOMMODITIES": ("NSE_INDEX", "NIFTY COMMODITIES", 9000.0, "^CNXCMDT"),
    "NIFTYENERGY": ("NSE_INDEX", "NIFTY ENERGY", 35500.0, "^CNXENERGY"),
    "NIFTYFMCG": ("NSE_INDEX", "NIFTY FMCG", 56000.0, "^CNXFMCG"),
    "NIFTYINFRA": ("NSE_INDEX", "NIFTY INFRA", 9300.0, "^CNXINFRA"),
    "NIFTYMEDIA": ("NSE_INDEX", "NIFTY MEDIA", 1500.0, "^CNXMEDIA"),
    "NIFTYMETAL": ("NSE_INDEX", "NIFTY METAL", 10200.0, "^CNXMETAL"),
    "NIFTYPHARMA": ("NSE_INDEX", "NIFTY PHARMA", 22500.0, "^CNXPHARMA"),
    "NIFTYPVTBANK": ("NSE_INDEX", "NIFTY PVT BANK", 28000.0, "NIFTY_PVT_BANK.NS"),
    "NIFTYPSE": ("NSE_INDEX", "NIFTY PSE", 10000.0, "^CNXPSE"),
    "NIFTYPSUBANK": ("NSE_INDEX", "NIFTY PSU BANK", 8000.0, "^CNXPSUBANK"),
    "NIFTYREALTY": ("NSE_INDEX", "NIFTY REALTY", 900.0, "^CNXREALTY"),
    "NIFTYCONSRDURBL": ("NSE_INDEX", "NIFTY CONSR DURBL", 38000.0, "NIFTY_CONSR_DURBL.NS"),
    "NIFTYHEALTHCARE": ("NSE_INDEX", "NIFTY HEALTHCARE", 14500.0, "NIFTY_HEALTHCARE.NS"),
    "NIFTYINDDEFENCE": ("NSE_INDEX", "NIFTY IND DEFENCE", 8000.0, "NIFTY_IND_DEFENCE.NS"),
    "NIFTYOILANDGAS": ("NSE_INDEX", "NIFTY OIL AND GAS", 12000.0, "NIFTY_OIL_AND_GAS.NS"),
    "INDIAVIX": ("NSE_INDEX", "INDIA VIX", 12.0, "^INDIAVIX"),
    "SENSEX": ("BSE_INDEX", "SENSEX", 84500.0, "^BSESN"),
    "BANKEX": ("BSE_INDEX", "BANKEX", 65000.0, "BSE-BANK.BO"),
}

# Index derivatives: underlying -> settings. Lot sizes are NSE's current ones.
INDEX_DERIVATIVES = {
    "NIFTY": {
        "lotsize": 65,
        "strike_step": 50,
        "strikes_each_side": 40,
        "weekly_expiries": 4,
        "monthly_expiries": 3,
        "futures": 3,
        "base_iv": 0.13,
    },
    "BANKNIFTY": {
        "lotsize": 30,
        "strike_step": 100,
        "strikes_each_side": 40,
        "weekly_expiries": 0,
        "monthly_expiries": 3,
        "futures": 3,
        "base_iv": 0.15,
    },
    "FINNIFTY": {
        "lotsize": 60,
        "strike_step": 50,
        "strikes_each_side": 0,
        "weekly_expiries": 0,
        "monthly_expiries": 0,
        "futures": 3,
        "base_iv": 0.14,
    },
    "MIDCPNIFTY": {
        "lotsize": 120,
        "strike_step": 25,
        "strikes_each_side": 0,
        "weekly_expiries": 0,
        "monthly_expiries": 0,
        "futures": 3,
        "base_iv": 0.17,
    },
}

#: Implied volatility of a stock's options or of an unknown underlying.
DEFAULT_STOCK_IV = 0.25

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

OPTION_RE = re.compile(r"^(?P<underlying>.+?)(?P<expiry>\d{2}[A-Z]{3}\d{2})(?P<strike>\d+(?:\.\d+)?)(?P<kind>CE|PE)$")
FUTURE_RE = re.compile(r"^(?P<underlying>.+?)(?P<expiry>\d{2}[A-Z]{3}\d{2})FUT$")


def now_ist() -> datetime:
    """The current time in IST."""
    return datetime.now(IST)


def tick_size_for(price: float) -> float:
    """NSE equity tick size for a price."""
    return 0.01 if price < 10 else 0.05


def stable_hash(text: str) -> int:
    """A process-independent 32-bit hash (Python's hash() is salted per process)."""
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def fallback_reference(symbol: str) -> float:
    """A deterministic reference price for a symbol the bundle does not know."""
    return round(80.0 + (stable_hash(symbol) % 112000) / 100.0, 2)


def equity_reference(symbol: str) -> float:
    """Reference price of an equity, or the deterministic fallback."""
    entry = EQUITIES.get(symbol)
    return entry[1] if entry else fallback_reference(symbol)


def index_reference(symbol: str) -> float:
    """Reference price of an index, or the deterministic fallback."""
    entry = INDICES.get(symbol)
    return entry[2] if entry else fallback_reference(symbol)


def underlying_reference(underlying: str) -> float:
    """Reference price of a derivative's underlying (an index or a stock)."""
    if underlying in INDICES:
        return INDICES[underlying][2]
    return equity_reference(underlying)


def underlying_exchange(underlying: str) -> str:
    """The exchange whose quote is the spot of a derivative's underlying."""
    if underlying in INDICES:
        return INDICES[underlying][0]
    return "NSE"


def underlying_iv(underlying: str) -> float:
    """The at-the-money implied volatility the simulator prices options with."""
    settings = INDEX_DERIVATIVES.get(underlying)
    return settings["base_iv"] if settings else DEFAULT_STOCK_IV


def format_expiry_code(day: date) -> str:
    """DDMMMYY, as used inside OpenAlgo symbols (28NOV25)."""
    return f"{day.day:02d}{MONTHS[day.month - 1]}{day.year % 100:02d}"


def format_expiry_column(day: date) -> str:
    """DD-MMM-YY, as stored in the symtoken expiry column (28-NOV-25)."""
    return f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year % 100:02d}"


def parse_expiry_code(code: str) -> date:
    """Parse DDMMMYY back into a date."""
    return date(2000 + int(code[5:7]), MONTHS.index(code[2:5]) + 1, int(code[0:2]))


def format_strike(strike: float) -> str:
    """A strike as it appears in an OpenAlgo symbol: no trailing .0."""
    return str(int(strike)) if float(strike).is_integer() else f"{strike:g}"


def option_symbol(underlying: str, expiry: date, strike: float, kind: str) -> str:
    """OpenAlgo option symbol, e.g. NIFTY25NOV2626000CE."""
    return f"{underlying}{format_expiry_code(expiry)}{format_strike(strike)}{kind}"


def future_symbol(underlying: str, expiry: date) -> str:
    """OpenAlgo futures symbol, e.g. NIFTY24NOV26FUT."""
    return f"{underlying}{format_expiry_code(expiry)}FUT"


def parse_option(symbol: str):
    """(underlying, expiry date, strike, CE|PE) for an option symbol, else None."""
    match = OPTION_RE.match(symbol or "")
    if not match:
        return None
    try:
        expiry = parse_expiry_code(match.group("expiry"))
    except (ValueError, IndexError):
        return None
    return match.group("underlying"), expiry, float(match.group("strike")), match.group("kind")


def parse_future(symbol: str):
    """(underlying, expiry date) for a futures symbol, else None."""
    match = FUTURE_RE.match(symbol or "")
    if not match:
        return None
    try:
        expiry = parse_expiry_code(match.group("expiry"))
    except (ValueError, IndexError):
        return None
    return match.group("underlying"), expiry


def expiry_datetime(expiry: date) -> datetime:
    """The IST moment a contract expires."""
    return IST.localize(datetime.combine(expiry, EXPIRY_CUTOFF))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _first_tradable_day(now: datetime) -> date:
    """Today, or tomorrow once today's expiries have closed."""
    today = now.date()
    return today + timedelta(days=1) if now.time() >= EXPIRY_CUTOFF else today


def monthly_expiries(count: int, now: datetime | None = None) -> list[date]:
    """The next ``count`` monthly expiries: the last Tuesday of each month."""
    now = now or now_ist()
    start = _first_tradable_day(now)
    out = []
    year, month = start.year, start.month
    while len(out) < count:
        expiry = _last_weekday_of_month(year, month, calendar.TUESDAY)
        if expiry >= start:
            out.append(expiry)
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def weekly_expiries(count: int, now: datetime | None = None) -> list[date]:
    """The next ``count`` weekly expiries: every Tuesday."""
    now = now or now_ist()
    start = _first_tradable_day(now)
    first = start + timedelta(days=(calendar.TUESDAY - start.weekday()) % 7)
    return [first + timedelta(weeks=i) for i in range(count)]


def option_expiries(underlying: str, now: datetime | None = None) -> list[date]:
    """Every option expiry listed for an underlying, sorted."""
    settings = INDEX_DERIVATIVES.get(underlying)
    if not settings or not settings["strikes_each_side"]:
        return []
    days = set(weekly_expiries(settings["weekly_expiries"], now))
    days.update(monthly_expiries(settings["monthly_expiries"], now))
    return sorted(days)


def atm_strike(spot: float, step: float) -> float:
    """The strike nearest the spot."""
    return round(spot / step) * step


def build_instruments(spot_of=None, now: datetime | None = None) -> list[dict]:
    """Every symtoken row of the paper broker.

    Args:
        spot_of: Optional callable(underlying) -> current price, used to centre
            the option strikes. Defaults to the bundled reference prices.
        now: The moment to compute expiries from (IST). Defaults to now.

    Returns:
        list[dict]: Rows with the SymToken columns.
    """
    now = now or now_ist()
    spot_of = spot_of or underlying_reference
    rows = []
    token = 100000

    def add(symbol, name, exchange, expiry="", strike=0.0, lotsize=1, kind="EQ", tick=0.05):
        nonlocal token
        token += 1
        rows.append(
            {
                "symbol": symbol,
                "brsymbol": symbol,
                "name": name,
                "exchange": exchange,
                "brexchange": exchange,
                "token": str(token),
                "expiry": expiry,
                "strike": float(strike),
                "lotsize": int(lotsize),
                "instrumenttype": kind,
                "tick_size": float(tick),
                "contract_value": None,
            }
        )

    for symbol, (name, price, _volume) in EQUITIES.items():
        add(symbol, name, "NSE", tick=tick_size_for(price))
        add(symbol, name, "BSE", tick=tick_size_for(price))

    for symbol, (exchange, display, _price, _yahoo) in INDICES.items():
        add(symbol, display, exchange, tick=0.05)

    for underlying, settings in INDEX_DERIVATIVES.items():
        for expiry in monthly_expiries(settings["futures"], now):
            add(
                future_symbol(underlying, expiry),
                underlying,
                "NFO",
                expiry=format_expiry_column(expiry),
                lotsize=settings["lotsize"],
                kind="FUT",
                tick=0.10,
            )

        expiries = option_expiries(underlying, now)
        if not expiries:
            continue
        step = settings["strike_step"]
        centre = atm_strike(float(spot_of(underlying)), step)
        wing = settings["strikes_each_side"]
        strikes = [centre + step * i for i in range(-wing, wing + 1) if centre + step * i > 0]
        for expiry in expiries:
            for strike in strikes:
                for kind in ("CE", "PE"):
                    add(
                        option_symbol(underlying, expiry, strike, kind),
                        underlying,
                        "NFO",
                        expiry=format_expiry_column(expiry),
                        strike=strike,
                        lotsize=settings["lotsize"],
                        kind=kind,
                        tick=0.05,
                    )
    return rows
