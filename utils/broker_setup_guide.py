# utils/broker_setup_guide.py
"""What Broker Configuration asks for, per broker, as OpenAlgo Desktop shows it.

For every broker: the keys it needs, labelled the way that broker names them,
a hint for each, a sentence on how its sign-in works, and what to do with the
redirect URL. Carried over from OpenAlgo Desktop's setup guide
(``src-tauri/src/brokers/setup_guide.rs``) so a trader sees the same page in
both, with these changes for how the web signs in:

- ``sign_in`` follows this server's login flow (``utils/broker_login`` and
  the callback routes in ``blueprints/brlogin.py``): a redirect to the
  broker's site, OpenAlgo's own form, or one click with the saved keys. Groww
  signs in with the saved keys here, so its sentence says so. A test starts
  each broker's login and checks where it goes against this table.
- No client ID is saved here, so the Client ID fields and the sentences about
  checking a login against one are left out. HDFC Sky's BROKER_CLIENT_ID
  stays in .env.
- Every field maps to one of the .env names in ``FIELD_ENV_VARS``.

A broker missing from the table gets the generic entry.
"""

#: The .env name each field is saved as.
FIELD_ENV_VARS = {
    "api_key": "BROKER_API_KEY",
    "api_secret": "BROKER_API_SECRET",
    "api_key_market": "BROKER_API_KEY_MARKET",
    "api_secret_market": "BROKER_API_SECRET_MARKET",
}

REDIRECT_REGISTER = "Register this exact address as the redirect URL in your broker app."

_GENERIC_FIELDS = (
    {
        "key": "api_key",
        "label": "API Key",
        "hint": "From your broker's developer portal.",
        "secret": False,
        "required": True,
    },
    {
        "key": "api_secret",
        "label": "API Secret",
        "hint": "From your broker's developer portal.",
        "secret": True,
        "required": True,
    },
)

_GENERIC_BANNERS = {
    "redirect": (
        "Login takes you to your broker's login page. Log in there and your broker "
        "sends you back to OpenAlgo."
    ),
    "form": "Login opens a short form in OpenAlgo for the details your broker asks for at each login.",
    "saved_keys": "Login signs you in with one click using the keys you saved.",
}

#: broker -> name, sign_in, fields, banner, redirect_hint
GUIDES = {
    "paper": {
        "name": "Sandbox (No Broker)",
        "sign_in": "saved_keys",
        "fields": (),
        "banner": "Sandbox (No Broker) needs no broker account and no keys. Login signs you "
        "in with one click and every order goes to the Sandbox. Prices come from Yahoo "
        "Finance when this server can reach it, and are simulated otherwise.",
        "redirect_hint": "",
    },
    "zerodha": {
        "name": "Zerodha",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The API key of your Kite Connect app at developers.kite.trade.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Zerodha takes you to Zerodha's Kite login page. Log in "
        "there and Zerodha sends you back to OpenAlgo. Market data needs an "
        "active Kite Connect subscription.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
}


def guide(broker):
    """The Broker Configuration entry for a broker, the generic one if unknown."""
    entry = GUIDES.get(broker)
    if entry is not None:
        return entry
    from utils.broker_keys import broker_title
    from utils.broker_login import CALLBACK_START_BROKERS

    sign_in = "form" if broker in CALLBACK_START_BROKERS else "redirect"
    return {
        "name": broker_title(broker),
        "sign_in": sign_in,
        "fields": _GENERIC_FIELDS,
        "banner": _GENERIC_BANNERS[sign_in],
        "redirect_hint": REDIRECT_REGISTER if sign_in == "redirect" else "",
    }


def uses_redirect_url(broker):
    """Whether the broker sends the trader back to a redirect URL."""
    return guide(broker)["sign_in"] == "redirect"
