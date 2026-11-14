"""Claude Code bridge: talk to the operator's Claude Code agent from inside Buckleson.

Two ways Claude reaches the platform, and this blueprint shows both:

1. **In-app chat** (``POST /claude/api/chat``). The server runs the operator's
   own ``claude`` CLI in print mode with ``--output-format stream-json`` and
   streams every event back to the page as Server-Sent Events. The CLI is
   given the platform's MCP server (``mcp/mcpserver.py``) with the operator's
   API key, so it can read quotes, the order book, positions and funds and
   place orders. Conversations resume with ``--resume <session_id>``.
2. **External Claude Code** (a terminal on the same machine). ``GET
   /claude/api/connect`` returns the one-line ``claude mcp add`` command. The
   MCP server pings ``POST /claude/api/heartbeat`` on start and on every tool
   call, so the UI can show an external session as connected.

The CLI runs in a dedicated desk workspace (``BUCKLESON_DESK_DIR``, default
``~/.buckleson/desk``) seeded from ``desk/`` in this repository: its own
CLAUDE.md with the desk instructions and the installed web skills, and none of
this repository's developer instructions.

Sign-in: ``GET /claude/api/status`` reports the detected plan (Pro, Max, Team,
Enterprise, Console API key, Bedrock, Vertex) from ``claude auth status --json``
and the environment. ``POST /claude/api/login`` runs ``claude auth login`` in the
background, captures the sign-in link it prints into a log file, and the page
polls ``GET /claude/api/login`` until the CLI reports connected. Process
discovery and stopping work on Windows (claude.exe/claude.cmd, taskkill /T) and
on macOS/Linux (process groups).

Local-mode only by design: the routes require the operator's session, which
local mode gives every browser on the bound address.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request, session, stream_with_context

from utils import stream_registry
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

claude_bp = Blueprint("claude_bridge", __name__, url_prefix="/claude/api")

REPO_ROOT = Path(__file__).resolve().parent.parent
DESK_TEMPLATE = REPO_ROOT / "desk"
STORE_DIR = REPO_ROOT / "db" / "claude"
CONVERSATIONS_FILE = STORE_DIR / "conversations.json"
MCP_SERVER_NAME = "buckleson"

# Tools the agent may use without asking, per access level. Anything else is
# denied in print mode (there is nobody at a prompt to approve it).
WEB_SKILL_BASH = [
    "Bash(agent-reach:*)",
    "Bash(firecrawl:*)",
    "Bash(npx firecrawl:*)",
    "Bash(npx -y firecrawl-cli:*)",
    "Bash(curl:*)",
    "Bash(yt-dlp:*)",
    "Bash(gh:*)",
]
ACCESS_LEVELS: dict[str, dict[str, Any]] = {
    "trade": {
        "label": "Trade",
        "description": "Platform tools, web research and skills. No shell or file edits.",
        "allowed": [f"mcp__{MCP_SERVER_NAME}", "WebSearch", "WebFetch", "Read", "Glob", "Grep", "Skill", "TodoWrite", *WEB_SKILL_BASH],
        "permission_mode": "default",
    },
    "full": {
        "label": "Full access",
        "description": "Everything in Trade, plus shell commands and file edits in the desk workspace.",
        "allowed": [
            f"mcp__{MCP_SERVER_NAME}",
            "WebSearch",
            "WebFetch",
            "Read",
            "Glob",
            "Grep",
            "Skill",
            "TodoWrite",
            "Bash",
            "Edit",
            "Write",
            "NotebookEdit",
            "Task",
        ],
        "permission_mode": "acceptEdits",
    },
}

HEARTBEAT_WINDOW_SECONDS = 15 * 60
MAX_TURN_SECONDS = int(os.getenv("CLAUDE_BRIDGE_MAX_TURN_SECONDS", "900"))
STATUS_CACHE_SECONDS = 30
LOGIN_LOG = STORE_DIR / "login.log"
LOGIN_TIMEOUT_SECONDS = 600

_lock = threading.Lock()
_running: dict[str, subprocess.Popen] = {}
_status_cache: dict[str, Any] = {"at": 0.0, "value": None}
_login: dict[str, Any] = {"proc": None, "method": None, "started": 0.0}
_external: dict[str, Any] = {"last_seen": None, "last_tool": None, "calls": 0, "client": None}


# --------------------------------------------------------------------------- #
# Paths and the desk workspace
# --------------------------------------------------------------------------- #


def candidate_paths() -> list[Path]:
    """Places the CLI installers put ``claude`` when it is not on PATH."""
    if os.name == "nt":
        found: list[Path] = []
        profile, appdata = os.environ.get("USERPROFILE"), os.environ.get("APPDATA")
        if profile:
            found += [Path(profile) / ".local" / "bin" / "claude.exe", Path(profile) / ".claude" / "local" / "claude.exe"]
        if appdata:
            found += [Path(appdata) / "npm" / "claude.cmd", Path(appdata) / "npm" / "claude.exe"]
        return found
    return [
        Path.home() / ".claude" / "local" / "claude",
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]


def claude_binary() -> str | None:
    """Path of the operator's ``claude`` CLI, or None when it is not installed."""
    configured = os.getenv("CLAUDE_CLI_PATH", "").strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("claude")
    if found:
        return found
    for candidate in candidate_paths():
        if candidate.exists():
            return str(candidate)
    return None


