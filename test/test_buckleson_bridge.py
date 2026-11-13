"""Buckleson additions: local mode and the Claude Code bridge.

These run without the full app: a bare Flask app gets the blueprint or the
before-request hook, and the database calls are patched.
"""

from __future__ import annotations

import json
import time
from unittest import mock

import pytest
from flask import Flask, session

from blueprints import claude_bridge
from utils import local_mode


# --------------------------------------------------------------------------- #
# local mode
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("TRUE", True), ("1", True), ("on", True), ("false", False), ("0", False), ("no", False)],
)
def test_local_mode_enabled_reads_env(monkeypatch, value, expected):
    monkeypatch.setenv("BUCKLESON_LOCAL_MODE", value)
    assert local_mode.enabled() is expected


def test_local_mode_defaults_on(monkeypatch):
    monkeypatch.delenv("BUCKLESON_LOCAL_MODE", raising=False)
    assert local_mode.enabled() is True


def test_local_broker_defaults_to_paper(monkeypatch):
    monkeypatch.delenv("BUCKLESON_LOCAL_BROKER", raising=False)
    assert local_mode.local_broker() == "paper"


def _hook_app():
    app = Flask(__name__)
    app.secret_key = "test"

    @app.before_request
    def _attach():
        local_mode.attach_operator_session()

    @app.route("/dashboard")
    def dashboard():
        return {
            "user": session.get("user"),
            "broker": session.get("broker"),
            "logged_in": session.get("logged_in"),
        }

    @app.route("/api/v1/funds", methods=["POST"])
    def funds():
        return {"user": session.get("user")}

    return app


def test_every_browser_request_gets_the_operator_session(monkeypatch):
    monkeypatch.setenv("BUCKLESON_LOCAL_MODE", "true")
    monkeypatch.setattr(local_mode._bootstrapped, "is_set", lambda: True)
    with mock.patch("utils.session.mark_signed_in"), mock.patch("database.auth_db.register_session"):
        client = _hook_app().test_client()
        data = client.get("/dashboard").get_json()
    assert data == {"user": local_mode.LOCAL_USER, "broker": "paper", "logged_in": True}


def test_api_requests_are_not_given_a_session(monkeypatch):
    """/api/v1 authenticates by API key; local mode must not add a browser session there."""
    monkeypatch.setenv("BUCKLESON_LOCAL_MODE", "true")
    monkeypatch.setattr(local_mode._bootstrapped, "is_set", lambda: True)
    client = _hook_app().test_client()
    assert client.post("/api/v1/funds").get_json() == {"user": None}


def test_local_mode_off_leaves_requests_alone(monkeypatch):
    monkeypatch.setenv("BUCKLESON_LOCAL_MODE", "false")
    client = _hook_app().test_client()
    assert client.get("/dashboard").get_json()["user"] is None


# --------------------------------------------------------------------------- #
# Claude bridge
# --------------------------------------------------------------------------- #


def test_trade_access_has_no_unrestricted_shell():
    allowed = claude_bridge.ACCESS_LEVELS["trade"]["allowed"]
    assert "Bash" not in allowed
    assert "Edit" not in allowed and "Write" not in allowed
    assert f"mcp__{claude_bridge.MCP_SERVER_NAME}" in allowed


def test_full_access_adds_shell_and_edits():
    allowed = claude_bridge.ACCESS_LEVELS["full"]["allowed"]
    assert {"Bash", "Edit", "Write"} <= set(allowed)


def test_system_prompt_names_the_mode():
    assert "SANDBOX" in claude_bridge._system_prompt(True)
    assert "LIVE" in claude_bridge._system_prompt(False)


def test_in_app_mcp_spec_labels_its_heartbeats():
    spec = claude_bridge.mcp_server_spec("k" * 64, claude_bridge.IN_APP_CLIENT)
    assert spec["env"] == {"BUCKLESON_MCP_CLIENT": claude_bridge.IN_APP_CLIENT}
    assert "k" * 64 in spec["args"]
    assert any(str(a).endswith("mcpserver.py") for a in spec["args"])


def test_terminal_mcp_spec_has_no_client_label():
    assert "env" not in claude_bridge.mcp_server_spec("k" * 64)


@pytest.mark.parametrize(
    "value,expected",
    [("abc", "abc"), ("/usr/bin/uv", "/usr/bin/uv"), ("has space", "'has space'"), ("it's", "'it'\"'\"'s'")],
)
def test_shell_quote(value, expected):
    assert claude_bridge._shell_quote(value) == expected


def _bridge_app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(claude_bridge.claude_bp)
    return app


@pytest.fixture
def fresh_external():
    saved = dict(claude_bridge._external)
    claude_bridge._external.update(last_seen=None, last_tool=None, calls=0, client=None)
    yield claude_bridge._external
    claude_bridge._external.clear()
    claude_bridge._external.update(saved)


def test_heartbeat_refuses_a_bad_key(fresh_external):
    with mock.patch("database.auth_db.verify_api_key", return_value=None):
        res = _bridge_app().test_client().post("/claude/api/heartbeat", json={"apikey": "nope"})
    assert res.status_code == 403
    assert claude_bridge.external_status()["connected"] is False


def test_terminal_heartbeat_marks_external_connected(fresh_external):
    with mock.patch("database.auth_db.verify_api_key", return_value="buckleson"), mock.patch(
        "extensions.socketio.emit"
    ):
        client = _bridge_app().test_client()
        client.post("/claude/api/heartbeat", json={"apikey": "k", "client": "Claude Code"})
        client.post("/claude/api/heartbeat", json={"apikey": "k", "tool": "place_order", "client": "Claude Code"})
    status = claude_bridge.external_status()
    assert status["connected"] is True
    assert status["last_tool"] == "place_order"
    assert status["calls"] == 1


def test_in_app_heartbeat_is_not_a_terminal_session(fresh_external):
    with mock.patch("database.auth_db.verify_api_key", return_value="buckleson"):
        _bridge_app().test_client().post(
            "/claude/api/heartbeat", json={"apikey": "k", "tool": "get_quote", "client": claude_bridge.IN_APP_CLIENT}
        )
    assert claude_bridge.external_status()["connected"] is False


def test_external_session_expires(fresh_external):
    fresh_external["last_seen"] = time.time() - claude_bridge.HEARTBEAT_WINDOW_SECONDS - 5
    assert claude_bridge.external_status()["connected"] is False


def test_conversation_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_bridge, "STORE_DIR", tmp_path)
    monkeypatch.setattr(claude_bridge, "CONVERSATIONS_FILE", tmp_path / "conversations.json")
    claude_bridge._append_items("c1", [{"role": "user", "text": "buy infy"}], title="buy infy")
    claude_bridge._append_items("c1", [{"role": "assistant", "text": "done"}], session_id="s-1")
    data = json.loads((tmp_path / "conversations.json").read_text(encoding="utf-8"))
    assert data["c1"]["title"] == "buy infy"
    assert data["c1"]["session_id"] == "s-1"
    assert [i["role"] for i in data["c1"]["items"]] == ["user", "assistant"]


def test_desk_dir_is_seeded_from_template(tmp_path, monkeypatch):
    monkeypatch.setenv("BUCKLESON_DESK_DIR", str(tmp_path / "desk"))
    target = claude_bridge.desk_dir()
    assert (target / "CLAUDE.md").exists()
    assert (target / ".claude" / "skills" / "agent-reach" / "SKILL.md").exists()
