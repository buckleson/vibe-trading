# Buckleson to-do sheet

Run plan for requirements R1 to R6. Decisions are in
[ADR-001](ADR-001-zerodha-only-paper-claude.md); the system map is in
[HANDOFF.md](HANDOFF.md).

## Requirements

| Id | Requirement |
| --- | --- |
| R1 | Only the `zerodha` and `paper` broker plugins remain; every other plugin and every reference to it is removed. App boots, zerodha imports. No Zerodha MCP now. |
| R2 | TradingView, GoCharting, Chartink and Platforms pages, routes, blueprints and their own database/services are removed. Kept: REST, Python strategies, Flow, Strategy module, Scalping, Tools, Historify, alerts, `/agent`, Claude bridge. |
| R3 | Sandbox trading works end to end on the paper broker from every surface: dashboard ticket, Positions close/close-all, Orderbook cancel/modify, Tradebook, option chain, scalping (NRML), Strategy module sandbox runs, Flow order nodes, REST, Claude (MCP). |
| R4 | Backtesting works on paper-broker history: Portfolio, SIP, Sector Rotation, Strategy Builder, `/trading` backtest panel, Python strategy backtests, Historify downloads. |
| R5 | Claude connects for any plan (Pro, Max, Team/Enterprise, Console key, Bedrock/Vertex); plan shown; one-click Connect when signed out; install help when missing; Windows and macOS/Linux. |
| R6 | Everything kept keeps working: `npm run build` green; tests for kept code green (no new failures against the baseline). |

## Roles and protocol

- **Orchestrator (Opus)** owns this sheet, assigns tasks, and plans fixes when a
  test fails.
- **Test author (Opus)** writes the test files named in each task from the
  task text alone, with edge cases, before or while the coder works.
- **Coders (Sonnet)**, one per task, change only their OWNED FILES. Two tasks in
  one wave never share a file. Anything outside your files that must change:
  stop and report it to the orchestrator; do not edit it.
- **Test runner (Haiku)** records the baseline before Wave 1, runs each task's
  tests after the coder finishes, and reports failures (test name, assertion,
  traceback head) to the orchestrator. A failing task is fixed before the next
  wave starts.
- Conventions: `uv` always, `get_logger`, `logger.exception` for errors, no
  `print`, no emojis, trader-facing messages (no status codes or exception
  names on screen), Sandbox wording, Ruff and Biome clean on changed files.
- Baseline command (test runner, before Wave 1):
  `uv run pytest test -o addopts="" -q --timeout=120 -rf --ignore-glob='test/test_gthread_*' > $SCRATCH/baseline.txt 2>&1`

Status values: `pending`, `in progress`, `done`, `blocked`.

## Board

| Id | Wave | Title | Owner | Req | Status |
| --- | --- | --- | --- | --- | --- |
| T01 | 1 | Remove broker plugins and their runtime registrations | Sonnet coder | R1 | done |
| T02 | 1 | Reduce broker login, keys, setup guide and env/install files to paper + zerodha | Sonnet coder | R1 | done |
| T03 | 1 | Frontend: remove broker login forms and platform pages | Sonnet coder | R1, R2 | done |
| T04 | 1 | Backend: remove TradingView, GoCharting, Chartink, Platforms | Sonnet coder | R2 | done |
| T05 | 1 | Claude bridge: plan detection, one-click sign-in, Windows processes | Sonnet coder | R5 | done |
| T06 | 1 | Claude UI: plan label, Connect Claude flow, install help | Sonnet coder | R5 | done |
| T07 | 2 | Paper history follows exchange sessions | Sonnet coder | R4 | done |
| T08 | 2 | Sandbox end to end on paper: backend surfaces and live smoke test | Sonnet coder | R3 | done |
| T09 | 2 | Sandbox end to end on paper: frontend order surfaces | Sonnet coder | R3 | done |
| T10 | 3 | Backtesting surfaces on paper history | Sonnet coder | R4 | done |
| T11 | 3 | CI, build, lint and docs consistency | Sonnet coder | R6 | done |

Removed broker names (37), used throughout: `aliceblue angel arrow
compositedge definedge deltaexchange dhan dhan_sandbox firstock fivepaisa
fivepaisaxts flattrade fyers groww hdfcsecurities hdfcsky ibulls iifl
iiflcapital indmoney jainamxts kotak motilal mstock nubra paytm pocketful
rmoney rupeezy sahi samco shoonya tradejini tradesmart upstox wisdom zebu`
(plus the stray `icici` branch in `brlogin.py`).

Rule for mixed tests (T01, T02, T04): a test that only uses a removed broker
name as an opaque string (for example `broker="angel"` in an auth row) and
still passes is left alone. A test that imports a removed module, or asserts a
removed registry entry, is retargeted to `zerodha` when the behaviour still
exists, otherwise that test function is deleted (the file too if nothing is
left).

---

## Wave 1: removals and Claude connect (parallel)

### T01. Remove broker plugins and their runtime registrations

- Owner: Sonnet coder. Status: pending. Requirement: R1.
- Owned files:
  - `broker/<each of the 37 removed names>/` (delete)
  - `websocket_proxy/__init__.py`, `websocket_proxy/server.py`
  - `services/order_update_service.py`, `blueprints/postback.py`
  - `services/option_chain_service.py`, `utils/position_read.py`,
    `utils/constants.py`, `blueprints/admin.py`, `database/auth_db.py`
  - `examples/python/broker_sdk_downloads.py` (delete)
  - Tests to delete: every `test/test_<removed>_*.py` (aliceblue, angel,
    definedge, dhan, firstock, fivepaisa, fivepaisaxts, flattrade, fyers, groww,
    hdfcsky, kotak, motilal, mstock_*, paytm, pocketful, rmoney, rupeezy, sahi,
    samco, shoonya, tradejini, tradesmart, upstox), `test/shoonya_getquotes_soak.py`,
    every `test/test_gthread_brokers_a_*.py` and `test_gthread_brokers_b_*.py`,
    `test/test_gthread_pocketful_connect.py`, `test/test_gthread_review_brokers.py`
  - Tests to update (mixed rule): `test_order_update_adapters.py`,
    `test_postback_sender_check.py`, `test_position_read_failure.py`,
    `test_websocket_unsubscribe_contract.py`, `test_margin_2156.py`,
    `test_smartorder_logic.py`, `test_mpp_slab_instrument_type.py`,
    `test_mstock.py`, `test_gthread_feed_waits_return_early.py`,
    `test_gthread_foundation_runtime.py`, `test_gthread_memory_streaming.py`,
    `test_gthread_rest_broker_busy.py`, `test_gthread_core_auth_cache.py`,
    `test_gthread_foundation_db.py`, `test_strategy_module_broker_binding.py`,
    `test_strategy_module_docs.py`, `test_pending_order_execution_service.py`,
    `test_cache_performance.py`, `test_eventlet_cross_thread_locks.py`,
    `test_http_protocol.py`, `test_broker_protocol.py`
  - New test (test author): `test/test_zerodha_only.py`