def desk_dir() -> Path:
    """The desk workspace the CLI runs in, created from ``desk/`` on first use."""
    target = Path(os.getenv("BUCKLESON_DESK_DIR", str(Path.home() / ".buckleson" / "desk"))).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    if DESK_TEMPLATE.is_dir():
        for src in DESK_TEMPLATE.rglob("*"):
            rel = src.relative_to(DESK_TEMPLATE)
            dst = target / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            elif not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    return target


def host_url() -> str:
    return (os.getenv("HOST_SERVER") or "http://127.0.0.1:5000").strip().rstrip("/")


def _api_key() -> str | None:
    try:
        from utils.local_mode import LOCAL_USER, ensure_api_key

        user = session.get("user") or LOCAL_USER
        if user == LOCAL_USER:
            return ensure_api_key()
        from database.auth_db import get_api_key_for_tradingview

        return get_api_key_for_tradingview(user)
    except Exception:
        logger.exception("Could not read the operator API key for the Claude bridge")
        return None


IN_APP_CLIENT = "Buckleson app"


def mcp_server_spec(api_key: str, client: str | None = None) -> dict[str, Any]:
    """The stdio MCP server entry for the platform.

    ``client`` labels the heartbeats the server sends, so the in-app chat is not
    mistaken for a terminal session.
    """
    uv = shutil.which("uv")
    if uv:
        spec: dict[str, Any] = {
            "command": uv,
            "args": ["--directory", str(REPO_ROOT), "run", "--quiet", "mcp/mcpserver.py", api_key, host_url()],
        }
    else:
        python = REPO_ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        spec = {"command": str(python), "args": [str(REPO_ROOT / "mcp" / "mcpserver.py"), api_key, host_url()]}
    if client:
        spec["env"] = {"BUCKLESON_MCP_CLIENT": client}
    return spec


def write_mcp_config(api_key: str) -> Path:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = STORE_DIR / "mcp.json"
    payload = {"mcpServers": {MCP_SERVER_NAME: mcp_server_spec(api_key, IN_APP_CLIENT)}}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


# --------------------------------------------------------------------------- #
# Conversation store (a small JSON file; one operator)
# --------------------------------------------------------------------------- #


def _load_conversations() -> dict[str, Any]:
    try:
        return json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Could not read the Claude conversation store")
        return {}


def _save_conversations(data: dict[str, Any]) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONVERSATIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(CONVERSATIONS_FILE)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _append_items(conv_id: str, items: list[dict[str, Any]], *, title: str | None = None, session_id: str | None = None) -> None:
    with _lock:
        data = _load_conversations()
        conv = data.setdefault(conv_id, {"id": conv_id, "title": title or "New conversation", "created": _now(), "items": []})
        if title and conv.get("title") in (None, "", "New conversation"):
            conv["title"] = title
        if session_id:
            conv["session_id"] = session_id
        conv["items"].extend(items)
        conv["items"] = conv["items"][-400:]
        conv["updated"] = _now()
        _save_conversations(data)


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


def _run_quick(args: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=str(desk_dir()))
        return proc.returncode, (proc.stdout or proc.stderr or "").strip()
    except Exception as exc:
        return -1, str(exc)


PLAN_LABELS = {
    "pro": "Claude Pro",
    "max": "Claude Max",
    "team": "Claude Team",
    "enterprise": "Claude Enterprise",
    "free": "Claude Free",
}
PROVIDER_LABELS = {"bedrock": "Amazon Bedrock", "vertex": "Google Vertex AI", "foundry": "Microsoft Foundry"}


