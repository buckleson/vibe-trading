"""T05: Claude plan detection, one-click sign-in and Windows process handling.

No real claude login and no network: the CLI is a fake path, subprocess.Popen
is replaced by FakePopen, and the session check is patched open. Windows is
simulated by swapping the bridge module's ``os`` (and ``sys``) globals for a
proxy whose ``name`` is ``nt`` (``platform`` is ``win32``); patching the real
``os.name`` would break pathlib for the whole process.

Contract this file pins (blueprints/claude_bridge.py):
- the Windows decision reads ``os.name`` through the module global ``os``;
  install_info() reads ``sys.platform`` through the module global ``sys``;
- the login process is started with ``subprocess.Popen`` and stopped with the
  module-level ``kill_tree``;
- ``LOGIN_TIMEOUT_SECONDS`` and ``LOGIN_LOG`` are module globals read at call time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from unittest import mock

import pytest
from flask import Flask

from blueprints import claude_bridge as cb

REAL_CLI_TEXT = (
    "Opening browser to sign in...\n"
    "If the browser didn't open, visit: "
    "https://claude.com/cai/oauth/authorize?code=true&client_id=abc&response_type=code"
    "&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback&state=xyz\n"
    "Paste code here if prompted > "
)
REAL_URL = REAL_CLI_TEXT.split("visit: ")[1].split("\n")[0]


class _Proxy:
    """A stand-in module: the given attributes, everything else from the real one."""

    def __init__(self, real, **overrides):
        self._real = real
        self.__dict__.update(overrides)

    def __getattr__(self, item):
        return getattr(self._real, item)


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(cb, "os", _Proxy(os, name="nt"))
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    return monkeypatch


# --------------------------------------------------------------------------- #
# detect_plan (pure)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "info,environ,creds,expected",
    [
        ({"loggedIn": True, "authMethod": "oauth_token", "subscriptionType": "max"}, {}, {},
         {"key": "max", "label": "Claude Max"}),
        ({"loggedIn": True, "subscriptionType": "pro"}, {}, {}, {"key": "pro", "label": "Claude Pro"}),
        ({"loggedIn": True, "subscriptionType": "PRO"}, {}, {}, {"key": "pro", "label": "Claude Pro"}),
        ({"loggedIn": True, "subscription": "team"}, {}, {}, {"key": "team", "label": "Claude Team"}),
        ({"loggedIn": True, "plan": "enterprise"}, {}, {}, {"key": "enterprise", "label": "Claude Enterprise"}),
        ({"loggedIn": True, "subscriptionType": "free"}, {}, {}, {"key": "free", "label": "Claude Free"}),
        ({"loggedIn": True, "subscriptionType": "max_20x"}, {}, {}, {"key": "max_20x", "label": "Claude Max_20X"}),
        ({"loggedIn": True, "authMethod": "oauth_token"}, {}, {"claudeAiOauth": {"subscriptionType": "team"}},
         {"key": "team", "label": "Claude Team"}),
        # The status field wins over the credentials file.
        ({"loggedIn": True, "subscriptionType": "max"}, {}, {"claudeAiOauth": {"subscriptionType": "pro"}},
         {"key": "max", "label": "Claude Max"}),
        # Empty strings are skipped, not taken as a plan.
        ({"loggedIn": True, "subscriptionType": "", "plan": "pro"}, {}, {}, {"key": "pro", "label": "Claude Pro"}),
        ({"loggedIn": True, "apiProvider": "bedrock"}, {}, {}, {"key": "bedrock", "label": "Amazon Bedrock"}),
        ({"loggedIn": True, "apiProvider": "vertex"}, {}, {}, {"key": "vertex", "label": "Google Vertex AI"}),
        ({"loggedIn": True, "apiProvider": "foundry"}, {}, {}, {"key": "foundry", "label": "Microsoft Foundry"}),
        ({"loggedIn": True}, {"CLAUDE_CODE_USE_VERTEX": "1"}, {}, {"key": "vertex", "label": "Google Vertex AI"}),
        ({"loggedIn": True}, {"CLAUDE_CODE_USE_BEDROCK": "true"}, {}, {"key": "bedrock", "label": "Amazon Bedrock"}),
        ({"loggedIn": True}, {"CLAUDE_CODE_USE_FOUNDRY": "1"}, {}, {"key": "foundry", "label": "Microsoft Foundry"}),
        # A provider beats a subscription field.
        ({"loggedIn": True, "apiProvider": "bedrock", "subscriptionType": "max"}, {}, {},
         {"key": "bedrock", "label": "Amazon Bedrock"}),
        # firstParty is not a cloud provider.
        ({"loggedIn": True, "apiProvider": "firstParty", "authMethod": "oauth_token"}, {}, {},
         {"key": "subscription", "label": "Claude subscription"}),
        # "0" or "false" does not switch a provider on.
        ({"loggedIn": True}, {"CLAUDE_CODE_USE_BEDROCK": "0"}, {}, {"key": "subscription", "label": "Claude subscription"}),
        ({"loggedIn": True, "authMethod": "api_key"}, {}, {}, {"key": "api_key", "label": "Anthropic API key"}),
        ({"loggedIn": True, "authMethod": "apiKey"}, {}, {}, {"key": "api_key", "label": "Anthropic API key"}),
        ({"loggedIn": True, "authMethod": "console"}, {}, {}, {"key": "api_key", "label": "Anthropic API key"}),
        ({"loggedIn": False}, {"ANTHROPIC_API_KEY": "x"}, {}, {"key": "api_key", "label": "Anthropic API key"}),
        ({"loggedIn": True}, {}, {}, {"key": "subscription", "label": "Claude subscription"}),
        ({"loggedIn": False}, {}, {}, {"key": None, "label": None}),
        (None, {}, {}, {"key": None, "label": None}),
        ({}, {}, {}, {"key": None, "label": None}),
    ],
)
def test_detect_plan(info, environ, creds, expected):
    assert cb.detect_plan(info, environ, creds) == expected


def test_detect_plan_defaults_read_os_environ(monkeypatch):
    for var in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert cb.detect_plan({"loggedIn": False}) == {"key": "api_key", "label": "Anthropic API key"}
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert cb.detect_plan(None) == {"key": None, "label": None}


def test_detect_plan_ignores_non_string_subscription():
    assert cb.detect_plan({"loggedIn": True, "subscriptionType": 5}, {}, {}) == {
        "key": "subscription",
        "label": "Claude subscription",
    }


# --------------------------------------------------------------------------- #
# read_plan_credentials
# --------------------------------------------------------------------------- #


def _write_creds(directory, payload):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".credentials.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def test_credentials_return_only_the_subscription(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    _write_creds(
        tmp_path,
        {"claudeAiOauth": {"accessToken": "sk-ant-oat-SECRET", "refreshToken": "sk-ant-ort-SECRET",
                           "expiresAt": 1, "scopes": ["user:inference"], "subscriptionType": "max"}},
    )
    got = cb.read_plan_credentials()
    assert got == {"claudeAiOauth": {"subscriptionType": "max"}}
    assert "SECRET" not in json.dumps(got)


def test_credentials_without_subscription_are_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    _write_creds(tmp_path, {"claudeAiOauth": {"accessToken": "sk-ant-oat-SECRET"}})
    assert cb.read_plan_credentials() == {}


@pytest.mark.parametrize("payload", ["{not json", "[]", '"text"', "{}", '{"claudeAiOauth": null}'])
def test_credentials_invalid_file_is_empty(tmp_path, monkeypatch, payload):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    _write_creds(tmp_path, payload)
    assert cb.read_plan_credentials() == {}


def test_credentials_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nowhere"))
    assert cb.read_plan_credentials() == {}


def test_credentials_fall_back_to_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(cb.Path, "home", classmethod(lambda cls: tmp_path))
    _write_creds(tmp_path / ".claude", {"claudeAiOauth": {"subscriptionType": "pro", "accessToken": "t"}})
    assert cb.read_plan_credentials() == {"claudeAiOauth": {"subscriptionType": "pro"}}


def test_credentials_never_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    _write_creds(tmp_path, '{"claudeAiOauth": {"accessToken": "sk-ant-oat-SECRET", ')
    with caplog.at_level("DEBUG"):
        cb.read_plan_credentials()
    assert "SECRET" not in caplog.text


# --------------------------------------------------------------------------- #
# cli_status
# --------------------------------------------------------------------------- #


def _fake_quick(version="2.1.323 (Claude Code)", auth=None, auth_code=0):
    def run(args, timeout=20):
        if args[1:] == ["--version"]:
            return 0, version
        if args[1:3] == ["auth", "status"]:
            return auth_code, json.dumps(auth) if isinstance(auth, dict) else (auth or "")
        return -1, ""

    return run


@pytest.fixture
def no_creds(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for var in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        monkeypatch.delenv(var, raising=False)
    cb._status_cache.update(at=0.0, value=None)
    yield
    cb._status_cache.update(at=0.0, value=None)


def test_cli_status_reports_plan_provider_and_subscription(monkeypatch, no_creds):
    monkeypatch.setattr(cb, "claude_binary", lambda: "/fake/claude")
    auth = {"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty", "subscriptionType": "max"}
    monkeypatch.setattr(cb, "_run_quick", _fake_quick(auth=auth))
    value = cb.cli_status(force=True)
    assert value["installed"] is True and value["logged_in"] is True
    assert value["version"] == "2.1.323"
    assert value["auth_method"] == "oauth_token"
    assert value["api_provider"] == "firstParty"
    assert value["subscription"] == "max"
    assert value["plan"] == {"key": "max", "label": "Claude Max"}


def test_cli_status_plan_from_credentials_file(monkeypatch, no_creds, tmp_path):
    _write_creds(tmp_path / "cfg", {"claudeAiOauth": {"subscriptionType": "pro", "accessToken": "t"}})
    monkeypatch.setattr(cb, "claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(cb, "_run_quick", _fake_quick(auth={"loggedIn": True, "authMethod": "oauth_token"}))
    assert cb.cli_status(force=True)["plan"] == {"key": "pro", "label": "Claude Pro"}


def test_cli_status_failing_auth_with_api_key(monkeypatch, no_creds):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cb, "claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(cb, "_run_quick", _fake_quick(auth="error: unknown command", auth_code=1))
    value = cb.cli_status(force=True)
    assert value["logged_in"] is True
    assert value["plan"]["key"] == "api_key"


def test_cli_status_signed_out(monkeypatch, no_creds):
    monkeypatch.setattr(cb, "claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(cb, "_run_quick", _fake_quick(auth={"loggedIn": False}))
    value = cb.cli_status(force=True)
    assert value["installed"] is True and value["logged_in"] is False
    assert value["plan"] == {"key": None, "label": None}


def test_cli_status_missing_cli(monkeypatch, no_creds):
    monkeypatch.setattr(cb, "claude_binary", lambda: None)
    value = cb.cli_status(force=True)
    assert value["installed"] is False and value["logged_in"] is False
    assert value["path"] is None
    assert value["plan"] == {"key": None, "label": None}


def test_cli_status_non_json_auth_output(monkeypatch, no_creds):
    monkeypatch.setattr(cb, "claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(cb, "_run_quick", _fake_quick(auth="You are logged in."))
    value = cb.cli_status(force=True)
    assert value["logged_in"] is True
    assert "plan" in value


def test_cli_status_is_cached_until_forced(monkeypatch, no_creds):
    calls = []
    monkeypatch.setattr(cb, "claude_binary", lambda: calls.append(1) or None)
    cb.cli_status(force=True)
    cb.cli_status()
    assert len(calls) == 1
    cb.cli_status(force=True)
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# binary discovery
# --------------------------------------------------------------------------- #


def _norm(paths):
    return [str(p).replace("\\", "/") for p in paths]


def test_candidate_paths_posix(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "os", _Proxy(os, name="posix"))
    monkeypatch.setattr(cb.Path, "home", classmethod(lambda cls: tmp_path))
    paths = _norm(cb.candidate_paths())
    assert f"{tmp_path.as_posix()}/.claude/local/claude" in paths
    assert f"{tmp_path.as_posix()}/.local/bin/claude" in paths
    assert "/usr/local/bin/claude" in paths
    assert "/opt/homebrew/bin/claude" in paths
    assert not any(p.endswith((".exe", ".cmd")) for p in paths)


def test_candidate_paths_windows(windows, tmp_path):
    windows.setenv("USERPROFILE", str(tmp_path / "User"))
    windows.setenv("APPDATA", str(tmp_path / "Roaming"))
    paths = _norm(cb.candidate_paths())
    user, roaming = (tmp_path / "User").as_posix(), (tmp_path / "Roaming").as_posix()
    assert f"{user}/.local/bin/claude.exe" in paths
    assert f"{user}/.claude/local/claude.exe" in paths
    assert f"{roaming}/npm/claude.cmd" in paths
    assert f"{roaming}/npm/claude.exe" in paths
    assert "/usr/local/bin/claude" not in paths


def test_candidate_paths_windows_skips_unset_vars(windows, tmp_path):
    windows.setenv("USERPROFILE", str(tmp_path / "User"))
    windows.delenv("APPDATA", raising=False)
    paths = _norm(cb.candidate_paths())
    assert paths and not any("npm" in p for p in paths)


def test_claude_binary_prefers_configured_path(monkeypatch, tmp_path):
    exe = tmp_path / "my-claude"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CLI_PATH", str(exe))
    assert cb.claude_binary() == str(exe)


def test_claude_binary_ignores_missing_configured_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CLI_PATH", str(tmp_path / "missing"))
    monkeypatch.setattr(cb.shutil, "which", lambda name: "/on/path/claude")
    assert cb.claude_binary() == "/on/path/claude"


def test_claude_binary_falls_back_to_candidates(monkeypatch, tmp_path):
    found = tmp_path / "claude.cmd"
    found.write_text("", encoding="utf-8")
    monkeypatch.delenv("CLAUDE_CLI_PATH", raising=False)
    monkeypatch.setattr(cb.shutil, "which", lambda name: None)
    monkeypatch.setattr(cb, "candidate_paths", lambda: [tmp_path / "absent.exe", found])
    assert cb.claude_binary() == str(found)


def test_claude_binary_none_when_nowhere(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_CLI_PATH", raising=False)
    monkeypatch.setattr(cb.shutil, "which", lambda name: None)
    monkeypatch.setattr(cb, "candidate_paths", lambda: [tmp_path / "absent"])
    assert cb.claude_binary() is None


# --------------------------------------------------------------------------- #
# install_info, spawn_kwargs, kill_tree
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("platform,expected", [("win32", "windows"), ("darwin", "mac"), ("linux", "linux")])
def test_install_info(monkeypatch, platform, expected):
    monkeypatch.setattr(cb, "sys", _Proxy(sys, platform=platform))
    info = cb.install_info()
    assert info["platform"] == expected
    assert info["commands"] == {
        "windows": "irm https://claude.ai/install.ps1 | iex",
        "unix": "curl -fsSL https://claude.ai/install.sh | bash",
        "npm": "npm install -g @anthropic-ai/claude-code",
    }
    assert info["docs"] == "https://docs.claude.com/en/docs/claude-code/setup"


def test_spawn_kwargs_posix(monkeypatch):
    monkeypatch.setattr(cb, "os", _Proxy(os, name="posix"))
    assert cb.spawn_kwargs() == {"start_new_session": True}


def test_spawn_kwargs_windows(windows):
    kwargs = cb.spawn_kwargs()
    assert "start_new_session" not in kwargs
    assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW


class _Proc:
    def __init__(self, pid=4242, running=True):
        self.pid = pid
        self.returncode = None if running else 0
        self.killed = self.terminated = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True

    def terminate(self):
        self.terminated = True


def test_kill_tree_windows_uses_taskkill(windows):
    runs = []
    windows.setattr(cb.subprocess, "run", lambda args, **kw: runs.append((args, kw)) or mock.Mock(returncode=0))
    cb.kill_tree(_Proc(pid=777))
    assert runs and runs[0][0] == ["taskkill", "/PID", "777", "/T", "/F"]
    assert runs[0][1].get("capture_output") is True


def test_kill_tree_windows_falls_back_to_kill(windows):
    def boom(*a, **k):
        raise FileNotFoundError("taskkill")

    windows.setattr(cb.subprocess, "run", boom)
    proc = _Proc()
    cb.kill_tree(proc)
    assert proc.killed is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals (no SIGKILL on Windows)")
def test_kill_tree_posix_signals_the_group(monkeypatch):
    import signal

    monkeypatch.setattr(cb, "os", _Proxy(os, name="posix", killpg=lambda pid, sig: sent.append((pid, sig))))
    sent = []
    cb.kill_tree(_Proc(pid=55))
    cb.kill_tree(_Proc(pid=56), force=True)
    assert sent == [(55, signal.SIGTERM), (56, signal.SIGKILL)]


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals (no SIGKILL on Windows)")
def test_kill_tree_posix_fallback(monkeypatch):
    def boom(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(cb, "os", _Proxy(os, name="posix", killpg=boom))
    soft, hard = _Proc(), _Proc()
    cb.kill_tree(soft)
    cb.kill_tree(hard, force=True)
    assert soft.terminated and not soft.killed
    assert hard.killed


def test_kill_tree_leaves_a_finished_process_alone(windows):
    runs = []
    windows.setattr(cb.subprocess, "run", lambda *a, **k: runs.append(a))
    cb.kill_tree(_Proc(running=False))
    assert runs == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_kill_tree_really_stops_a_process_group():
    proc = subprocess.Popen(["sh", "-c", "sleep 30 & sleep 30; wait"], **cb.spawn_kwargs())
    try:
        cb.kill_tree(proc)
        assert proc.wait(timeout=5) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_only_kill_tree_calls_killpg():
    src = (cb.REPO_ROOT / "blueprints" / "claude_bridge.py").read_text(encoding="utf-8")
    assert src.count("killpg(") == 1
    assert "start_new_session=(os.name" not in src


def test_terminate_and_reap_go_through_kill_tree(monkeypatch):
    calls = []
    monkeypatch.setattr(cb, "kill_tree", lambda proc, force=False: calls.append(force))
    proc = mock.Mock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired("claude", 10), 0]
    cb._terminate(proc)
    cb._reap(proc)
    assert calls == [False, True]


# --------------------------------------------------------------------------- #
# parse_login_output (pure)
# --------------------------------------------------------------------------- #


def test_parse_real_cli_output():
    assert cb.parse_login_output(REAL_CLI_TEXT) == (REAL_URL, True)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", (None, False)),
        ("Opening browser to sign in...\n", (None, False)),
        ("See https://docs.claude.com/setup then https://claude.ai/oauth/x?y=1\n",
         ("https://claude.ai/oauth/x?y=1", False)),
        ("visit: https://console.anthropic.com/authorize?code=1\nPASTE CODE HERE >",
         ("https://console.anthropic.com/authorize?code=1", True)),
        ("http://claude.ai/oauth/authorize?x=1\n", (None, False)),
        ("Login successful.\n", (None, False)),
    ],
)
def test_parse_login_output_cases(text, expected):
    assert cb.parse_login_output(text) == expected


# --------------------------------------------------------------------------- #
# The /login endpoints
# --------------------------------------------------------------------------- #


class _Stdin:
    def __init__(self):
        self.written = []
        self.flushed = 0
        self.closed = False

    def write(self, text):
        if self.closed:
            raise ValueError("closed")
        self.written.append(text)
        return len(text)

    def flush(self):
        self.flushed += 1

    def close(self):
        self.closed = True


class FakePopen:
    instances: list[FakePopen] = []
    fail = False

    def __init__(self, args, **kwargs):
        if FakePopen.fail:
            raise OSError("cannot start")
        self.args = args
        self.kwargs = kwargs
        self.pid = 9000 + len(FakePopen.instances)
        self.returncode = None
        self.stdin = _Stdin()
        self.stdout = None
        self.waits = 0
        FakePopen.instances.append(self)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waits += 1
        return self.returncode

    def finish(self, code):
        self.returncode = code


@pytest.fixture
def login_env(tmp_path, monkeypatch):
    """A bridge app with a fake CLI, fake Popen and an open session check."""
    FakePopen.instances = []
    FakePopen.fail = False
    state = {"logged_in": False, "status_calls": []}

    def fake_status(force=False):
        state["status_calls"].append(force)
        return {
            "installed": True, "path": "/fake/claude", "version": "2.1.323",
            "logged_in": state["logged_in"], "auth_method": "oauth_token" if state["logged_in"] else None,
            "api_provider": None, "subscription": None,
            "plan": {"key": "max", "label": "Claude Max"} if state["logged_in"] else {"key": None, "label": None},
        }

    killed = []
    monkeypatch.setattr("utils.session.is_session_valid", lambda: True)
    monkeypatch.setattr(cb, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(cb, "LOGIN_LOG", tmp_path / "store" / "login.log")
    monkeypatch.setenv("BUCKLESON_DESK_DIR", str(tmp_path / "desk"))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cb, "claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(cb, "cli_status", fake_status)
    monkeypatch.setattr(cb, "kill_tree", lambda proc, force=False: killed.append(proc) or proc.finish(-15))
    monkeypatch.setattr(cb.subprocess, "Popen", FakePopen)
    monkeypatch.setattr("database.settings_db.get_analyze_mode", lambda: True)
    (tmp_path / "store").mkdir()

    saved = dict(cb._login)
    cb._login.clear()
    cb._login.update(proc=None, method=None, started=0.0)

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(cb.claude_bp)
    client = app.test_client()
    yield client, state, killed, tmp_path / "store" / "login.log"

    cb._login.clear()
    cb._login.update(saved)


def _cli_prints(log, text):
    log.write_text(text, encoding="utf-8")


def test_get_login_idle_by_default(login_env):
    client, *_ = login_env
    res = client.get("/claude/api/login")
    assert res.status_code == 200
    assert res.get_json() == {
        "status": "success",
        "login": {"state": "idle", "url": None, "needs_code": False, "method": None, "message": None},
    }


def test_post_login_starts_one_claudeai_process(login_env):
    client, *_ = login_env
    res = client.post("/claude/api/login", json={})
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "success"
    assert body["login"]["state"] == "starting"
    assert body["login"]["method"] == "claudeai"
    assert len(FakePopen.instances) == 1
    proc = FakePopen.instances[0]
    assert proc.args == ["/fake/claude", "auth", "login"]
    kw = proc.kwargs
    assert kw["stdin"] is subprocess.PIPE
    assert kw["stderr"] is subprocess.STDOUT
    assert kw["stdout"] not in (subprocess.PIPE, None)  # a file, never a pipe to drain
    assert kw.get("text") is True
    assert "CLAUDECODE" not in kw["env"]
    assert kw["cwd"] == str(cb.desk_dir())
    if os.name != "nt":
        assert kw.get("start_new_session") is True


def test_post_login_console_adds_flag(login_env):
    client, *_ = login_env
    res = client.post("/claude/api/login", json={"method": "console"})
    assert res.status_code == 200
    assert res.get_json()["login"]["method"] == "console"
    assert FakePopen.instances[0].args == ["/fake/claude", "auth", "login", "--console"]


@pytest.mark.parametrize("method", ["google", "CLAUDEAI ", 5])
def test_post_login_bad_method(login_env, method):
    client, *_ = login_env
    res = client.post("/claude/api/login", json={"method": method})
    assert res.status_code == 400
    assert res.get_json() == {"status": "error", "message": "Choose a Claude subscription or a Console account."}
    assert FakePopen.instances == []


def test_post_login_without_body_defaults_to_subscription(login_env):
    client, *_ = login_env
    res = client.post("/claude/api/login")
    assert res.status_code == 200
    assert FakePopen.instances[0].args == ["/fake/claude", "auth", "login"]


def test_post_login_twice_starts_no_second_process(login_env):
    client, _state, _killed, log = login_env
    client.post("/claude/api/login", json={"method": "claudeai"})
    _cli_prints(log, REAL_CLI_TEXT)
    res = client.post("/claude/api/login", json={"method": "console"})
    assert res.status_code == 200
    assert len(FakePopen.instances) == 1
    assert res.get_json()["login"]["state"] == "waiting"


def test_waiting_state_shows_the_link_and_code_prompt(login_env):
    client, _state, _killed, log = login_env
    client.post("/claude/api/login", json={})
    _cli_prints(log, REAL_CLI_TEXT)
    login = client.get("/claude/api/login").get_json()["login"]
    assert login == {"state": "waiting", "url": REAL_URL, "needs_code": True, "method": "claudeai", "message": None}


def test_waiting_without_code_prompt(login_env):
    client, _state, _killed, log = login_env
    client.post("/claude/api/login", json={})
    _cli_prints(log, "If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?x=1\n")
    login = client.get("/claude/api/login").get_json()["login"]
    assert login["state"] == "waiting" and login["needs_code"] is False


def test_post_login_already_signed_in_starts_nothing(login_env):
    client, state, *_ = login_env
    state["logged_in"] = True
    res = client.post("/claude/api/login", json={})
    assert res.status_code == 200
    assert res.get_json()["login"]["state"] == "connected"
    assert FakePopen.instances == []
    assert True in state["status_calls"]  # checked with force=True


def test_post_login_without_cli(login_env, monkeypatch):
    client, *_ = login_env
    monkeypatch.setattr(cb, "claude_binary", lambda: None)
    res = client.post("/claude/api/login", json={})
    assert res.status_code == 409
    body = res.get_json()
    assert body["status"] == "error"
    assert body["message"] == "Claude Code is not installed on this machine. Install it, then press Refresh."
    assert body["install"]["commands"]["npm"] == "npm install -g @anthropic-ai/claude-code"
    assert FakePopen.instances == []


def test_post_login_spawn_failure(login_env):
    client, *_ = login_env
    FakePopen.fail = True
    res = client.post("/claude/api/login", json={})
    assert res.status_code == 500
    assert res.get_json() == {
        "status": "error",
        "message": "Claude Code could not start the sign-in. Run claude auth login in a terminal instead.",
    }
    assert client.get("/claude/api/login").get_json()["login"]["state"] == "idle"


def test_exit_zero_and_signed_in_is_connected_and_sticky(login_env):
    client, state, _killed, log = login_env
    client.post("/claude/api/login", json={})
    _cli_prints(log, REAL_CLI_TEXT + "Login successful.\n")
    state["logged_in"] = True
    FakePopen.instances[0].finish(0)
    state["status_calls"].clear()
    login = client.get("/claude/api/login").get_json()["login"]
    assert login["state"] == "connected"
    assert True in state["status_calls"]
    proc = FakePopen.instances[0]
    assert proc.waits >= 1 and proc.stdin.closed
    # Still reported after the process is reaped, until the next POST or DELETE.
    assert client.get("/claude/api/login").get_json()["login"]["state"] == "connected"


def test_exit_zero_but_still_signed_out_is_failed(login_env):
    client, _state, _killed, _log = login_env
    client.post("/claude/api/login", json={})
    FakePopen.instances[0].finish(0)
    assert client.get("/claude/api/login").get_json()["login"]["state"] == "failed"


def test_exit_nonzero_is_failed_with_trader_message(login_env):
    client, *_ = login_env
    client.post("/claude/api/login", json={})
    FakePopen.instances[0].finish(1)
    login = client.get("/claude/api/login").get_json()["login"]
    assert login["state"] == "failed"
    assert login["message"] == "Sign-in did not finish. Press Connect Claude to try again."
    assert client.get("/claude/api/login").get_json()["login"]["state"] == "failed"


def test_after_failure_a_new_post_starts_again(login_env):
    client, *_ = login_env
    client.post("/claude/api/login", json={})
    FakePopen.instances[0].finish(1)
    client.get("/claude/api/login")
    res = client.post("/claude/api/login", json={})
    assert res.get_json()["login"]["state"] == "starting"
    assert len(FakePopen.instances) == 2


def test_login_expires(login_env, monkeypatch):
    client, _state, killed, log = login_env
    client.post("/claude/api/login", json={})
    _cli_prints(log, REAL_CLI_TEXT)
    monkeypatch.setattr(cb, "LOGIN_TIMEOUT_SECONDS", -1)
    login = client.get("/claude/api/login").get_json()["login"]
    assert login["state"] == "failed"
    assert login["message"] == "The sign-in link expired. Press Connect Claude to start again."
    assert killed == [FakePopen.instances[0]]


def test_submit_code_writes_to_stdin(login_env):
    client, _state, _killed, log = login_env
    client.post("/claude/api/login", json={})
    _cli_prints(log, REAL_CLI_TEXT)
    res = client.post("/claude/api/login/code", json={"code": "  abc#123  "})
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    stdin = FakePopen.instances[0].stdin
    assert stdin.written == ["abc#123\n"]
    assert stdin.flushed >= 1


@pytest.mark.parametrize("code", ["", "   ", "x" * 4001, None])
def test_submit_code_refuses_empty_or_huge(login_env, code):
    client, *_ = login_env
    client.post("/claude/api/login", json={})
    res = client.post("/claude/api/login/code", json={"code": code})
    assert res.status_code == 400
    assert res.get_json() == {"status": "error", "message": "Paste the code shown after you signed in."}
    assert FakePopen.instances[0].stdin.written == []


def test_submit_code_without_login(login_env):
    client, *_ = login_env
    res = client.post("/claude/api/login/code", json={"code": "abc"})
    assert res.status_code == 409
    assert res.get_json() == {"status": "error", "message": "No sign-in is in progress. Press Connect Claude first."}


def test_submit_code_after_process_ended(login_env):
    client, *_ = login_env
    client.post("/claude/api/login", json={})
    FakePopen.instances[0].finish(1)
    res = client.post("/claude/api/login/code", json={"code": "abc"})
    assert res.status_code == 409


def test_delete_login_stops_and_resets(login_env):
    client, _state, killed, log = login_env
    client.post("/claude/api/login", json={})
    _cli_prints(log, REAL_CLI_TEXT)
    res = client.delete("/claude/api/login")
    assert res.status_code == 200
    assert res.get_json() == {
        "status": "success",
        "login": {"state": "idle", "url": None, "needs_code": False, "method": None, "message": None},
    }
    assert killed == [FakePopen.instances[0]]
    assert client.get("/claude/api/login").get_json()["login"]["state"] == "idle"


def test_delete_with_nothing_running(login_env):
    client, _state, killed, _log = login_env
    res = client.delete("/claude/api/login")
    assert res.status_code == 200 and killed == []


def test_delete_clears_a_sticky_failure(login_env):
    client, *_ = login_env
    client.post("/claude/api/login", json={})
    FakePopen.instances[0].finish(1)
    client.get("/claude/api/login")
    client.delete("/claude/api/login")
    assert client.get("/claude/api/login").get_json()["login"]["state"] == "idle"


def test_login_endpoints_require_the_session(login_env, monkeypatch):
    client, *_ = login_env
    monkeypatch.setattr("utils.session.is_session_valid", lambda: False)
    for method, path in (("get", "/claude/api/login"), ("post", "/claude/api/login"),
                         ("delete", "/claude/api/login"), ("post", "/claude/api/login/code")):
        res = getattr(client, method)(path, json={}, headers={"Accept": "application/json"})
        assert res.status_code == 401, path
    assert FakePopen.instances == []


def test_status_includes_install_and_login(login_env, monkeypatch):
    client, *_ = login_env
    monkeypatch.setattr(cb, "_skills_installed", lambda: [])
    body = client.get("/claude/api/status").get_json()
    assert body["status"] == "success"
    assert body["install"]["platform"] in ("windows", "mac", "linux")
    assert body["login"]["state"] == "idle"
    assert body["cli"]["plan"] == {"key": None, "label": None}


# --------------------------------------------------------------------------- #
# chat: process start and one turn per conversation
# --------------------------------------------------------------------------- #


class _ChatProc:
    started: list = []

    def __init__(self, args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.pid = 1234
        self.returncode = None
        import io

        self.stdout = io.StringIO(json.dumps({"type": "result", "result": "ok", "session_id": "s"}) + "\n")
        _ChatProc.started.append(self)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


@pytest.fixture
def chat_env(login_env, monkeypatch):
    client, *_ = login_env
    _ChatProc.started = []
    monkeypatch.setattr(cb.subprocess, "Popen", _ChatProc)
    monkeypatch.setattr(cb, "_api_key", lambda: None)
    monkeypatch.setattr(cb, "CONVERSATIONS_FILE", cb.STORE_DIR / "conversations.json")
    saved = dict(cb._running)
    cb._running.clear()
    yield client
    cb._running.clear()
    cb._running.update(saved)


def test_chat_spawns_with_spawn_kwargs_posix(chat_env, monkeypatch):
    monkeypatch.setattr(cb, "os", _Proxy(os, name="posix"))
    res = chat_env.post("/claude/api/chat", json={"message": "hi", "conversation_id": "c1"})
    res.get_data()
    assert _ChatProc.started[0].kwargs.get("start_new_session") is True


def test_chat_spawns_with_spawn_kwargs_windows(chat_env, windows):
    res = chat_env.post("/claude/api/chat", json={"message": "hi", "conversation_id": "c2"})
    res.get_data()
    kw = _ChatProc.started[0].kwargs
    assert "start_new_session" not in kw
    assert kw["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP


def test_second_turn_on_a_busy_conversation_is_refused(chat_env):
    busy = mock.Mock()
    busy.poll.return_value = None
    cb._running["c3"] = busy
    res = chat_env.post("/claude/api/chat", json={"message": "again", "conversation_id": "c3"})
    assert res.status_code == 409
    assert "still answering" in res.get_json()["message"]
    assert _ChatProc.started == []


def test_a_finished_turn_does_not_block_the_next(chat_env):
    done = mock.Mock()
    done.poll.return_value = 0
    cb._running["c4"] = done
    res = chat_env.post("/claude/api/chat", json={"message": "next", "conversation_id": "c4"})
    assert res.status_code == 200
    res.get_data()
    assert len(_ChatProc.started) == 1


def test_chat_without_cli(chat_env, monkeypatch):
    monkeypatch.setattr(cb, "claude_binary", lambda: None)
    res = chat_env.post("/claude/api/chat", json={"message": "hi"})
    assert res.status_code == 409


def test_chat_empty_message(chat_env):
    res = chat_env.post("/claude/api/chat", json={"message": "   "})
    assert res.status_code == 400


# --------------------------------------------------------------------------- #
# heartbeats at the edge of the window
# --------------------------------------------------------------------------- #


@pytest.fixture
def external():
    saved = dict(cb._external)
    yield cb._external
    cb._external.clear()
    cb._external.update(saved)


def test_heartbeat_just_inside_window_is_connected(external):
    external["last_seen"] = time.time() - cb.HEARTBEAT_WINDOW_SECONDS + 5
    assert cb.external_status()["connected"] is True


def test_heartbeat_never_seen(external):
    external["last_seen"] = None
    status = cb.external_status()
    assert status["connected"] is False and status["last_seen"] is None