- Subtasks:
  - [ ] `git rm -r broker/<name>` for the 37 names; confirm `ls broker` shows only `__init__.py`, `paper`, `zerodha`.
  - [ ] `websocket_proxy/__init__.py`: delete every removed adapter import and `register_adapter(...)` line and the AliceBlue dynamic-load comments; keep `zerodha` and `paper` registrations and `__all__`.
  - [ ] `websocket_proxy/server.py`: drop the `["flattrade", "shoonya"]` keep-adapter branch (the code path for others stays); change the `VALID_BROKERS` fallback default from `"angel"` to `"paper"`.
  - [ ] `services/order_update_service.py`: reduce the adapter registry dict to `zerodha` (and nothing for paper unless it is already there).
  - [ ] `blueprints/postback.py`: `SUPPORTED_BROKERS = {"zerodha"}`; delete the dhan, fyers, upstox, angel, aliceblue mapper functions and their dispatch entries.
  - [ ] `services/option_chain_service.py`: delete the Fyers fast path (`if _broker == "fyers"` block and `used_fast_path` logic) so the generic path always runs.
  - [ ] `utils/position_read.py`: keep only `paper` and `zerodha` in the display-name map. `utils/constants.py`: `CRYPTO_BROKERS: set[str] = set()` (keep the name; crypto exchange constants stay).
  - [ ] `blueprints/admin.py`: `_BROKER_PROBE_HOSTS = {"zerodha": "api.kite.trade"}`.
  - [ ] `database/auth_db.py`: delete `_get_samco_auth`, `samco_save_secret_key`, `samco_get_ip_status`, `samco_save_ip_info`, `samco_has_secret_key`, `samco_get_secret_key`, `samco_has_registered_ip`; fix the docstring at about line 763 that names Samco. Do NOT drop Auth columns or `upgrade/migrate_samco_auth.py` (no schema change).
  - [ ] Delete and update the tests listed above using the mixed rule.
  - [ ] `grep -rnwE '<37 names>' --include=*.py websocket_proxy services blueprints/postback.py blueprints/admin.py utils/position_read.py utils/constants.py database/auth_db.py` returns nothing (comments naming a broker as an example may be changed to `zerodha`).
- Acceptance:
  - `ls broker` lists exactly `__init__.py paper zerodha` (plus `__pycache__`).
  - `uv run python -c "import broker.zerodha.api.auth_api, broker.zerodha.api.order_api, broker.zerodha.api.data, broker.zerodha.streaming.zerodha_adapter, broker.paper.api.data, websocket_proxy"` exits 0.
  - `set(websocket_proxy.broker_factory.BROKER_ADAPTERS) == {"zerodha", "paper"}` after importing `websocket_proxy`.
  - `blueprints.postback.SUPPORTED_BROKERS == {"zerodha"}`.
  - `test/test_zerodha_only.py`, `test/test_paper_broker.py` and every updated test file pass; no new failures against the baseline.
  - `uv run app.py` boots with `VALID_BROKERS='paper,zerodha'` and `/api/v1/funds` answers in Sandbox mode.

### T02. Reduce broker login, keys, setup guide and env/install files to paper + zerodha

- Owner: Sonnet coder. Status: pending. Requirement: R1.
- Owned files: `utils/broker_keys.py`, `utils/broker_setup_guide.py`,
  `utils/broker_login.py`, `blueprints/brlogin.py`, `blueprints/broker_config.py`,
  `blueprints/broker_credentials.py`, `utils/env_check.py`, `.sample.env`, `.env`,
  `start.sh`, `install/install.sh`, `install/install-docker.sh`,
  `install/install-multi.sh`, `install/install-docker-multi-custom-ssl.sh`,
  `install/docker-run.sh`, `install/docker-run.bat`, `docker-build.sh`,
  `docker-build.bat`; tests `test/test_broker_keys.py`, `test/test_index_symbols.py`,
  `test/test_gthread_rest_env_write.py`, `test/test_broker_callback_logging.py`,
  `test/test_broker_credential_logging.py`, `test/test_xts_credential_logging.py`,
  `test/test_auth_logout.py`, `test/test_auth_resume.py`,
  `test/test_auth_upsert_multisession.py`, `test/test_logout_csrf.py`,
  `test/test_orphaned_apikey.py`, `test/test_installer_worker_and_memory.py`.
- Subtasks:
  - [ ] `utils/broker_keys.py`: `BROKER_NAMES = {"paper": "Sandbox (No Broker)", "zerodha": "Zerodha"}`; `_KEY_FORMATS = {}` and keep `key_format_error` (it still has callers; with an empty table it returns None). Leave every function signature unchanged.
  - [ ] `utils/broker_setup_guide.py`: `GUIDES` keeps only `paper` and `zerodha`; `guide()` and `uses_redirect_url()` unchanged.
  - [ ] `utils/broker_login.py`: `BROKER_SITE_POST_BROKERS = frozenset()`, `CALLBACK_START_BROKERS = frozenset({"paper"})`, `STATE_BROKERS = frozenset({"zerodha"})`, `_STATE_CALLBACK_START_BROKERS = frozenset()`; `login_url()` keeps the CALLBACK_START branch, the zerodha branch and the final `/{broker}/callback` fallback; delete `xts_login_url` and every other branch (dhan, compositedge/rmoney, flattrade, fyers, upstox, arrow, rupeezy, hdfc*, paytm, pocketful). Update callers of `xts_login_url` (only in this file and brlogin).
  - [ ] `blueprints/brlogin.py`: in `_broker_callback` keep the session check, CSRF/pending-login checks, the `paper` branch, the generic `else` branch (Zerodha uses it: `request_token`), and the success path with the `zerodha` token prefix; delete every other `elif broker == ...` branch, the `("compositedge","rmoney","iiflcapital")` and `mstock` special cases, `_dhan_account_mismatch`, `_xts_account_mismatch`, `_refuse_xts_account`, the `/dhan/initiate-oauth`, `/samco/ip-status`, `/nubra/ip-status` routes and their helpers, and the feed-token/user_id broker list (Zerodha passes `feed_token=None`). Remove now-unused imports.
  - [ ] `blueprints/broker_config.py` and `blueprints/broker_credentials.py`: remove any per-broker special case for removed brokers (there may be none besides VALID_BROKERS docs); keep the API shapes of `GET /api/broker/list` unchanged.
  - [ ] `utils/env_check.py`: delete the fivepaisa, flattrade, dhan (and any other removed broker) API-key format branches around lines 1440 to 1500; the VALID_BROKERS check stays.
  - [ ] `.sample.env` and `.env`: `VALID_BROKERS = 'paper,zerodha'` (keep the comment above it, reworded to say only Sandbox and Zerodha are available). Do not touch any secret in `.env`.
  - [ ] `start.sh`: default `VALID_BROKERS` becomes `paper,zerodha`. Install scripts: reword the VALID_BROKERS comments; in `install/docker-run.sh` and `.bat` remove the XTS broker list echo lines; `docker-build.sh`/`.bat`: replace the fyers/angel callback hints with the zerodha one. Do not change nginx blocks.
  - [ ] Update the listed tests with the mixed rule; `test_broker_keys.py` enumerations become `{"paper", "zerodha"}`.
