"""T02: broker login, keys, setup guide and env/install files know only paper and zerodha.

Zerodha login keeps working as before (Kite address with the state in
redirect_params, callback through the generic branch). No network: the
Flask checks use a bare app with the login blueprint registered.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

REPO = Path(__file__).resolve().parent.parent

REMOVED = (
    "aliceblue", "angel", "arrow", "compositedge", "definedge", "deltaexchange", "dhan",
    "dhan_sandbox", "firstock", "fivepaisa", "fivepaisaxts", "flattrade", "fyers", "groww",
    "hdfcsecurities", "hdfcsky", "ibulls", "iifl", "iiflcapital", "indmoney", "jainamxts",
    "kotak", "motilal", "mstock", "nubra", "paytm", "pocketful", "rmoney", "rupeezy", "sahi",
    "samco", "shoonya", "tradejini", "tradesmart", "upstox", "wisdom", "zebu",
)
_REMOVED_ALT = "|".join(sorted(REMOVED + ("icici",), key=len, reverse=True))
QUOTED_REMOVED = re.compile(rf"""["'](?:{_REMOVED_ALT})["']""")


def _keys(broker, api_key="kite_key", redirect="http://127.0.0.1:5000/zerodha/callback"):
    from utils.broker_keys import BrokerKeys

    return BrokerKeys(
        broker=broker,
        source="env",
        api_key=api_key,
        api_secret="secret",
        api_key_market="",
        api_secret_market="",
        redirect_url=redirect,
    )


# -- utils/broker_keys.py ------------------------------------------------------


def test_broker_names_are_paper_and_zerodha():
    from utils import broker_keys

    assert broker_keys.BROKER_NAMES == {"paper": "Sandbox (No Broker)", "zerodha": "Zerodha"}
    assert broker_keys.KEYLESS_BROKERS == frozenset({"paper"})
    assert broker_keys.broker_title("zerodha") == "Zerodha"


def test_key_format_table_is_empty_and_check_passes():
    from utils import broker_keys

    assert broker_keys._KEY_FORMATS == {}
    assert broker_keys.key_format_error("zerodha", "abc123") is None
    assert broker_keys.key_format_error("zerodha", "") is None
    # A name no longer known is not an error either: there is no format to check.
    assert broker_keys.key_format_error("fivepaisa", "no-separators") is None


def test_enabled_brokers_skips_names_without_a_plugin(monkeypatch):
    from utils import broker_keys

    monkeypatch.setenv("VALID_BROKERS", "paper, zerodha ,angel,dhan,paper")
    assert broker_keys.enabled_brokers() == ["paper", "zerodha"]


def test_enabled_brokers_empty_when_unset(monkeypatch):
    from utils import broker_keys

    monkeypatch.setenv("VALID_BROKERS", "")
    assert broker_keys.enabled_brokers() == []


# -- utils/broker_setup_guide.py ----------------------------------------------


def test_setup_guides_are_paper_and_zerodha():
    from utils import broker_setup_guide as g

    assert set(g.GUIDES) == {"paper", "zerodha"}
    assert g.uses_redirect_url("zerodha") is True
    assert g.uses_redirect_url("paper") is False
    assert g.guide("zerodha")["name"] == "Zerodha"


def test_setup_guide_for_unknown_broker_is_generic_not_an_error():
    from utils import broker_setup_guide as g

    generic = g.guide("angel")
    assert generic["sign_in"] == "redirect"
    assert generic["fields"]


# -- utils/broker_login.py ----------------------------------------------------


def test_login_broker_sets_reduced():
    from utils import broker_login as bl

    assert bl.BROKER_SITE_POST_BROKERS == frozenset()
    assert bl.CALLBACK_START_BROKERS == frozenset({"paper"})
    assert bl.STATE_BROKERS == frozenset({"zerodha"})
    assert bl._STATE_CALLBACK_START_BROKERS == frozenset()
    assert not hasattr(bl, "xts_login_url")


def test_zerodha_login_url_carries_state_in_redirect_params():
    from utils import broker_login as bl

    url = bl.login_url(_keys("zerodha"), "s1")
    assert url.startswith("https://kite.zerodha.com/connect/login?v=3&api_key=kite_key")
    assert "redirect_params=state%3Ds1" in url
    query = parse_qs(urlparse(url).query)
    assert query["redirect_params"] == ["state=s1"]


def test_zerodha_login_url_encodes_an_unsafe_key():
    from utils import broker_login as bl

    url = bl.login_url(_keys("zerodha", api_key="a b&c"), "s2")
    assert "api_key=a%20b%26c" in url


def test_paper_login_starts_at_its_callback():
    from utils import broker_login as bl

    assert bl.login_url(_keys("paper", api_key=""), "s") == "/paper/callback"


@pytest.mark.parametrize("name", ["dhan", "fyers", "upstox", "flattrade", "rmoney", "somebroker"])
def test_any_other_name_falls_back_to_its_callback(name):
    from utils import broker_login as bl

    assert bl.login_url(_keys(name), "s") == f"/{name}/callback"


def test_broker_site_post_is_refused_for_every_broker():
    from utils import broker_login as bl

    for broker in ("zerodha", "paper", "rmoney", "compositedge"):
        assert bl.is_broker_site_post(broker, "POST") is False


# -- blueprints/brlogin.py ----------------------------------------------------


@pytest.fixture(scope="module")
def login_rules():
    from flask import Flask

    from blueprints import brlogin

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(brlogin.brlogin_bp)
    return {r.rule for r in app.url_map.iter_rules()}


def test_generic_callback_route_kept(login_rules):
    assert "/<broker>/callback" in login_rules


@pytest.mark.parametrize("rule", ["/dhan/initiate-oauth", "/samco/ip-status", "/nubra/ip-status"])
def test_removed_broker_routes_gone(login_rules, rule):
    assert rule not in login_rules


@pytest.mark.parametrize(
    "name", ["_dhan_account_mismatch", "_xts_account_mismatch", "_refuse_xts_account", "_dhan_initiate_oauth"]
)
def test_removed_broker_helpers_gone(name):
    from blueprints import brlogin

    assert not hasattr(brlogin, name)


def test_brlogin_keeps_paper_branch_and_zerodha_token_prefix():
    src = (REPO / "blueprints" / "brlogin.py").read_text(encoding="utf-8")
    assert re.search(r"""broker\s*==\s*["']paper["']""", src)
    assert "zerodha" in src  # the '<api_key>:' token prefix on success
    assert "_complete_login(" in src


@pytest.mark.parametrize(
    "rel",
    [
        "utils/broker_keys.py",
        "utils/broker_setup_guide.py",
        "utils/broker_login.py",
        "blueprints/brlogin.py",
        "blueprints/broker_config.py",
        "blueprints/broker_credentials.py",
        "utils/env_check.py",
    ],
)
def test_owned_file_names_no_removed_broker(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    hits = [
        f"{rel}:{n}: {line.strip()[:120]}"
        for n, line in enumerate(text.splitlines(), 1)
        if QUOTED_REMOVED.search(line)
    ]
    assert hits == []


# -- env and install files ------------------------------------------------------


def _valid_brokers_line(text):
    match = re.search(r"^VALID_BROKERS\s*=\s*['\"]([^'\"]*)['\"]", text, re.M)
    assert match, "VALID_BROKERS line missing"
    return match.group(1)


def test_sample_env_valid_brokers():
    text = (REPO / ".sample.env").read_text(encoding="utf-8")
    assert _valid_brokers_line(text) == "paper,zerodha"


def test_dot_env_valid_brokers():
    env = REPO / ".env"
    if not env.exists():
        pytest.skip("no .env in this checkout (CI)")
    assert _valid_brokers_line(env.read_text(encoding="utf-8")) == "paper,zerodha"


def test_start_sh_default_valid_brokers():
    text = (REPO / "start.sh").read_text(encoding="utf-8")
    assert "${VALID_BROKERS:-paper,zerodha}" in text


@pytest.mark.parametrize("rel", ["install/docker-run.sh", "install/docker-run.bat"])
def test_docker_run_no_xts_broker_list(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert "XTS Brokers" not in text
    assert "fivepaisaxts" not in text


@pytest.mark.parametrize("rel", ["docker-build.sh", "docker-build.bat"])
def test_docker_build_hints_only_zerodha(rel):
    text = (REPO / rel).read_text(encoding="utf-8").lower()
    for name in ("fyers", "angel", "dhan", "upstox"):
        assert name not in text, f"{rel} still mentions {name}"
    assert "zerodha/callback" in text


@pytest.mark.parametrize(
    "rel",
    [
        ".sample.env",
        "start.sh",
        "install/install.sh",
        "install/install-docker.sh",
        "install/install-multi.sh",
        "install/install-docker-multi-custom-ssl.sh",
        "install/docker-run.sh",
        "install/docker-run.bat",
    ],
)
def test_install_files_list_no_removed_broker_in_valid_brokers(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    for line in text.splitlines():
        if "VALID_BROKERS" in line and "=" in line:
            for name in REMOVED:
                assert not re.search(rf"\b{name}\b", line), f"{rel}: {line.strip()[:120]}"