def _subscription_value(info: dict[str, Any], credentials: dict[str, Any]) -> str | None:
    oauth = credentials.get("claudeAiOauth")
    candidates = [info.get("subscriptionType"), info.get("subscription"), info.get("plan")]
    candidates.append(oauth.get("subscriptionType") if isinstance(oauth, dict) else None)
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def detect_plan(info: dict | None, environ: Mapping[str, str] | None = None, credentials: dict | None = None) -> dict[str, Any]:
    """Which Claude plan or auth method the CLI is using. Pure: no I/O."""
    info = info or {}
    environ = os.environ if environ is None else environ
    credentials = credentials or {}
    provider = info.get("apiProvider")
    if provider not in PROVIDER_LABELS:
        provider = next((name for name in PROVIDER_LABELS if environ.get(f"CLAUDE_CODE_USE_{name.upper()}") in ("1", "true")), None)
    if provider:
        return {"key": provider, "label": PROVIDER_LABELS[provider]}
    subscription = _subscription_value(info, credentials)
    if subscription:
        key = subscription.lower()
        return {"key": key, "label": PLAN_LABELS.get(key, "Claude " + key.title())}
    if info.get("authMethod") in ("api_key", "apiKey", "console") or (not info.get("loggedIn") and environ.get("ANTHROPIC_API_KEY")):
        return {"key": "api_key", "label": "Anthropic API key"}
    if info.get("loggedIn"):
        return {"key": "subscription", "label": "Claude subscription"}
    return {"key": None, "label": None}


def read_plan_credentials() -> dict[str, Any]:
    """The subscription type from the CLI's credentials file. Never returns a token."""
    base = os.getenv("CLAUDE_CONFIG_DIR", "").strip()
    path = (Path(base).expanduser() if base else Path.home() / ".claude") / ".credentials.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["claudeAiOauth"]["subscriptionType"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {"claudeAiOauth": {"subscriptionType": value}} if isinstance(value, str) else {}