- Acceptance:
  - `set(utils.broker_keys.BROKER_NAMES) == {"paper", "zerodha"}` and `set(utils.broker_setup_guide.GUIDES) == {"paper", "zerodha"}`.
  - `utils.broker_login.login_url(keys_for("zerodha"), "s1")` starts with `https://kite.zerodha.com/connect/login?v=3&api_key=` and contains `redirect_params=state%3Ds1`; `login_url(keys_for("paper"), None) == "/paper/callback"`; `login_url` for any other name returns `/<name>/callback`.
  - `grep -nE "elif broker == \"(<37 names>|icici)\"" blueprints/brlogin.py` returns nothing; `/dhan/initiate-oauth` is not a registered rule.
  - `.sample.env`, `.env` and `start.sh` default all read `paper,zerodha`.
  - `GET /api/broker/list` (running app) lists exactly `paper` and `zerodha`.
  - Listed tests pass; no new failures against the baseline; app boots.

### T03. Frontend: remove broker login forms and platform pages

- Owner: Sonnet coder. Status: pending. Requirements: R1, R2.
- Owned files (frontend/src): `App.tsx`, `config/navigation.ts`,
  `config/navigation.test.ts`, `components/layout/Navbar.test.tsx`,
  `hooks/usePageTitle.ts`, `pages/Profile.tsx`, `stores/alertStore.ts`,
  `pages/BrokerSelect.tsx`, `lib/utils.ts`, `components/portfolio/SymbolSearchInput.tsx`,
  `pages/Home.tsx`, `pages/Faq.tsx`, `components/auth/LogoutConfirmDialog.tsx`;
  delete `pages/BrokerTOTP.tsx`, `pages/SamcoAuth.tsx`, `pages/Platforms.tsx`,
  `pages/TradingView.tsx`, `pages/GoCharting.tsx`, `pages/chartink/` (whole dir),
  `api/chartink.ts`, `types/chartink.ts`; new test (test author)
  `components/portfolio/SymbolSearchInput.test.tsx`.
- Subtasks:
  - [ ] `App.tsx`: remove the lazy imports and `<Route>`s for `BrokerTOTP` (`/broker/:broker/totp`, `/:broker/auth`), `SamcoAuth` (`/broker/samco/auth`), `Platforms` (`/platforms`), `TradingView` (`/tradingview`), `GoCharting` (`/gocharting`) and the four Chartink routes.
  - [ ] Delete the page, api and type files listed above.
  - [ ] `config/navigation.ts`: remove the `/platforms` item from `navItems` and the `Webhooks` (`/platforms`) item from the `Automate` sidebar group; keep imports that are still used (`Layers` is used by Holdings).
  - [ ] `navigation.test.ts` and `Navbar.test.tsx`: drop the Platforms expectations; the "Strategies after Platforms" assertion becomes "Strategies directly after Trading"; the More-menu list becomes `['Strategies', 'Logs', 'Tools']`.
  - [ ] `hooks/usePageTitle.ts`: remove `/platforms`, `/tradingview`, `/gocharting`, `/chartink*` entries and patterns.
  - [ ] `stores/alertStore.ts`: remove the `chartink` category key (type and default); `pages/Profile.tsx`: remove the Chartink alert category entry and the copy that names TradingView, Chartink or GoCharting.
  - [ ] `components/portfolio/SymbolSearchInput.tsx`: replace `chartinkApi.searchSymbols(q, exchange)` with a fetch of `/search/api/search?q=<q>&exchange=<exchange>` (credentials include, `Accept: application/json`), mapping `results[]` to `{symbol, name, exchange}`; same React Query key and debounce as today.
  - [ ] `pages/BrokerSelect.tsx`: delete the `dhan` note entry. `lib/utils.ts`: `makeFormatCurrency` always formats INR (drop the `deltaexchange` USD branch and its doc line; keep the signature).
  - [ ] Copy edits: `Home.tsx` (platform list and hero text), `Faq.tsx` (broker count and integrations answer), `LogoutConfirmDialog.tsx` ("External signals from TradingView, ChartInk" sentence becomes "Webhook and REST signals"). Name only Zerodha and the Sandbox.
- Acceptance:
  - `grep -rniE "chartink|gocharting|BrokerTOTP|SamcoAuth|/platforms" frontend/src` returns nothing.
  - `npx vitest run src/config src/components/layout src/components/portfolio src/pages/Profile.test.tsx src/pages/BrokerSelect.test.tsx` passes.
  - `npm run build` (tsc -b + vite) succeeds.
  - `SymbolSearchInput.test.tsx`: typing `REL` calls `/search/api/search?q=REL&exchange=NSE` and renders `RELIANCE`.

### T04. Backend: remove TradingView, GoCharting, Chartink, Platforms

