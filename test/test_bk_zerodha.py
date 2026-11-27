"""Zerodha API in local mode, and Zerodha's Kite MCP server in the Claude bridge.

Bare Flask apps and patched database calls: nothing here talks to Zerodha.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask, session

from blueprints import claude_bridge
from utils import local_mode

# --------------------------------------------------------------------------- #
# Which broker the operator is on
# --------------------------------------------------------------------------- #


def _row(broker):
    return SimpleNamespace(broker=broker)


def test_a_live_zerodha_session_is_the_active_broker(monkeypatch):
    monkeypatch.delenv("BUCKLESON_LOCAL_BROKER", raising=False)
    with mock.patch("database.auth_db.get_auth_token_dbquery", return_value=_row("zerodha")):
        assert local_mode.active_broker() == "zerodha"


def test_no_session_means_the_paper_broker(monkeypatch):
    monkeypatch.delenv("BUCKLESON_LOCAL_BROKER", raising=False)
    with mock.patch("database.auth_db.get_auth_token_dbquery", return_value=None):
        assert local_mode.active_broker() == "paper"


def test_a_live_zerodha_session_is_not_replaced_by_paper(monkeypatch):
    monkeypatch.delenv("BUCKLESON_LOCAL_BROKER", raising=False)
    with mock.patch("database.auth_db.get_auth_token", return_value="kite-token"), mock.patch(
        "database.auth_db.upsert_auth"
    ) as upsert:
        local_mode.ensure_broker_session()
    upsert.assert_not_called()


def test_an_expired_zerodha_session_falls_back_to_paper(monkeypatch):
    monkeypatch.delenv("BUCKLESON_LOCAL_BROKER", raising=False)
    with mock.patch("database.auth_db.get_auth_token", return_value=None), mock.patch(
        "database.auth_db.upsert_auth"
    ) as upsert:
        local_mode.ensure_broker_session()
    upsert.assert_called_once()
    assert upsert.call_args.args[:3] == (local_mode.LOCAL_USER, local_mode.PAPER_AUTH_TOKEN, "paper")


def _hook_app():
    app = Flask(__name__)
    app.secret_key = "test"

    @app.before_request
    def _attach():
        local_mode.attach_operator_session()

    @app.route("/dashboard")
    def dashboard():
        return {"broker": session.get("broker"), "feed": session.get("FEED_TOKEN")}

    return app


@pytest.mark.parametrize("broker,feed", [("zerodha", None), ("paper", local_mode.PAPER_FEED_TOKEN)])
def test_a_new_browser_gets_the_broker_that_is_logged_in(monkeypatch, broker, feed):
    monkeypatch.setenv("BUCKLESON_LOCAL_MODE", "true")
    monkeypatch.setattr(local_mode._bootstrapped, "is_set", lambda: True)
    with mock.patch.object(local_mode, "ensure_broker_session"), mock.patch.object(
        local_mode, "active_broker", return_value=broker
    ), mock.patch("utils.session.mark_signed_in"), mock.patch("database.auth_db.register_session"):
        data = _hook_app().test_client().get("/dashboard").get_json()
    assert data == {"broker": broker, "feed": feed}


def test_a_browser_already_on_zerodha_keeps_its_session(monkeypatch):
    """After "Login with Zerodha" the session says zerodha; the hook must not reset it to paper."""
    monkeypatch.setenv("BUCKLESON_LOCAL_MODE", "true")
    monkeypatch.setattr(local_mode._bootstrapped, "is_set", lambda: True)
    client = _hook_app().test_client()
    with client.session_transaction() as s:
        s.update(user=local_mode.LOCAL_USER, logged_in=True, local_mode=True, broker="zerodha")
    with mock.patch.object(local_mode, "active_broker") as active:
        assert client.get("/dashboard").get_json()["broker"] == "zerodha"
    active.assert_not_called()


@pytest.mark.parametrize("broker,disabled", [("paper", True), ("zerodha", False)])
def test_session_expiry_follows_the_broker_logged_in(monkeypatch, broker, disabled):
    """Zerodha tokens end every day, so the daily rollover applies to it; paper has nothing to expire."""
    from utils.session import is_session_expiry_disabled

    monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "false")
    monkeypatch.setenv("BUCKLESON_LOCAL_MODE", "true")
    with mock.patch.object(local_mode, "active_broker", return_value=broker), mock.patch(
        "utils.broker_keys.logged_in_broker", return_value=broker
    ):
        assert is_session_expiry_disabled() is disabled


# --------------------------------------------------------------------------- #
# Kite MCP
# --------------------------------------------------------------------------- #


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _write_config(home, servers):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def test_kite_is_not_added_when_there_is_no_claude_config(claude_home):
    status = claude_bridge.kite_mcp_status()
    assert status["added"] is False
    assert status["url"] == claude_bridge.KITE_MCP_URL
    assert status["command"] == (
        f"claude mcp add --transport http --scope user kite {claude_bridge.KITE_MCP_URL}"
    )


def test_kite_is_added_when_claude_code_lists_it(claude_home):
    _write_config(claude_home, {"kite": {"type": "http", "url": "https://mcp.kite.trade/mcp"}})
    status = claude_bridge.kite_mcp_status()
    assert status["added"] is True
    assert status["configured_url"] == "https://mcp.kite.trade/mcp"


@pytest.mark.parametrize("content", ["not json", "[]", '{"mcpServers": null}'])
def test_a_broken_claude_config_reads_as_not_added(claude_home, content):
    (claude_home / ".claude.json").write_text(content, encoding="utf-8")
    assert claude_bridge.kite_mcp_status()["added"] is False


def test_the_default_endpoint_is_zerodhas_hosted_server():
    assert claude_bridge.KITE_MCP_URL == "https://mcp.kite.trade/mcp"


def test_every_kite_write_tool_is_blocked():
    assert set(claude_bridge.KITE_WRITE_TOOLS) == {
        "mcp__kite__place_order",
        "mcp__kite__modify_order",
        "mcp__kite__cancel_order",
        "mcp__kite__place_gtt_order",
        "mcp__kite__modify_gtt_order",
        "mcp__kite__delete_gtt_order",
    }


def _call(view):
    app = Flask(__name__)
    with app.test_request_context():
        res = view.__wrapped__()
    return (res, 200) if not isinstance(res, tuple) else res


def test_add_runs_claude_mcp_add_at_user_scope(claude_home, monkeypatch):
    monkeypatch.setattr(claude_bridge, "claude_binary", lambda: "/usr/bin/claude")
    calls = []

    def fake_run(args, timeout=20):
        calls.append(args)
        _write_config(claude_home, {"kite": {"type": "http", "url": claude_bridge.KITE_MCP_URL}})
        return 0, "Added HTTP MCP server kite"

    monkeypatch.setattr(claude_bridge, "_run_quick", fake_run)
    res, code = _call(claude_bridge.add_kite_mcp)
    assert calls == [
        ["/usr/bin/claude", "mcp", "add", "--transport", "http", "--scope", "user", "kite", claude_bridge.KITE_MCP_URL]
    ]
    assert code == 200 and res.get_json()["kite_mcp"]["added"] is True


def test_add_does_nothing_when_kite_is_already_added(claude_home, monkeypatch):
    _write_config(claude_home, {"kite": {"type": "http", "url": claude_bridge.KITE_MCP_URL}})
    monkeypatch.setattr(claude_bridge, "claude_binary", lambda: "/usr/bin/claude")
    run = mock.Mock()
    monkeypatch.setattr(claude_bridge, "_run_quick", run)
    res, code = _call(claude_bridge.add_kite_mcp)
    run.assert_not_called()
    assert code == 200 and res.get_json()["kite_mcp"]["added"] is True


def test_add_reports_a_cli_failure(claude_home, monkeypatch):
    monkeypatch.setattr(claude_bridge, "claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(claude_bridge, "_run_quick", lambda args, timeout=20: (1, "boom"))
    res, code = _call(claude_bridge.add_kite_mcp)
    assert code == 502
    assert res.get_json()["message"] == "boom"


def test_add_needs_claude_code(claude_home, monkeypatch):
    monkeypatch.setattr(claude_bridge, "claude_binary", lambda: None)
    _, code = _call(claude_bridge.add_kite_mcp)
    assert code == 409


def test_remove_runs_claude_mcp_remove(claude_home, monkeypatch):
    _write_config(claude_home, {"kite": {"type": "http", "url": claude_bridge.KITE_MCP_URL}})
    monkeypatch.setattr(claude_bridge, "claude_binary", lambda: "/usr/bin/claude")
    calls = []

    def fake_run(args, timeout=20):
        calls.append(args)
        _write_config(claude_home, {})
        return 0, "Removed"

    monkeypatch.setattr(claude_bridge, "_run_quick", fake_run)
    res, code = _call(claude_bridge.remove_kite_mcp)
    assert calls == [["/usr/bin/claude", "mcp", "remove", "kite", "--scope", "user"]]
    assert code == 200 and res.get_json()["kite_mcp"]["added"] is False


# --------------------------------------------------------------------------- #
# What Claude is told
# --------------------------------------------------------------------------- #


def test_prompt_on_zerodha_in_sandbox_says_orders_stay_simulated():
    prompt = claude_bridge._system_prompt(True, "zerodha")
    assert "Zerodha" in prompt and "orders stay simulated" in prompt


def test_prompt_on_zerodha_live_says_orders_are_real():
    assert "orders are real Zerodha orders" in claude_bridge._system_prompt(False, "zerodha")


def test_prompt_mentions_kite_only_when_added():
    assert "`kite`" not in claude_bridge._system_prompt(True, "paper", kite=False)
    with_kite = claude_bridge._system_prompt(True, "zerodha", kite=True)
    assert "`kite`" in with_kite
    assert "Never place, modify or cancel orders through it" in with_kite