def install_info() -> dict[str, Any]:
    """How to install the CLI, for the page to show when it is missing."""
    platform = {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux")
    return {
        "platform": platform,
        "commands": {
            "windows": "irm https://claude.ai/install.ps1 | iex",
            "unix": "curl -fsSL https://claude.ai/install.sh | bash",
            "npm": "npm install -g @anthropic-ai/claude-code",
        },
        "docs": "https://docs.claude.com/en/docs/claude-code/setup",
    }


def cli_status(force: bool = False) -> dict[str, Any]:
    """Whether the CLI is installed and signed in. Cached for a few seconds."""
    now = time.monotonic()
    if not force and _status_cache["value"] and now - _status_cache["at"] < STATUS_CACHE_SECONDS:
        return _status_cache["value"]
    binary = claude_binary()
    value: dict[str, Any] = {"installed": bool(binary), "path": binary, "version": None, "logged_in": False, "auth_method": None, "api_provider": None, "subscription": None, "plan": detect_plan(None, {})}
    info: dict[str, Any] = {}
    if binary:
        code, out = _run_quick([binary, "--version"], timeout=15)
        if code == 0:
            value["version"] = out.split()[0] if out else None
        code, out = _run_quick([binary, "auth", "status", "--json"], timeout=20)
        if code == 0:
            try:
                info = json.loads(out)
                value["logged_in"] = bool(info.get("loggedIn"))
                value["auth_method"] = info.get("authMethod")
                value["api_provider"] = info.get("apiProvider")
            except json.JSONDecodeError:
                info = {}
                value["logged_in"] = "logged in" in out.lower()
            if not isinstance(info, dict):
                info = {}
        elif os.getenv("ANTHROPIC_API_KEY"):
            value["logged_in"] = True
            value["auth_method"] = "api_key"
        credentials = read_plan_credentials()
        value["subscription"] = _subscription_value(info, credentials)
        value["plan"] = detect_plan(info, os.environ, credentials)
    _status_cache.update(at=now, value=value)
    return value


def external_status() -> dict[str, Any]:
    last = _external.get("last_seen")
    connected = bool(last) and (time.time() - last) < HEARTBEAT_WINDOW_SECONDS
    return {
        "connected": connected,
        "last_seen": datetime.fromtimestamp(last, UTC).isoformat() if last else None,
        "last_tool": _external.get("last_tool"),
        "calls": _external.get("calls", 0),
        "client": _external.get("client"),
    }


def _skills_installed() -> list[dict[str, str]]:
    skills = []
    for root in (desk_dir() / ".claude" / "skills", Path.home() / ".claude" / "skills"):
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            name, desc = skill_md.parent.name, ""
            try:
                lines = skill_md.read_text(encoding="utf-8")[:3000].splitlines()
                for idx, line in enumerate(lines):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
                        if desc in (">", "|", ">-", "|-"):
                            desc = " ".join(ln.strip() for ln in lines[idx + 1 : idx + 4] if ln.startswith("  "))
                        desc = desc[:200]
            except OSError:
                pass
            if not any(s["name"] == name for s in skills):
                skills.append({"name": name, "description": desc, "scope": "desk" if root.parent.parent == desk_dir() else "user"})
    return skills


def _market_data_status() -> dict[str, Any] | None:
    """Where the paper broker's prices come from (live Yahoo or simulated)."""
    if session.get("broker") != "paper":
        return None
    try:
        from broker.paper.api.data import data_source_status

        return data_source_status()
    except Exception:
        logger.debug("Paper data source status unavailable", exc_info=True)
        return None


@claude_bp.route("/status", methods=["GET"])
@check_session_validity
def status():
    cli = cli_status(force=request.args.get("refresh") == "1")
    with _lock:
        active = [cid for cid, p in _running.items() if p.poll() is None]
    from database.settings_db import get_analyze_mode

    return jsonify(
        {
            "status": "success",
            "cli": cli,
            "install": install_info(),
            "login": login_view(),
            "in_app": {"ready": cli["installed"] and cli["logged_in"], "running": active},
            "external": external_status(),
            "connected": (cli["installed"] and cli["logged_in"]) or external_status()["connected"],
            "sandbox": bool(get_analyze_mode()),
            "market_data": _market_data_status(),
            "desk_dir": str(desk_dir()),
            "skills": _skills_installed(),
            "access_levels": {k: {"label": v["label"], "description": v["description"]} for k, v in ACCESS_LEVELS.items()},
        }
    )


@claude_bp.route("/connect", methods=["GET"])
@check_session_validity
def connect_info():
    """Everything needed to connect an external Claude Code session."""
    api_key = _api_key()
    if not api_key:
        return jsonify({"status": "error", "message": "No API key yet. Generate one on the API Key page."}), 409
    spec = mcp_server_spec(api_key)
    cmd = " ".join([f"claude mcp add {MCP_SERVER_NAME} --scope user --", spec["command"], *[_shell_quote(a) for a in spec["args"]]])
    return jsonify(
        {
            "status": "success",
            "server_name": MCP_SERVER_NAME,
            "command": cmd,
            "mcp_json": {"mcpServers": {MCP_SERVER_NAME: spec}},
            "desk_dir": str(desk_dir()),
            "host": host_url(),
        }
    )


def _shell_quote(value: str) -> str:
    if value and all(c.isalnum() or c in "-_./:=@" for c in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


@claude_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    """Called by the MCP server: on start and on every tool call. Needs the API key."""
    payload = request.get_json(silent=True) or {}
    provided = payload.get("apikey") or request.headers.get("X-API-KEY")
    from database.auth_db import verify_api_key

    if not provided or not verify_api_key(provided):
        return jsonify({"status": "error", "message": "Invalid API key"}), 403
    if payload.get("client") == IN_APP_CLIENT:
        return jsonify({"status": "success"})
    _external["last_seen"] = time.time()
    _external["calls"] = int(_external.get("calls") or 0) + (1 if payload.get("tool") else 0)
    if payload.get("tool"):
        _external["last_tool"] = str(payload.get("tool"))[:80]
    _external["client"] = str(payload.get("client") or "Claude Code")[:80]
    try:
        from extensions import socketio

        socketio.emit("claude_status", {"external": external_status()})
    except Exception:
        logger.debug("Could not broadcast the Claude heartbeat", exc_info=True)
    return jsonify({"status": "success"})


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #


@claude_bp.route("/conversations", methods=["GET"])
@check_session_validity
def list_conversations():
    data = _load_conversations()
    rows = [
        {"id": c["id"], "title": c.get("title"), "updated": c.get("updated"), "created": c.get("created"), "turns": sum(1 for i in c.get("items", []) if i.get("role") == "user")}
        for c in data.values()
    ]
    rows.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return jsonify({"status": "success", "conversations": rows})


@claude_bp.route("/conversations/<conv_id>", methods=["GET"])
@check_session_validity
def get_conversation(conv_id: str):
    conv = _load_conversations().get(conv_id)
    if not conv:
        return jsonify({"status": "error", "message": "Conversation not found"}), 404
    return jsonify({"status": "success", "conversation": conv})


@claude_bp.route("/conversations/<conv_id>", methods=["DELETE"])
@check_session_validity
def delete_conversation(conv_id: str):
    with _lock:
        data = _load_conversations()
        data.pop(conv_id, None)
        _save_conversations(data)
    return jsonify({"status": "success"})


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #


def _system_prompt(sandbox: bool) -> str:
    mode = (
        "The platform is in SANDBOX mode: every order is simulated against live or simulated prices "
        "and no real money moves."
        if sandbox
        else "The platform is in LIVE mode: orders go to the real broker. Confirm intent before any order."
    )
    return (
        "You are the Buckleson desk agent, running inside the Buckleson trading app. "
        f"You are connected to the platform through the `{MCP_SERVER_NAME}` MCP server "
        "(quotes, depth, history, option chains, Greeks, funds, order book, trade book, positions, holdings, "
        "placing, modifying and cancelling orders). "
        f"{mode} "
        "Use strategy name 'claude' for orders you place. Before placing an order, state the symbol, exchange, "
        "side, quantity, product and price type in one line, then place it. Report the order id and fill. "
        "Symbols use the OpenAlgo format (RELIANCE on NSE, NIFTY on NSE_INDEX, NIFTY28NOV2524000CE on NFO). "
        "For news and web research use WebSearch/WebFetch or the installed skills (agent-reach, firecrawl). "
        "Keep answers short and scannable: tables for numbers, no filler."
    )


def _summarise_tool_result(content: Any) -> str:
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict)]
        content = "\n".join(parts)
    text = str(content or "")
    return text[:4000]