- Owner: Sonnet coder. Status: pending. Requirement: R2 (also removes the R1 broker-form routes in `react_app.py`).
- Owned files: `app.py`, `blueprints/react_app.py`; delete `blueprints/tv_json.py`,
  `blueprints/gc_json.py`, `blueprints/chartink.py`, `blueprints/platforms.py`,
  `database/chartink_db.py`, `database/tv_search.py`; `utils/db_sessions.py`,
  `utils/shutdown.py`, `utils/url_redaction.py`, `upgrade/init_db.py`; tests: delete
  `test/test_gthread_hosts_chartink.py`; update `test_gthread_foundation_lifecycle.py`,
  `test_graceful_shutdown.py`, `test_gthread_core_shutdown.py`,
  `test_gthread_review_deploy.py`, `test_gthread_hosts_scheduler_jobs.py`,
  `test_gthread_hosts_eventlet.py`, `test_gthread_review_eventlet.py`,
  `test_logging_redaction.py`, `test_rate_limits_simple.py`,
  `test_rate_limits_mock.py`, `test_gthread_deploy_ci.py`; new test (test author)
  `test/test_platforms_removed.py`.
- Subtasks:
  - [ ] `app.py`: delete imports and `register_blueprint` of `tv_json_bp`, `gc_json_bp`, `platforms_bp`, `chartink_bp`; the `csrf.exempt(app.view_functions["chartink_bp.webhook"])` line; the `("Chartink DB", ensure_chartink_tables_exists)` init entry and its import.
  - [ ] Delete the six modules listed. `get_api_key_for_tradingview` in `database/auth_db.py` stays (many callers).
  - [ ] `blueprints/react_app.py`: delete views for `/platforms`, `/tradingview`, `/gocharting`, `/chartink`, `/chartink/new`, `/chartink/<int:strategy_id>`, `/chartink/<int:strategy_id>/configure`, `/broker/<broker>/totp`, `/broker/samco/auth`, `/<broker>/auth`. Keep `/broker` and `/broker/config`.
  - [ ] `utils/shutdown.py`: delete `_stop_chartink_scheduler` and its entry in the shutdown step list. `utils/db_sessions.py`: remove `("database.chartink_db", "db_session")`. `utils/url_redaction.py`: regex alternative becomes `(?:strategy|flow)`. `upgrade/init_db.py`: remove the Chartink DB import and entry.
  - [ ] Update the listed tests (drop chartink step names, chartink route rows, chartink import blocks); delete `test_gthread_hosts_chartink.py`. Leave `test_webhook_proxy_log_safety.py` and the installer nginx regex untouched.
  - [ ] Leave comments in `blueprints/strategy_module.py`/`flow.py` that mention `/chartink` as history only if T04 does not own them; report them, do not edit (they are harmless).
- Acceptance:
  - `uv run python -c "import app"` succeeds; `app.app.blueprints` has no `tv_json_bp`, `gc_json_bp`, `platforms_bp`, `chartink_bp`.
  - No URL rule starts with `/chartink`, `/tradingview`, `/gocharting`, `/platforms`; no rule `/broker/<broker>/totp` or `/<broker>/auth`.
  - `utils.shutdown` has no `_stop_chartink_scheduler`; `utils.url_redaction` still redacts `/strategy/webhook/<token>` and `/flow/webhook/<token>`.
  - `test/test_platforms_removed.py` and every updated test pass; no new failures against the baseline; the running app boots and `/dashboard` serves.

### T05. Claude bridge: plan detection, one-click sign-in, Windows processes

- Owner: Sonnet coder. Status: pending. Requirement: R5.
- Owned files: `blueprints/claude_bridge.py`; new test (test author)
  `test/test_claude_connect.py`; existing `test/test_buckleson_bridge.py` must stay green (coder may extend it).
- New and changed functions (exact signatures):
  - `def candidate_paths() -> list[Path]` POSIX: `~/.claude/local/claude`, `~/.local/bin/claude`, `/usr/local/bin/claude`, `/opt/homebrew/bin/claude`. Windows (`os.name == "nt"`): `%USERPROFILE%\.local\bin\claude.exe`, `%USERPROFILE%\.claude\local\claude.exe`, `%APPDATA%\npm\claude.cmd`, `%APPDATA%\npm\claude.exe` (skip any whose env var is unset).
  - `claude_binary()` keeps `CLAUDE_CLI_PATH` first, then `shutil.which("claude")` (PATHEXT finds `.exe`/`.cmd` on Windows), then `candidate_paths()`.
  - `def detect_plan(info: dict | None, environ: Mapping[str, str] | None = None, credentials: dict | None = None) -> dict` (pure, no I/O). Returns `{"key": str | None, "label": str | None}`. Order:
    1. provider: `info["apiProvider"]` in `bedrock|vertex|foundry`, or `environ["CLAUDE_CODE_USE_BEDROCK"|"CLAUDE_CODE_USE_VERTEX"|"CLAUDE_CODE_USE_FOUNDRY"]` truthy (`1`/`true`) gives key `bedrock` / `vertex` / `foundry`, label `Amazon Bedrock` / `Google Vertex AI` / `Microsoft Foundry`.
    2. subscription: first non-empty string of `info["subscriptionType"]`, `info["subscription"]`, `info["plan"]`, `credentials["claudeAiOauth"]["subscriptionType"]`; lower-cased; `pro`->`Claude Pro`, `max`->`Claude Max`, `team`->`Claude Team`, `enterprise`->`Claude Enterprise`, `free`->`Claude Free`; any other value `v` -> `"Claude " + v.title()`; key is the lower-cased value.
    3. API key: `info["authMethod"]` in (`api_key`, `apiKey`, `console`), or not `info.get("loggedIn")` while `environ["ANTHROPIC_API_KEY"]` is set, gives `{"key": "api_key", "label": "Anthropic API key"}`.
    4. `info.get("loggedIn")` true otherwise gives `{"key": "subscription", "label": "Claude subscription"}`.
    5. else `{"key": None, "label": None}`.
  - `def read_plan_credentials() -> dict` reads `$CLAUDE_CONFIG_DIR/.credentials.json` or `~/.claude/.credentials.json` and returns only `{"claudeAiOauth": {"subscriptionType": <str>}}` when present, else `{}`. Never returns or logs tokens. Missing or invalid file returns `{}`.
  - `cli_status()` adds keys `api_provider` (str|None), `subscription` (str|None, the raw subscription value used), `plan` (the `detect_plan` result). Existing keys unchanged.
  - `def install_info() -> dict` returns `{"platform": "windows"|"mac"|"linux", "commands": {"windows": "irm https://claude.ai/install.ps1 | iex", "unix": "curl -fsSL https://claude.ai/install.sh | bash", "npm": "npm install -g @anthropic-ai/claude-code"}, "docs": "https://docs.claude.com/en/docs/claude-code/setup"}`.
  - `def spawn_kwargs() -> dict`: Windows `{"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)}`, else `{"start_new_session": True}`. `chat()` uses it instead of `start_new_session=(os.name != "nt")`.
  - `def kill_tree(proc: subprocess.Popen, force: bool = False) -> None`: no-op if exited. Windows: `subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)`, falling back to `proc.kill()`. POSIX: `os.killpg(proc.pid, SIGKILL if force else SIGTERM)`, falling back to `proc.kill()`/`proc.terminate()`. `_terminate` calls `kill_tree(proc)`; `_reap` calls `kill_tree(proc, force=True)` after its wait times out.
  - Login state, module level under `_lock`: `_login = {"proc": None, "method": None, "started": 0.0}`; `LOGIN_LOG = STORE_DIR / "login.log"`; `LOGIN_TIMEOUT_SECONDS = 600`; `_LOGIN_URL = re.compile(r"https://\S+")`.
  - `def parse_login_output(text: str) -> tuple[str | None, bool]` (pure): returns (first `https://` URL whose text contains `oauth` or `authorize`, or None; True when the text contains `Paste code`, case-insensitive).
  - `def login_view() -> dict` returns `{"state": "idle"|"starting"|"waiting"|"connected"|"failed", "url": str|None, "needs_code": bool, "method": "claudeai"|"console"|None, "message": str|None}`: no process -> `idle`; running and no URL yet -> `starting`; running with URL -> `waiting`; running past `LOGIN_TIMEOUT_SECONDS` -> kill, `failed`, message `The sign-in link expired. Press Connect Claude to start again.`; exited 0 -> clear `_status_cache`, `cli_status(force=True)`, `connected` if `logged_in` else `failed`; exited non-zero -> `failed`, message `Sign-in did not finish. Press Connect Claude to try again.`. An exited process is reaped (`wait`) and its stdin closed.
