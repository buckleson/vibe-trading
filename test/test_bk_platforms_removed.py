"""T04: TradingView, GoCharting, Chartink and the Platforms page are gone from the backend.

Flow and Strategy-module webhooks, REST, alerts and the Claude bridge stay.
The app module is checked by source and by registering the React blueprint on
a bare Flask app, so the test needs no database, broker or running server
(the live 404 checks are in scripts/bk_smoke.py).
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

DELETED_MODULES = [
    "blueprints.tv_json",
    "blueprints.gc_json",
    "blueprints.chartink",
    "blueprints.platforms",
    "database.chartink_db",
    "database.tv_search",
]
GONE_PREFIXES = ("/chartink", "/tradingview", "/gocharting", "/platforms")
GONE_RULES = {"/broker/<broker>/totp", "/broker/samco/auth", "/<broker>/auth"}


@pytest.mark.parametrize("module", DELETED_MODULES)
def test_platform_modules_deleted(module):
    assert importlib.util.find_spec(module) is None


def _app_imports():
    tree = ast.parse((REPO / "app.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_app_imports_no_platform_module():
    assert not (_app_imports() & set(DELETED_MODULES))


@pytest.mark.parametrize(
    "needle",
    ["chartink_bp", "gc_json_bp", "tv_json_bp", "platforms_bp", "Chartink DB", "ensure_chartink_tables_exists"],
)
def test_app_registers_nothing_for_platforms(needle):
    assert needle not in (REPO / "app.py").read_text(encoding="utf-8")


def test_app_still_registers_kept_surfaces():
    src = (REPO / "app.py").read_text(encoding="utf-8")
    for kept in ("flow_bp", "strategy_module", "claude_bp", "react_bp", "historify_bp"):
        assert kept in src, f"{kept} must stay registered"


@pytest.fixture(scope="module")
def react_rules():
    from flask import Flask

    from blueprints import react_app

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(react_app.react_bp)
    return {r.rule for r in app.url_map.iter_rules()}


def test_no_platform_react_routes(react_rules):
    assert [r for r in react_rules if r.startswith(GONE_PREFIXES)] == []


def test_no_broker_form_react_routes(react_rules):
    assert not (react_rules & GONE_RULES)


@pytest.mark.parametrize(
    "rule",
    ["/broker", "/broker/config", "/flow", "/strategy", "/tools", "/claude", "/historify",
     "/portfolio-backtester", "/sip-backtester", "/sector-rotation", "/strategybuilder",
     "/optionchain", "/python", "/agent"],
)
def test_kept_react_routes_present(react_rules, rule):
    assert rule in react_rules


# -- shutdown, sessions, redaction, init_db ------------------------------------


def test_shutdown_has_no_chartink_step():
    from utils import shutdown

    assert not hasattr(shutdown, "_stop_chartink_scheduler")
    assert "chartink" not in (REPO / "utils" / "shutdown.py").read_text(encoding="utf-8").lower()


def test_scoped_sessions_drop_chartink():
    from utils import db_sessions

    assert ("database.chartink_db", "db_session") not in db_sessions.SCOPED_SESSION_MODULES
    for module, _attr in db_sessions.SCOPED_SESSION_MODULES:
        if module.startswith("database."):
            assert importlib.util.find_spec(module) is not None, f"{module} is listed but missing"


@pytest.mark.parametrize(
    "path,secret",
    [
        ("/strategy/webhook/abc123secret", "abc123secret"),
        ("/flow/webhook/tok_987/NIFTY", "tok_987"),
        ("https://host.example/strategy/webhook/zzz?x=1", "zzz"),
    ],
)
def test_kept_webhooks_are_still_redacted(path, secret):
    from utils.url_redaction import redact_url_credentials

    out = redact_url_credentials(path)
    assert secret not in out


def test_redaction_no_longer_names_chartink():
    src = (REPO / "utils" / "url_redaction.py").read_text(encoding="utf-8")
    assert "chartink" not in src.lower()


def test_init_db_has_no_chartink():
    src = (REPO / "upgrade" / "init_db.py").read_text(encoding="utf-8")
    assert "chartink" not in src.lower()


def test_api_key_lookup_kept_for_its_many_callers():
    from database import auth_db

    assert callable(auth_db.get_api_key_for_tradingview)


def test_chartink_only_test_file_deleted():
    assert not (REPO / "test" / "test_gthread_hosts_chartink.py").exists()


CORE_REACT_PAGES = [
    "/dashboard", "/positions", "/orderbook", "/tradebook", "/holdings",
    "/scalping", "/search", "/playground", "/trading", "/claude", "/broker",
]


@pytest.mark.parametrize("path", CORE_REACT_PAGES)
def test_core_pages_are_still_served_by_react(path):
    """Removing the platform pages must not take the core React pages with them."""
    from flask import Flask

    from blueprints.react_app import react_bp

    app = Flask(__name__)
    app.register_blueprint(react_bp)
    adapter = app.url_map.bind("localhost")
    endpoint, _ = adapter.match(path)
    assert endpoint.startswith("react.")
