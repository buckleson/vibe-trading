# Buckleson handoff

What Buckleson is, how the pieces fit, where each one lives, and how to run,
test and ship it. Read [ADR-001](ADR-001-zerodha-only-paper-claude.md) for why
it is shaped this way and [TODO.md](TODO.md) for the open work.

Repository: `github.com/buckleson/vibe-trading` (branch `main`), a fork of
OpenAlgo (`upstream` remote). Conventions are in the repository `CLAUDE.md`:
always `uv`, `logger = get_logger(__name__)`, never `print()`, no emojis
anywhere, Biome for TypeScript, Ruff for Python, Sandbox/analyzer wording
(never "paper trading" on a screen).

## How it fits together

```
Browser (React 19, frontend/)                 claude CLI (operator's plan)
   |  every request gets the operator               ^   stream-json over stdout
   |  session (utils/local_mode.py)                 |   MCP: mcp/mcpserver.py
   v                                                |
Flask app.py ---- blueprints/claude_bridge.py -----+   /claude/api/*
   |      \---- blueprints/* (orders, scalping, strategy_module, flow, tools, historify ...)
   |      \---- restx_api/  (/api/v1/*, API key in body)
   v
services/*  (place_order_service, history_service, ...)
   |  Sandbox (analyzer) mode ON  -> sandbox/ engine, db/sandbox.db
   |  Live mode (later, Zerodha)  -> broker/zerodha/
   v
broker/paper/  quotes, depth, history, master contract, streaming adapter
   Yahoo when reachable, deterministic simulator otherwise
```

- **Local mode** (`utils/local_mode.py`, wired in `app.py`): on startup creates
  the operator `buckleson`, an API key, a `paper` broker session and turns
  Sandbox mode on. `attach_operator_session()` runs before every browser
  request. Env: `BUCKLESON_LOCAL_MODE` (default true), `BUCKLESON_LOCAL_BROKER`
  (default `paper`), `BUCKLESON_LOCAL_USER`.
- **Paper broker** (`broker/paper/`): `api/data.py` (`BrokerData`: quotes,
  multiquotes, depth, history, intervals `1m 3m 5m 10m 15m 30m 1h D`),
  `api/market_data.py` (simulator, Yahoo client, sessions), `api/order_api.py`,
  `api/funds.py` (1 Crore), `database/` (master contract), `streaming/`
  (adapter registered as `paper`). Env: `PAPER_DATA_SOURCE` (`auto` | `yahoo` |
  `simulated`), `PAPER_MARKET_HOURS` (`always` | `exchange`; past-day history
  is always exchange sessions after T07).
- **Sandbox engine** (`sandbox/`, `services/sandbox_service.py`,
  `db/sandbox.db`): fills every order while analyzer mode is on. MIS is refused
  after 15:15 IST; CNC and NRML fill any time.
- **Zerodha** (`broker/zerodha/`): the only real broker plugin. Login starts at
  Select Broker (`/broker`), keys on Broker Configuration (`/broker/config`).
  Not used until the operator adds keys and leaves Sandbox mode.
- **Claude bridge** (`blueprints/claude_bridge.py`, prefix `/claude/api`):
  - `GET /status` CLI install/sign-in/plan, external MCP heartbeat, sandbox flag,
    market data source, skills, install help, current login flow.
  - `GET /connect` the `claude mcp add` command for a terminal session.
  - `POST /heartbeat` pinged by the MCP server.
  - `GET|DELETE /conversations[/<id>]`, `POST /chat` (SSE), `POST /chat/<id>/stop`.
  - `POST|GET|DELETE /login`, `POST /login/code` (one-click sign-in, T05).
  - The CLI runs in the desk workspace (`BUCKLESON_DESK_DIR`, default
    `~/.buckleson/desk`, seeded from `desk/`). Access levels: `trade` and `full`.
  - Frontend: `src/api/claude.ts`, `src/stores/claudeStore.ts`,
    `src/components/claude/{ClaudeChat,ClaudePanel,ConnectClaude}.tsx`,
    `src/pages/Claude.tsx`.
- **UI shell**: `src/components/layout/{Sidebar,Layout}.tsx`, groups in
  `src/config/navigation.ts` (`sidebarGroups`), pages in `src/pages/`.
- **Backtesting**: Portfolio and SIP backtesters (`portfolio/`, `sip/`,
  `restx_api/portfolio.py`, `restx_api/sip.py`), Sector Rotation
  (`services/sector_rotation_service.py`), Strategy Builder (option chain and
  greeks), the `/trading` chart backtest panel (client side over
  `/api/v1/history`), Python strategy backtests
  (`.claude/skills/python-strategy/backtest.py`), Historify downloads
  (`services/historify_service.py`, 1m and D storage). All read the paper
  broker through `services/history_service.py` (`source=api`) or Historify
  (`source=db`, needs a download first). The UI defaults to `api`.
- **Desk workspace for Claude** (`desk/CLAUDE.md`, `desk/.claude/skills/`),
  installed by `scripts/install_claude_skills.sh` or
  `scripts/windows/Install-Skills.ps1`.

## Where things live (after this run)