- New endpoints (all `@check_session_validity`, JSON):
  - `POST /claude/api/login` body `{"method": "claudeai"|"console"}` (default `claudeai`; anything else -> 400 `{"status":"error","message":"Choose a Claude subscription or a Console account."}`). CLI missing -> 409 `{"status":"error","message":"Claude Code is not installed on this machine. Install it, then press Refresh.","install": install_info()}`. Already signed in (`cli_status(force=True)["logged_in"]`) -> 200 with `login.state == "connected"`. Login already running -> 200 with current `login_view()` (no second process). Otherwise start `[binary, "auth", "login"] + (["--console"] if console else [])` with `cwd=desk_dir()`, `stdin=PIPE`, `stdout` = `LOGIN_LOG` opened `"w"` (closed in the parent right after Popen), `stderr=STDOUT`, `text=True`, env without `CLAUDECODE`, `**spawn_kwargs()`. Response 200 `{"status":"success","login": login_view()}`. Spawn failure -> 500 `{"status":"error","message":"Claude Code could not start the sign-in. Run claude auth login in a terminal instead."}`, logged with `logger.exception`.
  - `GET /claude/api/login` -> 200 `{"status":"success","login": login_view()}`.
  - `POST /claude/api/login/code` body `{"code": str}`: strip; empty or longer than 4000 chars -> 400 `{"status":"error","message":"Paste the code shown after you signed in."}`; no running login -> 409 `{"status":"error","message":"No sign-in is in progress. Press Connect Claude first."}`; else write `code + "\n"` to stdin, flush; 200 `{"status":"success","login": login_view()}`.
  - `DELETE /claude/api/login` -> kill the process tree if running, reset state; 200 `{"status":"success","login": {"state":"idle","url":null,"needs_code":false,"method":null,"message":null}}`.
  - `GET /claude/api/status` gains top-level `"install": install_info()` and `"login": login_view()`; `cli` gains `plan`, `api_provider`, `subscription`.
- Subtasks:
  - [ ] Add `candidate_paths`, extend `claude_binary`.
  - [ ] Add `detect_plan`, `read_plan_credentials`; extend `cli_status`.
  - [ ] Add `install_info`, `spawn_kwargs`, `kill_tree`; route `chat()`, `_terminate`, `_reap` through them (remove direct `os.killpg` calls elsewhere).
  - [ ] Add `parse_login_output`, `login_view` and the four login endpoints; extend `status()`.
  - [ ] Update the module docstring with the login flow and Windows notes.
- Acceptance:
  - `detect_plan({"loggedIn": True, "authMethod": "oauth_token", "subscriptionType": "max"}) == {"key": "max", "label": "Claude Max"}`; `detect_plan({"loggedIn": True, "apiProvider": "bedrock"})["label"] == "Amazon Bedrock"`; `detect_plan({"loggedIn": False}, {"ANTHROPIC_API_KEY": "x"})["key"] == "api_key"`; `detect_plan({"loggedIn": True, "authMethod": "oauth_token"}, {}, {"claudeAiOauth": {"subscriptionType": "team"}})["label"] == "Claude Team"`; `detect_plan(None) == {"key": None, "label": None}`.
  - `parse_login_output` on the real CLI output (`Opening browser...\nIf the browser didn't open, visit: https://claude.com/cai/oauth/authorize?...\nPaste code here if prompted >`) returns that URL and True.
  - With `subprocess.Popen` mocked: POST `/login` starts exactly one process with `auth login` (and `--console` for console); a second POST does not start another; POST `/login/code` writes `code\n` to stdin; DELETE calls `kill_tree`; exit code 0 plus `logged_in` gives `connected`.
  - With `os.name` patched to `nt`: `kill_tree` runs `taskkill /PID <pid> /T /F`; `spawn_kwargs()` has `creationflags` and no `start_new_session`; `candidate_paths()` includes `%APPDATA%\npm\claude.cmd`.
  - `read_plan_credentials()` on a file holding `accessToken` returns a dict with no `accessToken` anywhere.
  - `test/test_claude_connect.py` and `test/test_buckleson_bridge.py` pass; against the running app `GET /claude/api/status` returns `cli.plan.label` non-empty when signed in.

### T06. Claude UI: plan label, Connect Claude flow, install help

- Owner: Sonnet coder. Status: pending. Requirement: R5.
- Owned files (frontend/src): `api/claude.ts`, `stores/claudeStore.ts`,
  `stores/claudeStore.test.ts`, `components/claude/ConnectClaude.tsx` (new),
  `components/claude/ClaudePanel.tsx`, `pages/Claude.tsx`; new test (test author)
  `components/claude/ConnectClaude.test.tsx`.