@claude_bp.route("/chat", methods=["POST"])
@check_session_validity
def chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "Type a message first."}), 400
    access = payload.get("access") if payload.get("access") in ACCESS_LEVELS else "trade"
    model = str(payload.get("model") or "").strip() or None
    conv_id = str(payload.get("conversation_id") or "") or uuid.uuid4().hex

    binary = claude_binary()
    if not binary:
        return jsonify({"status": "error", "message": "Claude Code is not installed on this machine. Install it, then press Refresh."}), 409

    with _lock:
        existing = _running.get(conv_id)
        if existing is not None and existing.poll() is None:
            return jsonify({"status": "error", "message": "Claude is still answering in this conversation. Stop it or wait."}), 409

    api_key = _api_key()
    conv = _load_conversations().get(conv_id) or {}
    resume_id = conv.get("session_id")

    from database.settings_db import get_analyze_mode

    sandbox = bool(get_analyze_mode())
    level = ACCESS_LEVELS[access]
    args = [
        binary,
        "-p",
        message,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--append-system-prompt",
        _system_prompt(sandbox),
        "--permission-mode",
        level["permission_mode"],
        "--allowedTools",
        ",".join(level["allowed"]),
    ]
    if api_key:
        args += ["--mcp-config", str(write_mcp_config(api_key))]
    if resume_id:
        args += ["--resume", resume_id]
    if model:
        args += ["--model", model]

    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    env["BUCKLESON_HOST"] = host_url()
    if api_key:
        env["BUCKLESON_API_KEY"] = api_key

    title = message[:60] + ("..." if len(message) > 60 else "")
    _append_items(conv_id, [{"role": "user", "text": message, "at": _now()}], title=title)

    try:
        proc = subprocess.Popen(
            args,
            cwd=str(desk_dir()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            **spawn_kwargs(),
        )
    except Exception:
        logger.exception("Could not start the Claude CLI")
        return jsonify({"status": "error", "message": "Claude Code could not be started. Check that it runs in a terminal on this machine."}), 500

    with _lock:
        _running[conv_id] = proc

    ticket = stream_registry.admit("claude_bridge_sse")

    def generate():
        assistant_text: list[str] = []
        tools: dict[str, dict[str, Any]] = {}
        items: list[dict[str, Any]] = []
        session_id = resume_id
        started = time.monotonic()
        try:
            yield _sse({"type": "bridge", "event": "started", "conversation_id": conv_id, "access": access, "sandbox": sandbox})
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    yield _sse({"type": "bridge", "event": "log", "text": line[:2000]})
                    continue
                etype = event.get("type")
                if etype == "system" and event.get("subtype") == "init":
                    session_id = event.get("session_id") or session_id
                elif etype == "assistant":
                    for block in (event.get("message") or {}).get("content") or []:
                        if block.get("type") == "text" and block.get("text"):
                            assistant_text.append(block["text"])
                        elif block.get("type") == "tool_use":
                            tools[block.get("id")] = {"role": "tool", "name": block.get("name"), "input": block.get("input"), "at": _now()}
                elif etype == "user":
                    for block in (event.get("message") or {}).get("content") or []:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tool = tools.get(block.get("tool_use_id"))
                            if tool is not None:
                                if assistant_text:
                                    items.append({"role": "assistant", "text": "\n\n".join(assistant_text), "at": _now()})
                                    assistant_text = []
                                tool["result"] = _summarise_tool_result(block.get("content"))
                                tool["is_error"] = bool(block.get("is_error"))
                                items.append(tool)
                elif etype == "result":
                    session_id = event.get("session_id") or session_id
                    if not assistant_text and event.get("result") and not any(i.get("role") == "assistant" for i in items):
                        assistant_text.append(str(event.get("result")))
                    items.append({"role": "meta", "cost_usd": event.get("total_cost_usd"), "duration_ms": event.get("duration_ms"), "turns": event.get("num_turns"), "is_error": event.get("is_error"), "at": _now()})
                yield _sse(event)
                if time.monotonic() - started > MAX_TURN_SECONDS:
                    yield _sse({"type": "bridge", "event": "timeout"})
                    _terminate(proc)
                    break
                if stream_registry.should_stop():
                    _terminate(proc)
                    break
            code = proc.wait(timeout=30)
            yield _sse({"type": "bridge", "event": "finished", "exit_code": code, "conversation_id": conv_id})
        except GeneratorExit:
            _terminate(proc)
            raise
        except Exception:
            logger.exception("Claude bridge stream failed")
            yield _sse({"type": "bridge", "event": "error", "text": "The Claude session ended unexpectedly. Try again."})
            _terminate(proc)
        finally:
            if assistant_text:
                meta = [i for i in items if i.get("role") == "meta"]
                items = [i for i in items if i.get("role") != "meta"] + [{"role": "assistant", "text": "\n\n".join(assistant_text), "at": _now()}] + meta
            try:
                _append_items(conv_id, items, session_id=session_id)
            except Exception:
                logger.exception("Could not save the Claude conversation")
            with _lock:
                if _running.get(conv_id) is proc:
                    _running.pop(conv_id, None)
            _reap(proc)
            if ticket is not None:
                ticket.release()

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    if ticket is not None:
        response.call_on_close(ticket.release)
    return response


@claude_bp.route("/chat/<conv_id>/stop", methods=["POST"])
@check_session_validity
def stop_chat(conv_id: str):
    with _lock:
        proc = _running.get(conv_id)
    if proc is None or proc.poll() is not None:
        return jsonify({"status": "success", "message": "Nothing running."})
    _terminate(proc)
    return jsonify({"status": "success", "message": "Stopped."})


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


def spawn_kwargs() -> dict[str, Any]:
    """Popen options that put the CLI in its own process group, per platform."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen, force: bool = False) -> None:
    """Stop the CLI and everything it started."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
    except Exception:
        try:
            proc.kill() if force or os.name == "nt" else proc.terminate()
        except Exception:
            logger.debug("Could not stop the Claude CLI process", exc_info=True)


def _terminate(proc: subprocess.Popen) -> None:
    kill_tree(proc)


def _reap(proc: subprocess.Popen) -> None:
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            kill_tree(proc, force=True)
            proc.wait(timeout=5)
        except Exception:
            logger.debug("Could not reap the Claude CLI process", exc_info=True)
    try:
        if proc.stdout:
            proc.stdout.close()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# One-click sign-in: ``claude auth login`` in the background
# --------------------------------------------------------------------------- #

IDLE_LOGIN = {"state": "idle", "url": None, "needs_code": False, "method": None, "message": None}


def parse_login_output(text: str) -> tuple[str | None, bool]:
    """The sign-in link the CLI printed, and whether it waits for a pasted code."""
    url = next((t for t in text.split() if t.startswith("https://") and ("oauth" in t or "authorize" in t)), None)
    return url, "paste code" in text.lower()


def _read_login_log() -> str:
    try:
        return LOGIN_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _finish_login(proc: subprocess.Popen, view: dict[str, Any]) -> dict[str, Any]:
    """Reap an ended login process and remember its outcome. Caller holds ``_lock``."""
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        logger.debug("Could not reap the Claude sign-in process", exc_info=True)
    _login.update(proc=None, result=view)
    return view


def login_view() -> dict[str, Any]:
    """Where the sign-in stands, for the page to poll."""
    with _lock:
        proc = _login.get("proc")
        method = _login.get("method")
        if proc is None:
            return dict(_login.get("result") or IDLE_LOGIN)
        code = proc.poll()
        if code is None:
            if time.time() - _login.get("started", 0.0) > LOGIN_TIMEOUT_SECONDS:
                kill_tree(proc)
                return _finish_login(proc, {**IDLE_LOGIN, "state": "failed", "method": method, "message": "The sign-in link expired. Press Connect Claude to start again."})
            url, needs_code = parse_login_output(_read_login_log())
            return {**IDLE_LOGIN, "state": "waiting" if url else "starting", "url": url, "needs_code": needs_code if url else False, "method": method}
        if code == 0:
            _status_cache.update(at=0.0, value=None)
            connected = cli_status(force=True)["logged_in"]
            message = None if connected else "Sign-in did not finish. Press Connect Claude to try again."
            return _finish_login(proc, {**IDLE_LOGIN, "state": "connected" if connected else "failed", "method": method, "message": message})
        return _finish_login(proc, {**IDLE_LOGIN, "state": "failed", "method": method, "message": "Sign-in did not finish. Press Connect Claude to try again."})


@claude_bp.route("/login", methods=["POST"])
@check_session_validity
def start_login():
    method = (request.get_json(silent=True) or {}).get("method") or "claudeai"
    if method not in ("claudeai", "console"):
        return jsonify({"status": "error", "message": "Choose a Claude subscription or a Console account."}), 400
    binary = claude_binary()
    if not binary:
        return jsonify({"status": "error", "message": "Claude Code is not installed on this machine. Install it, then press Refresh.", "install": install_info()}), 409
    if cli_status(force=True)["logged_in"]:
        return jsonify({"status": "success", "login": {**IDLE_LOGIN, "state": "connected", "method": method}})
    with _lock:
        running = _login.get("proc")
        if running is not None and running.poll() is None:
            pass
        else:
            running = None
    if running is not None:
        return jsonify({"status": "success", "login": login_view()})
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    try:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOGIN_LOG, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [binary, "auth", "login"] + (["--console"] if method == "console" else []),
                cwd=str(desk_dir()),
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                **spawn_kwargs(),
            )
    except Exception:
        logger.exception("Could not start the Claude sign-in")
        return jsonify({"status": "error", "message": "Claude Code could not start the sign-in. Run claude auth login in a terminal instead."}), 500
    with _lock:
        _login.update(proc=proc, method=method, started=time.time(), result=None)
    return jsonify({"status": "success", "login": login_view()})


