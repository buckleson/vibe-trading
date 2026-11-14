"""T01: only the Zerodha and Sandbox (paper) broker plugins remain.

Written before the removal. Every test here fails on the tree that still
carries the 37 other plugins and passes once T01 is done. Nothing here needs
the network, a broker account or a running server.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

REMOVED = (
    "aliceblue", "angel", "arrow", "compositedge", "definedge", "deltaexchange", "dhan",
    "dhan_sandbox", "firstock", "fivepaisa", "fivepaisaxts", "flattrade", "fyers", "groww",
    "hdfcsecurities", "hdfcsky", "ibulls", "iifl", "iiflcapital", "indmoney", "jainamxts",
    "kotak", "motilal", "mstock", "nubra", "paytm", "pocketful", "rmoney", "rupeezy", "sahi",
    "samco", "shoonya", "tradejini", "tradesmart", "upstox", "wisdom", "zebu",
)
KEPT = {"paper", "zerodha"}
_REMOVED_ALT = "|".join(sorted(REMOVED, key=len, reverse=True))
IMPORT_OF_REMOVED = re.compile(rf"\bbroker[./](?:{_REMOVED_ALT})\b")
QUOTED_REMOVED = re.compile(rf"""["'](?:{_REMOVED_ALT})["']""")

# Directories whose Python files are not runtime code of this app.
_SKIP_DIRS = {".venv", "node_modules", "test", "docs", "__pycache__", ".git", "frontend", "upgrade"}


def _runtime_python_files():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if rel.parts[0] == "broker" and len(rel.parts) > 1 and rel.parts[1] not in KEPT:
            continue  # a leftover plugin dir is reported by test_broker_dir_holds_only_kept_plugins
        yield rel, path


# -- the plugin directories --------------------------------------------------


def test_broker_dir_holds_only_kept_plugins():
    entries = {p.name for p in (REPO / "broker").iterdir()} - {"__pycache__"}
    assert entries == {"__init__.py", "paper", "zerodha"}


@pytest.mark.parametrize("name", REMOVED)
def test_removed_plugin_is_not_importable(name):
    assert importlib.util.find_spec(f"broker.{name}") is None


@pytest.mark.parametrize(
    "module",
    [
        "broker.zerodha.api.auth_api",
        "broker.zerodha.api.order_api",
        "broker.zerodha.api.data",
        "broker.zerodha.api.funds",
        "broker.zerodha.mapping.order_data",
        "broker.zerodha.streaming.zerodha_adapter",
        "broker.zerodha.database.master_contract_db",
        "broker.paper.api.data",
        "broker.paper.api.order_api",
        "broker.paper.streaming.paper_adapter",
    ],
)
def test_kept_plugins_still_import(module):
    # websocket_proxy first: a streaming adapter imported on its own re-enters
    # websocket_proxy/__init__.py (a pre-existing cycle; production imports the
    # proxy first).
    importlib.import_module("websocket_proxy")
    importlib.import_module(module)


# -- runtime registries ------------------------------------------------------


def test_websocket_proxy_registers_only_zerodha_and_paper():
    import websocket_proxy  # noqa: F401  (registers the adapters on import)
    from websocket_proxy import broker_factory

    assert set(broker_factory.BROKER_ADAPTERS) == KEPT


def test_websocket_proxy_unknown_broker_is_not_silently_angel():
    src = (REPO / "websocket_proxy" / "server.py").read_text(encoding="utf-8")
    assert '"angel"' not in src and "'angel'" not in src
    assert re.search(r"""getenv\(\s*["']VALID_BROKERS["']\s*,\s*["']paper""", src)


def test_websocket_proxy_has_no_flattrade_shoonya_keep_branch():
    src = (REPO / "websocket_proxy" / "server.py").read_text(encoding="utf-8")
    assert "flattrade" not in src and "shoonya" not in src


def test_postback_supports_only_zerodha():
    from blueprints import postback

    assert postback.SUPPORTED_BROKERS == {"zerodha"}
    for name in ("dhan", "fyers", "upstox", "angel", "aliceblue"):
        assert not hasattr(postback, f"_normalize_{name}")
    assert hasattr(postback, "_normalize_zerodha")
    assert hasattr(postback, "_validate_zerodha_checksum")


def test_postback_refuses_a_removed_broker():
    from flask import Flask

    from blueprints import postback

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(postback.postback_bp)
    rules = [r for r in app.url_map.iter_rules() if "<broker>" in r.rule]
    assert rules, "the postback route takes the broker in its path"
    path = rules[0].rule.replace("<broker>", "dhan")
    res = app.test_client().post(path, json={"order_id": "1"})
    assert res.status_code in (400, 404)


def test_order_update_service_knows_only_zerodha():
    from services import order_update_service as svc

    assert set(svc._BROKER_FACTORIES) == {"zerodha"}
    assert not (set(getattr(svc, "_POLLING_BROKERS", set())) & set(REMOVED))


def test_crypto_broker_set_is_empty_but_exchange_constants_stay():
    from utils import constants

    assert constants.CRYPTO_BROKERS == set()
    # The crypto exchange constants are still imported by kept callers.
    from services import telegram_bot_service  # noqa: F401
    from utils import auth_utils  # noqa: F401


def test_admin_probe_hosts_zerodha_only():
    from blueprints import admin

    assert admin._BROKER_PROBE_HOSTS == {"zerodha": "api.kite.trade"}


def test_position_read_names_only_kept_brokers():
    from utils import position_read

    assert set(position_read.BROKER_DISPLAY_NAMES) == KEPT


def test_option_chain_has_no_fyers_fast_path():
    src = (REPO / "services" / "option_chain_service.py").read_text(encoding="utf-8")
    assert "fyers" not in src.lower()
    assert "used_fast_path" not in src


# -- database: helpers go, schema stays ---------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "_get_samco_auth",
        "samco_save_secret_key",
        "samco_get_ip_status",
        "samco_save_ip_info",
        "samco_has_secret_key",
        "samco_get_secret_key",
        "samco_has_registered_ip",
    ],
)
def test_samco_helpers_removed(name):
    from database import auth_db

    assert not hasattr(auth_db, name)