- Contract: the T05 endpoints and shapes above.
- Subtasks:
  - [ ] `api/claude.ts`: add `export interface ClaudePlan { key: string | null; label: string | null }`; extend `ClaudeCliStatus` with `plan: ClaudePlan; api_provider: string | null; subscription: string | null`; add `export type ClaudeLoginState = { state: 'idle' | 'starting' | 'waiting' | 'connected' | 'failed'; url: string | null; needs_code: boolean; method: 'claudeai' | 'console' | null; message: string | null }`; add `export interface ClaudeInstallInfo { platform: 'windows' | 'mac' | 'linux'; commands: { windows: string; unix: string; npm: string }; docs: string }`; extend `ClaudeStatus` with `install: ClaudeInstallInfo; login: ClaudeLoginState`. Add to `claudeApi`: `startLogin(method: 'claudeai' | 'console' = 'claudeai')` (POST `/claude/api/login`), `loginStatus()` (GET), `submitLoginCode(code: string)` (POST `/claude/api/login/code`), `cancelLogin()` (DELETE); each resolves to `ClaudeLoginState` (the `login` field) and rejects with the server `message` on error.
  - [ ] `stores/claudeStore.ts`: add state `login: ClaudeLoginState | null` and actions `startLogin(method?)`, `pollLogin()`, `submitLoginCode(code)`, `cancelLogin()`; `refreshStatus` also copies `status.login` into `login`; when a poll returns `connected`, call `refreshStatus(true)`. Errors go to a `loginError: string | null` field shown by the component.
  - [ ] `components/claude/ConnectClaude.tsx`: `export function ConnectClaude({ compact = false }: { compact?: boolean })`. Renders nothing when `status.cli.installed && status.cli.logged_in`. CLI missing: heading "Install Claude Code", the command for `status.install.platform` (Windows -> `commands.windows`, else `commands.unix`) and the npm alternative, each in a copy block, plus a Refresh button calling `refreshStatus(true)`. Signed out, `login` idle/failed: primary button "Connect Claude" (`startLogin('claudeai')`), secondary link button "Use a Console API account" (`startLogin('console')`), and `login.message` when failed. `starting`: spinner "Starting sign-in...". `waiting`: link "Open the sign-in page" (`href=login.url`, `target="_blank"`, `rel="noopener noreferrer"`), text "Sign in with the account that has your Claude plan.", and when `needs_code` an input labelled "Sign-in code" with a "Submit code" button; a "Cancel" button. While `starting` or `waiting`, poll `pollLogin()` every 2000 ms (clear the interval on unmount and on any other state).
  - [ ] `pages/Claude.tsx`: the "Signed in" row shows `cli.plan.label ?? cli.auth_method ?? 'yes'` when signed in; replace the two hint paragraphs (not installed, signed out) with `<ConnectClaude />`.
  - [ ] `components/claude/ClaudePanel.tsx`: `useClaudeState` connected detail becomes `${cli.plan?.label ?? 'Claude Code'} · v${cli.version}` (keep the terminal-session suffix); signed-out detail `Press Connect Claude`; render `<ConnectClaude compact />` in the panel body when the state is `signed-out` or `missing`. Keep the exported names `useClaudeState`, `StatusDot`, `ClaudeState` (Sidebar and Claude page import them).
  - [ ] `claudeStore.test.ts`: cover `startLogin`, `pollLogin` to `connected` triggering `refreshStatus(true)`, and `loginError` on rejection.
- Acceptance:
  - `npx vitest run src/stores src/components/claude src/components/layout` passes; `npm run build` passes; Biome clean on changed files.
  - `ConnectClaude.test.tsx`: missing CLI on Windows shows `irm https://claude.ai/install.ps1 | iex`; signed out shows "Connect Claude" and clicking it POSTs `/claude/api/login` with `{"method":"claudeai"}`; `waiting` renders a link with the URL and `target="_blank"`; `needs_code` shows the code input and submit POSTs `/claude/api/login/code`; `connected` renders nothing; the poll interval is cleared on unmount.
  - With the running app signed in, `/claude` shows the plan label (for example "Claude subscription" in this container).

---

## Wave 2: Sandbox and data correctness (parallel, after Wave 1)

### T07. Paper history follows exchange sessions

- Owner: Sonnet coder. Status: pending. Requirement: R4.
- Owned files: `broker/paper/api/market_data.py`, `test/test_paper_broker.py`,
  `.sample.env` (the `PAPER_MARKET_HOURS` comment only); new test (test author)
  `test/test_paper_history_sessions.py`.
- Problem: with `PAPER_MARKET_HOURS=always` (default) simulated history includes
  Saturday/Sunday daily bars and 24-hour intraday bars, so backtests annualise
  over 365 sessions and SIPs land on Sundays.
- Subtasks:
  - [ ] Add `def _history_session(day, today) -> tuple[float, float] | None`: for `day < today` return the exchange session (weekday only, `SESSION_OPEN` IST plus `SESSION_SECONDS`, None on Saturday/Sunday) regardless of `_hours_setting()`; for `day >= today` return `_session(day)`.
  - [ ] `_session_starts(start, end, seconds, now)` and the daily branch of `_sim_spot_history` use `_history_session(day, today)` with `today = datetime.fromtimestamp(now, inst.IST).date()`.
  - [ ] Intraday volume: use `SESSION_SECONDS` as the day length for bars of past days and the current setting for today (spot and derivative branches of `history()`).
  - [ ] Leave the Yahoo path, `snapshot`, `market_time` and live quotes unchanged.
  - [ ] Update the `.sample.env` comment: `PAPER_MARKET_HOURS` affects live quotes and today's bars; past history always follows exchange sessions.
  - [ ] Update any assertion in `test/test_paper_broker.py` that expected weekend or night bars.
- Acceptance:
  - Daily history for RELIANCE NSE from 2023-01-01 to 2023-01-15 has 10 bars, none on Saturday or Sunday (UTC date of the stamp), with `PAPER_MARKET_HOURS` set to `always` and to `exchange`.
  - 1h history for a past weekday has bars only between 09:15 and 15:30 IST; a past Saturday returns no bars.
  - Today's intraday bars under `always` may start at 00:00 IST (continuity with live quotes); under `exchange` they start at 09:15.
  - Option and future history inherit the weekday rule (NIFTY option daily history has no weekend bars).
  - Results stay deterministic: two calls with the same arguments return identical frames.
  - `test/test_paper_broker.py` and `test/test_paper_history_sessions.py` pass.