| Concern | Path |
| --- | --- |
| Broker plugins | `broker/paper/`, `broker/zerodha/` only |
| Broker list and keys | `utils/broker_keys.py` (`BROKER_NAMES`), `utils/broker_setup_guide.py` (`GUIDES`), `.sample.env` `VALID_BROKERS = 'paper,zerodha'` |
| Broker login | `utils/broker_login.py`, `blueprints/brlogin.py`, `blueprints/broker_config.py` |
| Websocket adapters | `websocket_proxy/__init__.py` (registers `zerodha`, `paper`) |
| Order update adapters | `services/order_update_service.py`, `blueprints/postback.py` (Zerodha only) |
| Page routes (Flask side) | `blueprints/react_app.py` |
| Page routes (React side) | `frontend/src/App.tsx` |
| Removed platforms | none left: tv_json, gc_json, chartink, platforms are deleted |
| Buckleson docs | `docs/buckleson/` |
| Windows packaging | `scripts/windows/package.ps1`, `Start-Buckleson.bat` |
| CI | `.github/workflows/windows.yml` |

## Run it

```bash
cd /home/user/openalgo
uv sync
cd frontend && npm ci && npm run build && cd ..
uv run app.py            # http://127.0.0.1:5000 opens on /dashboard
```

Restart after backend changes (dev container):

```bash
pkill -f "app.py"; sleep 2; cd /home/user/openalgo && (nohup script -qfc "uv run app.py" /dev/null > "$SCRATCH/app.log" 2>&1 &) ; until curl -s -o /dev/null http://127.0.0.1:5000/auth/session-status; do sleep 2; done; sleep 5
```

The REST API key of the operator, for curl probes:

```bash
uv run python -c "from database.auth_db import get_api_key_for_tradingview as k; print(k('buckleson'))"
```

On Windows: unzip `Buckleson-windows.zip` and run `Start-Buckleson.bat`.

Claude: install the CLI (`irm https://claude.ai/install.ps1 | iex` on Windows,
`curl -fsSL https://claude.ai/install.sh | bash` on macOS/Linux, or
`npm install -g @anthropic-ai/claude-code`), open `/claude`, press
**Connect Claude**.

## Test it

Baseline first. Before Wave 1, the test runner records the failing tests of
the untouched tree so "green" means "no new failures":

```bash
uv run pytest test -o addopts="" -q --timeout=120 -rf \
  --ignore-glob='test/test_gthread_*' > "$SCRATCH/baseline.txt" 2>&1
```

Per change:

```bash
uv run pytest <files> -o addopts="" -q --timeout=120 -rf
cd frontend && npx vitest run <paths> && npm run build
uv run ruff check <changed .py files>
cd frontend && npx biome check <changed .ts/.tsx files>
```

The Buckleson suites (all listed in `windows.yml` after T11):

| Suite | Covers |
| --- | --- |
| `test/test_paper_broker.py`, `test/test_paper_history_sessions.py` | paper broker, exchange-session history |
| `test/test_buckleson_bridge.py`, `test/test_claude_connect.py` | local mode, Claude bridge, plan detection, sign-in flow, Windows process handling |
| `test/test_zerodha_only.py` | R1: only paper and zerodha remain, zerodha imports |
| `test/test_platforms_removed.py` | R2: platform blueprints and routes are gone |
| `test/test_backtests_paper.py` | R4: portfolio, SIP, sector rotation, history on paper |
| `test/test_bk_sandbox_smoke.py` | R3: every order surface against a running server (skips when none is running) |
| `frontend: src/stores src/components/claude src/components/layout src/components/auth src/config src/pages/Trading.test.tsx src/pages/Positions.test.tsx` | UI |

Run the live smoke against the dev server:

```bash
BUCKLESON_SMOKE_URL=http://127.0.0.1:5000 uv run pytest test/test_bk_sandbox_smoke.py -o addopts="" -q
```

## Ship it

1. All suites above green, `npm run build` green.
2. Commit with Conventional Commits; never stage `frontend/dist/`
   (`git add -A -- . ':!frontend/dist'`).
3. Push to `origin main`; the Windows workflow tests and packages.
4. Tag `vX.Y.Z` to publish the zip as a release, with a `docs/CHANGELOG.md`
   stanza in the same change.

## Known limits

- Yahoo is blocked in the dev container, so every price there is simulated.
  On an operator machine with internet, `PAPER_DATA_SOURCE=auto` uses Yahoo.
- Simulated history: weekday sessions only; no exchange holidays, no corporate
  actions. Today's bars follow `PAPER_MARKET_HOURS`.
- Weekly and monthly history intervals are not offered by the paper broker;
  tools that resample do so from daily bars.
- Option coverage is NIFTY and BANKNIFTY only; stock options and MCX are not in
  the paper master contract.
- Sandbox refuses MIS after 15:15 IST. Use CNC or NRML outside market hours.
- Local mode trusts anyone who can reach the port. Keep the bind address
  127.0.0.1.
- Plan labels depend on what the installed `claude` reports; when it reports
  no plan the UI shows the auth method.
- Linux gthread/eventlet test jobs are not in CI (Windows only).
- 27 frontend tests in 7 files (SocketProvider, BrokerSelect, BrokerConfig,
  CandleViz, chartState, Diagnostics, webServerSummary) already failed before
  this run; they are left out of the CI test step, not fixed.

## Deliberately deferred

- **Zerodha MCP integration** (Kite MCP server or a Zerodha-backed toolset for
  Claude). Deferred until the operator moves to live trading. When it lands:
  add it as a second MCP server in `mcp_server_spec`/`write_mcp_config` in
  `blueprints/claude_bridge.py`, gate it on a Zerodha session, keep Sandbox as
  the default.
- Live trading on Zerodha: the plugin and login are kept and untested in this
  run beyond import.
- Exchange holiday calendar for the simulator.
- Any broker other than Zerodha (restore from upstream if ever needed).