def test_auth_table_columns_unchanged():
    """No schema change: existing installs keep their auth rows readable."""
    from database.auth_db import Auth

    assert sorted(c.name for c in Auth.__table__.columns) == [
        "auth", "aux_param1", "aux_param2", "aux_param3", "aux_param4", "broker",
        "feed_token", "id", "ip_updated_at", "is_revoked", "name", "primary_ip",
        "secondary_ip", "secret_api_key", "user_id",
    ]
    assert (REPO / "upgrade" / "migrate_samco_auth.py").exists()


def test_broker_sdk_downloads_example_deleted():
    assert not (REPO / "examples" / "python" / "broker_sdk_downloads.py").exists()


# -- nothing left that reaches a removed plugin --------------------------------


def test_no_runtime_python_imports_a_removed_plugin():
    offenders = []
    for rel, path in _runtime_python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if IMPORT_OF_REMOVED.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    assert offenders == []


@pytest.mark.parametrize(
    "rel",
    [
        "websocket_proxy/__init__.py",
        "websocket_proxy/server.py",
        "services/order_update_service.py",
        "blueprints/postback.py",
        "services/option_chain_service.py",
        "utils/position_read.py",
        "utils/constants.py",
        "blueprints/admin.py",
        "database/auth_db.py",
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


@pytest.mark.parametrize("name", REMOVED)
def test_no_test_file_exists_only_for_a_removed_broker(name):
    leftovers = sorted(p.name for p in (REPO / "test").glob(f"test_{name}_*.py"))
    leftovers += [p.name for p in (REPO / "test").glob(f"test_{name}.py")]
    assert leftovers == []