### T08. Sandbox end to end on paper: backend surfaces and live smoke test

- Owner: Sonnet coder. Status: pending. Requirement: R3.
- Owned files: `blueprints/orders.py`, `blueprints/scalping.py`,
  `blueprints/dashboard.py`, `blueprints/strategy_module.py`, `blueprints/flow.py`,
  `services/strategy_module/` (dir), `services/flow_executor_service.py`,
  `services/flow_openalgo_client.py`, `sandbox/` (dir), `services/place_order_service.py`,
  `services/place_options_order_service.py`, `services/close_position_service.py`,
  `services/cancel_order_service.py`, `services/cancel_all_order_service.py`,
  `services/modify_order_service.py`, `mcp/mcpserver.py`; new test (written by the
  coder with the test author) `test/test_live_sandbox_smoke.py`.
- Live smoke test design: module skips unless `GET $BUCKLESON_SMOKE_URL/auth/session-status`
  (default `http://127.0.0.1:5000`, timeout 3 s) answers 200. A `requests.Session`
  gets the operator session for free (local mode); CSRF from `GET /auth/csrf-token`
  (`csrf_token`) sent as `X-CSRFToken`; API key from `GET /apikey` with
  `Accept: application/json` (`api_key`). Use CNC/NRML only (MIS is refused after
  15:15 IST). Each test cleans up its own orders and positions.
- Subtasks (each one a test in the smoke file, then fix what fails in owned files):
  - [ ] REST: `placeorder` CNC MARKET SBIN fills; LIMIT far from market -> `modifyorder` -> `cancelorder`; `orderbook`, `tradebook`, `positionbook`, `funds` all `status: success` with `mode: analyze`.
  - [ ] Options: `expiry` for NIFTY NFO -> `optionchain` with `expiry_date` -> `optionsorder` ATM CE BUY NRML 1 lot fills; `closeposition` closes it.
  - [ ] Session endpoints the UI calls: `POST /close_position` (one symbol), `POST /close_all_positions`, `POST /cancel_order`, `POST /modify_order`, `POST /cancel_all_orders` with CSRF; each returns success and the book reflects it.
  - [ ] Scalping: `GET /scalping/api/underlyings`, `/expiry`, `/strikes` for NIFTY; `POST /scalping/api/order` NRML BUY CE fills; `/close_all` flattens; `/cancel_all` succeeds.
  - [ ] Strategy module: create a `batch` strategy in Sandbox run mode on NIFTY options via `POST /strategy/api/strategies`, `start`, confirm legs open in `/positions`, `close_all`, `stop`, delete.
  - [ ] Flow: create a workflow (start -> place order node CNC SBIN), `POST /flow/api/workflows/<id>/execute`, confirm an analyzer order and the execution record; delete the workflow.
  - [ ] Claude MCP path: call the MCP tool functions in `mcp/mcpserver.py` (`place_order`, `get_order_book`, `get_position_book`, `close_all_positions`) with `BUCKLESON_HOST`/API key pointing at the running server; each returns success in analyze mode.
  - [ ] For every failure: fix the root cause in an owned file with a unit test beside it; a failure inside `broker/paper/` or Wave 1 files is reported to the orchestrator, not edited.
- Acceptance:
  - `BUCKLESON_SMOKE_URL=http://127.0.0.1:5000 uv run pytest test/test_live_sandbox_smoke.py -o addopts="" -q` passes against the dev server, outside market hours.
  - The same file reports all tests skipped when no server is reachable (CI-safe).
  - No order reaches a live broker (every response carries `mode: analyze`).
  - Existing strategy module, flow and sandbox tests for the files changed still pass.

- Attempt 1 (failed): `BUCKLESON_SMOKE_URL=http://127.0.0.1:5000 uv run pytest test/test_bk_sandbox_smoke.py -o addopts="" -q`
  gave 29 passed, 2 failed. All order surfaces (REST, options, session
  endpoints, scalping, Strategy module, Flow, MCP) pass in analyze mode. The smoke
  file is `test/test_bk_sandbox_smoke.py` driving `scripts/bk_smoke.py` (accepted
  in place of `test/test_live_sandbox_smoke.py`).
  - `Sector Rotation on paper`: 12 default sectors not placed (NIFTYAUTO ...
    NIFTYREALTY). Root cause (code): `broker/paper/database/instruments.py`
    `INDICES` holds only NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50,
    NIFTYIT, INDIAVIX, SENSEX, BANKEX, so the other sector indices are not in the
    paper master contract and history refuses them. The NIFTY500 benchmark and
    the 4 optional sectors fail the same way.
  - `Historify download`: weekend rows 2026-09-13/19/20. Root cause (test
    state): the paper history API no longer returns weekend bars (T07), but
    Historify still holds RELIANCE:NSE:D rows stored by an earlier pre-T07 run,
    and `upsert_market_data` never removes rows. The check does not start from
    a clean slate.
- Fix plan (attempt 2):
  - [ ] Add 17 entries to paper `INDICES` (12 default `SECTORS`, 4
    `OPTIONAL_SECTORS`, `NIFTY500` benchmark) with NSE display names, reference
    prices and Yahoo tickers.
  - [ ] Unit test in `test/test_paper_broker.py`: every symbol in
    `sector_rotation_service.SECTORS`, `OPTIONAL_SECTORS` and `BENCHMARKS` is
    in `inst.build_instruments(...)` on its exchange.
  - [ ] `scripts/bk_smoke.py` `check_historify_download`: DELETE
    `/historify/api/delete` (JSON body symbol/exchange/interval, CSRF) before the
    download; `session_delete` gains an optional JSON payload.
  - [ ] Restart the app, force a master contract download, rerun the smoke file.

### T09. Sandbox end to end on paper: frontend order surfaces

- Owner: Sonnet coder. Status: pending. Requirement: R3.
- Owned files (frontend/src): `pages/Dashboard.tsx`, `pages/Positions.tsx`,
  `pages/OrderBook.tsx`, `pages/TradeBook.tsx`, `pages/OptionChain.tsx`,
  `pages/Scalping.tsx`, `components/scalping/` (dir), `components/trading/PlaceOrderDialog.tsx`,
  `components/trading/PlaceOrderDialog.test.tsx`, `pages/Positions.test.tsx`,
  `api/trading.ts`; new test (test author) `pages/OrderSurfaces.test.tsx`.