@claude_bp.route("/login", methods=["GET"])
@check_session_validity
def get_login():
    return jsonify({"status": "success", "login": login_view()})


@claude_bp.route("/login/code", methods=["POST"])
@check_session_validity
def submit_login_code():
    code = str((request.get_json(silent=True) or {}).get("code") or "").strip()
    if not code or len(code) > 4000:
        return jsonify({"status": "error", "message": "Paste the code shown after you signed in."}), 400
    with _lock:
        proc = _login.get("proc")
        if proc is None or proc.poll() is not None or proc.stdin is None:
            proc = None
        else:
            try:
                proc.stdin.write(code + "\n")
                proc.stdin.flush()
            except OSError:
                logger.exception("Could not pass the sign-in code to Claude Code")
    if proc is None:
        return jsonify({"status": "error", "message": "No sign-in is in progress. Press Connect Claude first."}), 409
    return jsonify({"status": "success", "login": login_view()})


@claude_bp.route("/login", methods=["DELETE"])
@check_session_validity
def cancel_login():
    with _lock:
        proc = _login.get("proc")
        if proc is not None:
            kill_tree(proc)
            _finish_login(proc, dict(IDLE_LOGIN))
        _login.update(proc=None, method=None, started=0.0, result=None)
    return jsonify({"status": "success", "login": dict(IDLE_LOGIN)})