- Subtasks:
  - [ ] Dashboard ticket (`PlaceOrderDialog`): default product is CNC for NSE/BSE equities and NRML for NFO/BFO; MIS remains selectable. The server sentence for a refused MIS after 15:15 is shown as returned (no status code).
  - [ ] Positions: close one and close all call the session endpoints (`/close_position`, `/close_all_positions`) with CSRF and refresh on `order_update`; Orderbook: cancel and modify call `/cancel_order` and `/modify_order`; Tradebook lists sandbox trades.
  - [ ] Option chain page: placing an order from a strike uses NRML by default and the correct option symbol from the chain row.
  - [ ] Scalping: product defaults to NRML (never CNC) and the hotkey order path posts to `/scalping/api/order`.
  - [ ] Exercise each surface in the running app (dev server, `npm run build` then reload) and fix what does not work; record what was checked in the task notes.
- Acceptance:
  - `npx vitest run src/pages/Positions.test.tsx src/components/trading/PlaceOrderDialog.test.tsx src/pages/OrderSurfaces.test.tsx src/components/scalping` passes.
  - `OrderSurfaces.test.tsx`: the ticket defaults (CNC for NSE, NRML for NFO); close-all, cancel and modify hit the right endpoints with an `X-CSRFToken` header.
  - `npm run build` passes; in the running app a CNC order from the dashboard appears in Orderbook, Tradebook and Positions and closes from Positions.

---

## Wave 3: backtesting and release (parallel, after Wave 2)

### T10. Backtesting surfaces on paper history

- Owner: Sonnet coder. Status: pending. Requirement: R4.
- Owned files: `portfolio/` (dir), `sip/` (dir), `services/portfolio_service.py`,
  `services/sip_service.py`, `services/sector_rotation_service.py`,
  `services/historify_service.py`, `blueprints/historify.py`,
  `services/strategy_builder_reference_service.py`, `.claude/skills/python-strategy/` (dir),
  `frontend/src/pages/PortfolioBacktester.tsx`, `frontend/src/pages/SipBacktester.tsx`,
  `frontend/src/pages/SectorRotation.tsx`, `frontend/src/pages/StrategyBuilder.tsx`,
  `frontend/src/pages/Historify.tsx`, `frontend/src/components/trading/BacktestPanel.tsx`;
  new test (test author) `test/test_backtests_paper.py`.
- Subtasks:
  - [ ] Historify: download RELIANCE, TCS (NSE) and NIFTY (NSE_INDEX) at `D` and `1m` from the paper broker through the Historify job API; confirm rows land in `historify.duckdb` and contain no weekend dates.
  - [ ] Portfolio backtest `POST /api/v1/portfolio/backtest` with `source: api` and, after the download, `source: db`, RELIANCE/TCS 50/50, benchmark NIFTY: success, finite CAGR/Sharpe/max drawdown, no weekend dates in the equity curve.
  - [ ] SIP backtest `POST /api/v1/sip/backtest` (monthly, day 1, RELIANCE, `api` and `db`): installments fall on weekdays; XIRR finite.
  - [ ] Sector rotation `POST /api/v1/sectorrotation` with timeframes `daily` and `weekly`, sources `api` and `db`: every default sector index resolves on the paper master contract; report any index the paper contract lacks to the orchestrator (do not edit `broker/paper/`).
  - [ ] Strategy Builder: payoff and what-if for a NIFTY short straddle on the nearest expiry load (option chain, greeks, reference chart service) on paper data.
  - [ ] `/trading` backtest panel: runs on paper history for RELIANCE 5m and D (vitest `BacktestPanel.test.tsx` plus a manual run).
  - [ ] Python strategy backtest: `uv run python .claude/skills/python-strategy/backtest.py <a template strategy> --days 60 --source api` against the running app completes with trades or a clear "no signals" line.
  - [ ] Fix whatever breaks in owned files (interval names the paper broker does not offer: map to `D`/`1m` or resample from them; do not add W/M to the broker).
- Acceptance:
  - `test/test_backtests_paper.py` (in-process, history service patched to the paper `BrokerData`) passes: portfolio, SIP and sector rotation succeed with `source=api`; no weekend dates in results; a `db` request with an empty Historify returns the existing trader-facing "download it in Historify" error.
  - The manual checks above pass against the running app and are recorded in the task notes.
  - `npx vitest run src/components/trading/BacktestPanel.test.tsx src/pages/SectorRotation.test.tsx` passes; existing portfolio, SIP and sector rotation tests still pass.

### T11. CI, build, lint and docs consistency

- Owner: Sonnet coder. Status: pending. Requirement: R6.
- Owned files: `.github/workflows/windows.yml`, `CLAUDE.md`, `docs/buckleson/HANDOFF.md`,
  `docs/buckleson/TODO.md` (status column), `docs/CHANGELOG.md`.
- Subtasks:
  - [ ] `windows.yml` Backend tests step runs: `test/test_paper_broker.py test/test_paper_history_sessions.py test/test_buckleson_bridge.py test/test_claude_connect.py test/test_zerodha_only.py test/test_platforms_removed.py test/test_backtests_paper.py test/test_live_sandbox_smoke.py` (the last one skips in CI).
  - [ ] `windows.yml` Frontend tests step adds `src/components/claude src/components/portfolio src/config src/pages/OrderSurfaces.test.tsx src/components/trading/PlaceOrderDialog.test.tsx`.
  - [ ] Run the full kept backend suite and compare with the baseline by test name; any new failure goes to the orchestrator.
  - [ ] `npm run build`, `npx biome check` on files changed this run, `uv run ruff check` on Python files changed this run: all clean.
  - [ ] `CLAUDE.md`: the Overview table's Unified Broker API row and the Security section's external-platform sentence name only REST/Python/MCP and Zerodha; add one line pointing to `docs/buckleson/`. No other rewrites.
  - [ ] `docs/CHANGELOG.md`: a Buckleson stanza saying what was removed (37 brokers, four platforms), what changed (history sessions), what was added (Claude plan detection and Connect), and what is deferred (Zerodha MCP).
  - [ ] Restart the dev server, open `/dashboard`, `/claude`, `/tools`, `/broker`, and run the live smoke; mark the board rows `done`.
- Acceptance:
  - Every test file named in `windows.yml` exists and passes locally.
  - `npm run build` green; Biome and Ruff clean on changed files.
  - No new backend failures against the baseline (list compared by name).
  - The app boots, `/api/broker/list` lists `paper` and `zerodha`, `/claude/api/status` reports the plan, and the live smoke passes.
