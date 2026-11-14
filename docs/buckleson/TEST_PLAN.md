# Buckleson test plan (run R1 to R6)

Written by the test author before the code, from the task text in the
orchestrator plan. Every case below is encoded in an executable test; the
file and command for each task are at the end of its section. Tests use
fakes and mocks: no network, no real broker, no real `claude` login. Anything
that needs the running app is in one smoke script, `scripts/bk_smoke.py`,
which `test/test_bk_sandbox_smoke.py` runs under pytest (skipped when no
server answers, so CI skips it).

Test file names follow the `test_bk_<area>.py` rule. They replace the names
the plan used: `test_zerodha_only.py` is `test_bk_zerodha_only.py`,
`test_platforms_removed.py` is `test_bk_platforms_removed.py`,
`test_claude_connect.py` is `test_bk_claude_connect.py`,
`test_paper_history_sessions.py` is `test_bk_paper_history.py`,
`test_backtests_paper.py` is `test_bk_backtests.py` and
`test_live_sandbox_smoke.py` is `test_bk_sandbox_smoke.py` plus
`scripts/bk_smoke.py`.

State on the tree before Wave 1: every new test that checks something new
fails, and every test that pins behaviour that must not change passes. The
"Before" line in each section says which.

## Findings for the orchestrator (read first)

1. **Sector Rotation cannot work on paper yet, and no task owns the fix.** 17
   sector and benchmark indices (NIFTYAUTO, NIFTYCOMMODITIES, NIFTYENERGY,
   NIFTYFMCG, NIFTYINFRA, NIFTYMEDIA, NIFTYMETAL, NIFTYPHARMA, NIFTYPVTBANK,
   NIFTYPSE, NIFTYPSUBANK, NIFTYREALTY, NIFTYCONSRDURBL, NIFTYHEALTHCARE,
   NIFTYINDDEFENCE, NIFTYOILANDGAS, NIFTY500) are missing from the paper
   master contract (`broker/paper/database/instruments.py`). The history
   service refuses symbols that are not in the master contract, so the live
   map places 2 of 14 default sectors. T07 owns only `market_data.py`, and
   T10 must not edit `broker/paper/`. Assign `instruments.py` (suggest T07).
   Pinned by `test_bk_backtests.py::test_every_sector_and_benchmark_is_in_the_paper_master_contract`
   and the smoke check "Sector Rotation on paper".
2. **T01 acceptance import order fails on the current tree.** The command
   `import broker.zerodha...zerodha_adapter, ..., websocket_proxy` hits a
   circular import that already exists (the adapter imports
   `websocket_proxy.base_adapter`, whose package `__init__` imports the
   adapter). Import `websocket_proxy` first, as production does. The T01
   test does that; nothing needs fixing.
3. **T03 acceptance grep is wider than T03's files.** `grep -rniE
   'chartink|gocharting|...' frontend/src` also matches kept pages that name
   Chartink and TradingView as alert sources for Flow and Strategy-module
   webhooks (`pages/flow/FlowIndex.tsx`, `pages/strategy/*`,
   `hooks/useSupportedExchanges.ts` comments,
   `components/sector-rotation/InstrumentSearch.tsx` comment). Those features
   are kept (R2). The T03 test checks T03's own files only.
4. **`test/test_paper_broker.py::test_intraday_history_is_ordered_ohlc`
   expects 3 x 288 round-the-clock bars for past days.** T07 must change it to
   3 x 75 (it is in T07's owned files).
5. Observations, no task needed unless the orchestrator wants them:
   `/api/v1/history` answers an unsupported interval with HTTP 500 (the
   message is in words; the smoke accepts any error status); a zero-quantity
   order answers `{'quantity': ['Quantity must be a positive number.']}` (a
   dict printed as text, pre-existing).

---

## T01 Remove broker plugins and their runtime registrations (R1)

File: `test/test_bk_zerodha_only.py` (114 cases). Before: fails (91), the
import and schema guards pass.

1. `broker/` holds exactly `__init__.py`, `paper`, `zerodha` (plus `__pycache__`).
2. Each of the 37 removed names is not importable as `broker.<name>`
   (37 cases).
3. Kept plugins import: Zerodha auth, order, data, funds, order mapping,
   master contract, streaming adapter; paper data, order, streaming adapter
   (websocket_proxy imported first).
4. After importing `websocket_proxy`, `BROKER_ADAPTERS` keys are exactly
   `{zerodha, paper}`.
5. Edge: the websocket proxy no longer defaults an unknown broker to
   `angel`; the `VALID_BROKERS` fallback reads `paper`.
6. The flattrade/shoonya keep-adapter branch is gone from the proxy.
7. `postback.SUPPORTED_BROKERS == {"zerodha"}`; no `_normalize_dhan|fyers|upstox|angel|aliceblue`;
   `_normalize_zerodha` and the Zerodha checksum check stay.
8. Failure path: a postback to `/postback/dhan` is refused (400/404), not
   processed.
9. `order_update_service._BROKER_FACTORIES` is `{zerodha}`; no removed name in
   `_POLLING_BROKERS`.
10. `CRYPTO_BROKERS == set()`; `utils.auth_utils` and
    `services.telegram_bot_service` still import (they use the crypto
    exchange constants).
11. `admin._BROKER_PROBE_HOSTS == {"zerodha": "api.kite.trade"}`.
12. `position_read.BROKER_DISPLAY_NAMES` keys are `{paper, zerodha}`.
13. The option chain has no Fyers fast path (`fyers`, `used_fast_path` absent).
14. The seven `samco_*` / `_get_samco_auth` helpers are gone from `auth_db`
    (7 cases).
15. Edge (no schema change): the `Auth` table columns are exactly the 15
    columns of today, and `upgrade/migrate_samco_auth.py` still exists.
16. `examples/python/broker_sdk_downloads.py` is deleted.
17. Removed-broker references: no runtime Python file (outside `test/`,
    `docs/`, `upgrade/`, `frontend/`) imports `broker.<removed>` or
    `broker/<removed>`.
18. Removed-broker references: none of T01's nine owned files contains a
    quoted removed name (9 cases).
19. No `test/test_<removed>_*.py` or `test/test_<removed>.py` file remains
    (37 cases).

Command: `uv run pytest test/test_bk_zerodha_only.py test/test_paper_broker.py -o addopts="" -q`

## T02 Broker login, keys, setup guide, env and install files (R1)

File: `test/test_bk_broker_login.py` (48 cases). Before: fails (33); the
Zerodha login address and the generic callback route already pass and must
keep passing.

1. `BROKER_NAMES == {"paper": "Sandbox (No Broker)", "zerodha": "Zerodha"}`;
   `KEYLESS_BROKERS == {"paper"}`; `broker_title("zerodha") == "Zerodha"`.
2. `_KEY_FORMATS == {}`; `key_format_error` returns None for a Zerodha key,
   an empty key, and a removed broker's name.
3. Edge: `VALID_BROKERS="paper, zerodha ,angel,dhan,paper"` enables exactly
   `["paper", "zerodha"]` (whitespace, duplicates, names with no plugin).
4. Edge: empty `VALID_BROKERS` enables nothing.
5. `GUIDES` keys are `{paper, zerodha}`; Zerodha uses a redirect URL, paper
   does not.
6. A removed broker's name gets the generic redirect guide, not an error.
7. Broker sets: `BROKER_SITE_POST_BROKERS` empty, `CALLBACK_START_BROKERS ==
   {paper}`, `STATE_BROKERS == {zerodha}`, `_STATE_CALLBACK_START_BROKERS`
   empty; `xts_login_url` gone.
8. Zerodha login address: starts with
   `https://kite.zerodha.com/connect/login?v=3&api_key=`, carries
   `redirect_params=state%3Ds1` and decodes to `state=s1`.
9. Edge: a key with a space and `&` is encoded (`a%20b%26c`).
10. Paper starts at `/paper/callback`.
11. Any other name (dhan, fyers, upstox, flattrade, rmoney, an unknown name)
    falls back to `/<name>/callback` (6 cases).
12. Failure path: no broker counts as a cross-site POST any more
    (`is_broker_site_post` is False for zerodha, paper, rmoney, compositedge).
13. `/<broker>/callback` is still registered; `/dhan/initiate-oauth`,
    `/samco/ip-status`, `/nubra/ip-status` are not (3 cases).
14. `_dhan_account_mismatch`, `_xts_account_mismatch`, `_refuse_xts_account`,
    `_dhan_initiate_oauth` are gone (4 cases).
15. `brlogin.py` keeps the paper branch, the Zerodha token prefix and
    `_complete_login(`.
16. Removed-broker references: no quoted removed name (or `icici`) in the
    seven owned Python files (7 cases).
17. `VALID_BROKERS = 'paper,zerodha'` in `.sample.env` and `.env` (skipped
    when `.env` is absent, as in CI); `start.sh` default
    `${VALID_BROKERS:-paper,zerodha}`.
18. `install/docker-run.sh` and `.bat` no longer print the XTS broker list.
19. `docker-build.sh` and `.bat` mention no fyers, angel, dhan or upstox and
    give the `zerodha/callback` hint.
20. No `VALID_BROKERS=` line in `.sample.env`, `start.sh` or any installer
    names a removed broker (8 cases).

Manual (no fake can stand in for Kite): with Zerodha keys saved, Login with
Zerodha reaches the Kite page and the callback completes through the generic
branch with the token prefixed by the API key.

Command: `uv run pytest test/test_bk_broker_login.py -o addopts="" -q`

## T03 Frontend: remove broker login forms and platform pages (R1, R2)

Files: `frontend/src/components/portfolio/SymbolSearchInput.test.tsx` (9),
`frontend/src/config/platformsRemoved.test.ts` (9). Before: fail (14 of 18).
T03 also updates its own `navigation.test.ts` and `Navbar.test.tsx`.

SymbolSearchInput:
1. Typing `rel` with exchange NSE fetches exactly
   `/search/api/search?q=REL&exchange=NSE` with `credentials: 'include'` and
   `Accept: application/json`, and lists RELIANCE with its name.
2. The exchange the parent picked is sent (BSE).
3. Edge: `M&M` is encoded (`q=M%26M`).
4. Edge: one character does not search.
5. Empty data: no match shows "Nothing on NSE matching".
6. Empty data: a body without `results` is treated as no results.
7. Selecting a result with the mouse calls `onSelect('RELIANCE')`.
8. Enter takes the typed ticker without waiting (`TCS`).
9. The component no longer references Chartink.

Platforms removed:
10. The BrokerTOTP, SamcoAuth, Platforms, TradingView, GoCharting pages,
    `pages/chartink/`, `api/chartink.ts`, `types/chartink.ts` are deleted.
11. `App.tsx` routes none of them, no `/:broker/auth` or
    `/broker/:broker/totp`; `/broker` and `/broker/config` stay.
12. No nav, profile-menu or sidebar entry points at a removed page.
13. The Automate group lists Strategies, Python, Flow only.
14. Strategies sits directly after Trading; Platforms is gone.
15. Page titles, the alert category (`chartink`) and Profile copy forget the
    platforms.
16. Copy: LogoutConfirmDialog says "Webhook and REST API signals"; Home and
    FAQ name no Chartink, GoCharting, Amibroker or "36 broker" plugins.
17. Select Broker has no Dhan note.
18. Edge: `makeFormatCurrency('deltaexchange')` formats rupees; the USD branch
    is gone.

Command: `cd frontend && npx vitest run src/config/platformsRemoved.test.ts src/components/portfolio/SymbolSearchInput.test.tsx src/config/navigation.test.ts src/components/layout/Navbar.test.tsx`

## T04 Backend: remove TradingView, GoCharting, Chartink and Platforms (R2)

File: `test/test_bk_platforms_removed.py` (42 cases). Before: fails (20); the
kept-surface guards pass.

1. `blueprints.tv_json`, `gc_json`, `chartink`, `platforms`,
   `database.chartink_db`, `database.tv_search` are not importable (6).
2. `app.py` imports none of them (AST check) and names no `chartink_bp`,
   `gc_json_bp`, `tv_json_bp`, `platforms_bp`, `Chartink DB`,
   `ensure_chartink_tables_exists` (6).
3. Guard: `app.py` still registers Flow, the Strategy module, the Claude
   bridge, the React app and Historify.
4. The React blueprint has no rule under `/chartink`, `/tradingview`,
   `/gocharting`, `/platforms`, and no `/broker/<broker>/totp`,
   `/broker/samco/auth`, `/<broker>/auth`.
5. Guard: 17 kept React routes are still registered (`/broker`,
   `/broker/config`, `/dashboard`, `/flow`, `/strategy`, `/tools`, `/claude`,
   `/historify`, the backtesters, `/sector-rotation`, `/strategybuilder`,
   `/scalping`, `/optionchain`, `/trading`, `/python`, `/agent`).
6. `utils.shutdown` has no `_stop_chartink_scheduler` and no chartink mention.
7. `SCOPED_SESSION_MODULES` drops `database.chartink_db`, and every listed
   database module still exists.
8. Kept webhooks are still redacted: `/strategy/webhook/<token>`,
   `/flow/webhook/<token>/<symbol>`, a full URL (3).
9. The redaction source and `upgrade/init_db.py` no longer name chartink.
10. Guard: `auth_db.get_api_key_for_tradingview` stays (many callers).
11. `test/test_gthread_hosts_chartink.py` is deleted.

Live (smoke "platform routes gone"): POST `/chartink/webhook/<id>`, GET
`/chartink/api/strategies`, GET `/chartink/search`, POST `/tradingview/`,
POST `/gocharting/`, GET `/platforms/` answer 404/405 or the React HTML
fallback, never JSON.

Command: `uv run pytest test/test_bk_platforms_removed.py -o addopts="" -q`

## T05 Claude bridge: plan detection, one-click sign-in, Windows (R5)

File: `test/test_bk_claude_connect.py` (111 cases). Before: fails (all new
functions and the `LOGIN_LOG` global are missing); the existing chat and
heartbeat behaviour passes when the new globals exist.

Contract the tests rely on: the Windows decision reads `os.name` through the
module global `os`; `install_info()` reads `sys.platform` through the module
global `sys` (so `import sys` in the module); credentials fall back to
`Path.home() / ".claude"`; the login process is started with
`subprocess.Popen` and stopped with the module-level `kill_tree`;
`LOGIN_LOG` and `LOGIN_TIMEOUT_SECONDS` are read at call time.

detect_plan (27 table cases plus 2):
1. Subscription field: max, pro, PRO (case), team (`subscription`),
   enterprise (`plan`), free, an unknown value (`max_20x` becomes
   "Claude Max_20X").
2. Credentials file: team from `claudeAiOauth.subscriptionType`; the status
   field wins over the file; empty strings are skipped.
3. Providers: `apiProvider` bedrock, vertex, foundry; env
   `CLAUDE_CODE_USE_VERTEX=1`, `..._BEDROCK=true`, `..._FOUNDRY=1`; a
   provider beats a subscription; `firstParty` is not a provider; `=0` does
   not switch a provider on.
4. API key: `authMethod` api_key, apiKey, console; signed out with
   `ANTHROPIC_API_KEY` set.
5. Signed in with nothing else: "Claude subscription". Signed out, None, `{}`:
   `{key: None, label: None}`.
6. Defaults read `os.environ`; a non-string subscription is ignored.

read_plan_credentials (9):
7. Returns only `{"claudeAiOauth": {"subscriptionType": ...}}`; never a token
   (the file holds accessToken and refreshToken).
8. No subscription field gives `{}`; invalid JSON, `[]`, a string, `{}`,
   `claudeAiOauth: null` give `{}`; a missing file gives `{}`.
9. Falls back to `~/.claude/.credentials.json` without `CLAUDE_CONFIG_DIR`.
10. A broken file containing a token does not put the token in any log.

cli_status (7):
11. Reports `api_provider`, `subscription`, `plan` (Max) with version,
    auth method and existing keys.
12. Plan from the credentials file when the status has none.
13. Failing `auth status` with `ANTHROPIC_API_KEY`: signed in, plan api_key.
14. Signed-out CLI; missing CLI (installed False, path None, empty plan).
15. Non-JSON auth output still answers; the cache holds until forced.

Discovery (8):
16. POSIX candidates: `~/.claude/local/claude`, `~/.local/bin/claude`,
    `/usr/local/bin/claude`, `/opt/homebrew/bin/claude`, no `.exe`/`.cmd`.
17. Windows candidates: `%USERPROFILE%\.local\bin\claude.exe`,
    `%USERPROFILE%\.claude\local\claude.exe`, `%APPDATA%\npm\claude.cmd`,
    `%APPDATA%\npm\claude.exe`; no POSIX paths.
18. Edge: an unset `APPDATA` drops the npm entries (no crash).
19. `CLAUDE_CLI_PATH` wins when it exists; a missing one is ignored;
    `shutil.which`; then the first existing candidate; else None.

Process handling (12):
20. `install_info()` for win32, darwin, linux with the three commands and the
    docs link (3).
21. `spawn_kwargs()`: POSIX `{"start_new_session": True}`; Windows
    `creationflags` with `CREATE_NEW_PROCESS_GROUP` and `CREATE_NO_WINDOW`,
    no `start_new_session`.
22. `kill_tree` on Windows runs `taskkill /PID <pid> /T /F` (captured output);
    falls back to `proc.kill()` when taskkill cannot run; leaves a finished
    process alone.
23. `kill_tree` on POSIX sends SIGTERM, or SIGKILL with `force`, to the
    group; falls back to terminate/kill (skipped on Windows).
24. A real `sh` process group is stopped (POSIX only).
25. Only `kill_tree` calls `killpg`; `_terminate` and `_reap` go through it
    (force on reap after the wait times out).

parse_login_output (7):
26. The real CLI text gives its authorize URL and `needs_code` True.
27. Empty, no URL, a docs URL before the oauth URL (the oauth one is picked),
    `PASTE CODE` in capitals, an `http://` URL (ignored), "Login successful".

Login endpoints (28):
28. GET `/login` idle by default (exact body).
29. POST with `{}` starts one `claude auth login` with stdin a pipe, stdout a
    file (never a pipe), stderr to stdout, text mode, no `CLAUDECODE` in env,
    cwd the desk, `start_new_session` on POSIX; state `starting`.
30. `method: console` adds `--console`; no body defaults to the subscription.
31. Failure path: method `google`, `"CLAUDEAI "`, `5` give 400 with the exact
    sentence and start nothing.
32. Edge: a second POST while one runs starts no second process and returns
    the current view.
33. `waiting` carries the URL and `needs_code`; without the paste prompt
    `needs_code` is False.
34. Already signed in: `connected`, nothing started, status read with force.
35. Missing CLI: 409 with the install sentence and `install` block.
36. Spawn failure: 500 with the "Run claude auth login in a terminal"
    sentence; the next GET is idle.
37. Exit 0 and signed in: `connected`, status re-read with force, process
    reaped and stdin closed; still `connected` on the next GET (sticky).
38. Exit 0 but still signed out: `failed`. Exit 1: `failed` with "Sign-in did
    not finish. Press Connect Claude to try again.", sticky.
39. After a failure a new POST starts a second process.
40. Stale sign-in: past `LOGIN_TIMEOUT_SECONDS` the process is killed and the
    state is `failed` with "The sign-in link expired...".
41. POST `/login/code` writes `code + "\n"` (trimmed) and flushes.
42. Failure path: empty, spaces, over 4000 characters, null give 400 with the
    exact sentence and write nothing; no login gives 409; a login that
    already ended gives 409.
43. DELETE kills the running process and answers idle; with nothing running
    it answers 200 and kills nothing; it clears a sticky failure.
44. Every login endpoint needs the session (401 for JSON callers, nothing
    started).
45. GET `/status` adds `install` and `login` (idle) and `cli.plan`.

Chat (6):
46. The chat process starts with `spawn_kwargs()` (POSIX and Windows).
47. Concurrent chat on one conversation: a second turn while one runs is 409
    "still answering" and starts nothing; a finished turn does not block.
48. Missing CLI 409; empty message 400.

Heartbeats (2):
49. A heartbeat just inside the window is connected; never seen is not.
    (Stale heartbeats past the window: `test_buckleson_bridge.py`.)

Command: `uv run pytest test/test_bk_claude_connect.py test/test_buckleson_bridge.py -o addopts="" -q`

## T06 Claude UI: plan label, Connect Claude, install help (R5)

Files: `frontend/src/components/claude/ConnectClaude.test.tsx` (18, real
component, store and API with fetch stubbed),
`frontend/src/stores/claudeLogin.test.ts` (11, API mocked). Before: fail
(component missing, store actions missing).

1. CLI missing on Windows: "Install Claude Code", the `irm ... | iex` block,
   the npm block, no curl block, no Connect button.
2. CLI missing on Linux and macOS: the curl block, no `irm` (2).
3. Refresh re-reads `/claude/api/status?refresh=1`.
4. Signed out: Connect Claude POSTs `/claude/api/login` with
   `{"method":"claudeai"}` and the CSRF header, then shows
   "Starting sign-in...".
5. "Use a Console API account" POSTs `{"method":"console"}`.
6. Failure path: a 500 refusal shows the server sentence, no status code,
   and Connect stays available.
7. A failed sign-in shows its message and offers Connect again.
8. Edge: a missing login block is treated as idle.
9. Waiting: "Open the sign-in page" links to the URL with `target=_blank`,
   `rel="noopener noreferrer"`, plus the plan sentence.
10. The "Sign-in code" input and "Submit code" POST `/claude/api/login/code`
    with `{"code":"abc#123"}`; no code box when the CLI does not ask.
11. Cancel sends DELETE `/claude/api/login` and returns to Connect.
12. Polling every 2 s while starting; the interval stops on unmount (fake
    timers); no polling while idle.
13. A poll reaching connected refreshes the status with force and the
    component renders nothing.
14. Signed in renders nothing; no status yet does not throw.
15. Store: `startLogin()` defaults to the subscription, `startLogin('console')`
    passes it; a poll reaching connected calls `status(true)`, a waiting poll
    does not; starting when already signed in refreshes too.
16. Store: a rejection sets `loginError` to the server sentence, cleared by
    the next action; a refused code is reported in words.
17. Store: submit and cancel keep the returned state; `refreshStatus` copies
    `status.login`; a failing status read keeps the last login state.

Manual: `/claude` shows the plan label in the Signed in row; the panel shows
`<plan> · v<version>`.

Command: `cd frontend && npx vitest run src/components/claude/ConnectClaude.test.tsx src/stores/claudeLogin.test.ts src/stores/claudeStore.test.ts`

## T07 Paper history follows exchange sessions (R4)

File: `test/test_bk_paper_history.py` (32 cases). Before: fails under
`always` (12), passes under `exchange` (which proves the expected numbers).

1. Daily RELIANCE 2023-01-01..15 has exactly 10 bars, Jan 2 to Jan 13, none
   on a weekend, stamps at UTC midnight, under `always` and `exchange` (2).
2. Daily NIFTY 2023..2024 has 522 bars (260 + 262 weekdays), no weekend (2).
3. Empty data: a range entirely on a weekend is an empty frame with the
   history columns; end before start is empty.
4. Daily bars are OHLC-consistent with volume.
5. 1h bars of a past weekday are 09:15 ... 15:15 IST, seven bars (2).
6. 1m bars of a past weekday are 375, 09:15 to 15:29 (2).
7. A past Saturday and Sunday give no intraday bars (2).
8. 5m over a past week: five days of 75 bars.
9. Past-day bars and volume are identical under `always` and `exchange`.
10. Today under `always` starts at 00:00 IST; under `exchange` it starts at
    09:15 (or is empty on a weekend or before the open).
11. History never runs past now.
12. NIFTY option and index-future daily history over a range with a weekend
    has no weekend bars, prices at least a tick, OI positive (4).
13. A past-day option 15m series is 25 bars and identical under both settings.
14. Determinism: two calls give the same frame.
15. Interval not supported: W, M, 1d, 2h, 7m, empty are refused with "not
    available" (no W/M added to the broker) (6).
16. The intervals offered are `1m 3m 5m 10m 15m 30m 1h D`.
17. BSE equity, BSE index and NIFTY BANK give 23 January 2024 sessions.

Command: `uv run pytest test/test_bk_paper_history.py test/test_paper_broker.py -o addopts="" -q`

## T08 Sandbox end to end on paper: backend surfaces (R3)

Files: `scripts/bk_smoke.py` (31 checks, one line each, exit 0 only if none
fails) and `test/test_bk_sandbox_smoke.py` (the same checks as 31 pytest
cases; module skipped without a server). Before: 21 pass, 10 fail (the
failures belong to T01-T07 and T10; every order surface already passes).

1. Server answers and gives the operator API key; broker is paper.
2. Sandbox (analyzer) mode is on.
3. `/api/broker/list` lists exactly paper and zerodha (T02).
4. Quotes, multiquotes (NSE, BSE, NSE_INDEX), five-level depth.
5. Bad symbol: a quote for an unknown symbol is refused (4xx).
6. Daily history has no weekend bars; 5m history of a past weekday runs
   09:15..15:25 IST (T07).
7. Interval not supported: `W` is refused in words.
8. CNC MARKET BUY SBIN fills: `mode: analyze`, order status complete,
   position up by 1, trade in the tradebook, available cash down.
9. NRML index future (one lot) fills.
10. Options: first NIFTY expiry, option chain with `strike_count` 2, ATM CE
    BUY NRML one lot via `/api/v1/optionsorder` fills.
11. Zero quantity is refused with HTTP 400; a bad symbol order is refused.
12. MIS after square-off: outside 09:00-15:15 IST a MIS order is refused with
    the square-off sentence in analyze mode (skipped inside the window).
13. LIMIT at half the LTP, modified to quantity 2 and a new price, then
    cancelled: status cancelled.
14. UI session routes with CSRF: POST `/close_position` closes SBIN CNC;
    POST `/cancel_all_orders` leaves no open order.
15. REST `/api/v1/closeposition` leaves the book flat.
16. Scalping: underlyings include NIFTY, expiries, strikes; NRML order on the
    ATM CE fills in analyze mode; CNC on NFO is refused; `close_all`
    flattens; `cancel_all` succeeds.
17. Strategy module: create a positional NIFTY ATM CE strategy, start in
    `sandbox`, every leg ok, leg position visible in analyze mode,
    `close_all`, `stop` (already stopped is fine), DELETE.
18. Flow: a start node to a place-order node (CNC SBIN 1) executes, the log
    shows a success in analyze mode, an execution is recorded, DELETE.
19. Claude MCP path: `mcp/mcpserver.py` loaded with the API key and host
    (in a subprocess) runs `place_order`, `get_order_book`,
    `get_position_book`, `close_all_positions`, each success; orders in
    analyze mode.
20. Cleanup: cancel all and close all for the smoke strategy, always.

Command: `BUCKLESON_SMOKE_URL=http://127.0.0.1:5000 uv run pytest test/test_bk_sandbox_smoke.py -o addopts="" -q`
(or `uv run python scripts/bk_smoke.py`)

## T09 Sandbox end to end on paper: frontend order surfaces (R3)

File: `frontend/src/pages/OrderSurfaces.test.tsx` (19 cases). Before: passes
(the current code already does this; the file pins it). T09 extends
`PlaceOrderDialog.test.tsx` and `Positions.test.tsx` as it needs.

1. The ticket defaults: SBIN NSE and RELIANCE BSE send CNC; NIFTY CE NFO,
   SENSEX PE BFO and the NIFTY future send NRML (5).
2. MIS stays when asked; CNC passed for F&O becomes NRML; NRML passed for
   equity becomes CNC.
3. MIS after square-off: the refusal sentence from a `status: error` answer
   is shown as given.
4. The same sentence from an HTTP 400 is shown, never "400" or "status code".
5. Session routes reach the transport with `X-CSRFToken`: `/close_position`
   (symbol, exchange, product), `/close_all_positions`, `/cancel_order`
   (orderid), `/modify_order` (quantity, price, product, price type),
   `/cancel_all_orders`, `/scalping/api/order` (NRML, NFO).
6. Failure path: with an empty CSRF token nothing is sent and the call
   rejects.
7. Scalping never defaults to CNC (source check); the option chain ticket
   passes the chain row symbol and no fixed product.

Manual (in the running app after `npm run build`): CNC order from the
dashboard appears in Orderbook, Tradebook and Positions and closes from
Positions; LIMIT order modify and cancel from Orderbook; option chain order;
scalping order and flatten.

Command: `cd frontend && npx vitest run src/pages/OrderSurfaces.test.tsx src/components/trading/PlaceOrderDialog.test.tsx src/pages/Positions.test.tsx`

## T10 Backtesting surfaces on paper history (R4)

File: `test/test_bk_backtests.py` (26 cases), in process with the history
service replaced by the paper broker's `BrokerData` and Historify by an
in-memory DuckDB table. Before: fails (13; weekend dates and the master
contract gap).

1. Portfolio 50/50 RELIANCE/TCS 2023-2024 vs NIFTY on paper: success, finite
   CAGR, Sharpe, max drawdown, volatility; no weekend date in the equity
   curve or the allocation dates.
2. Annualisation: 240-265 sessions a year (a calendar series gives ~365).
3. Empty holdings: "no holdings supplied" 400; duplicate symbols 400.
4. Bad symbol: a refused history answers with a message naming the symbol.
5. History range with no data: a weekend-only range fails in words.
6. Historify empty with `source=db`: 422 naming Historify, and no request to
   the broker (no silent fall back).
7. Historify filled from paper: portfolio with `source=db` succeeds with no
   weekend dates.
8. SIP RELIANCE monthly day 1 2022-2024, 5000: 36 installments, all on
   weekdays, finite XIRR, invested 180000.
9. A 1st that falls on Saturday (2022-01-01) executes on the next session.
10. Weekly, monthly, quarterly SIPs execute on weekdays (3).
11. Zero and negative amounts are refused with 400 (2).
12. SIP `source=db` on an empty Historify names Historify and calls no
    broker; after a download it succeeds on weekdays.
13. Every default sector, optional sector and benchmark is in the paper
    master contract (see Finding 1).
14. Sector rotation daily and weekly place every default sector, tails on
    weekdays (2).
15. The benchmark on its own map is listed unavailable.
16. Sector rotation `source=db` on an empty Historify gives the exact
    "Download it in Historify, or switch the data source to Broker API."
    sentence, 422, no broker request.
17. Bad benchmark, timeframe or source give 400 (3).
18. Interval not supported: consumers ask the paper broker only for intervals
    it offers.

Live (smoke): Portfolio and SIP backtests with `source=api` on the running
app have no weekend dates; Sector Rotation places every sector; a Historify D
download of RELIANCE stores rows with no weekend dates.

Manual (record in the task notes): Strategy Builder payoff and what-if for a
NIFTY short straddle; the `/trading` backtest panel on RELIANCE 5m and D;
`uv run python .claude/skills/python-strategy/backtest.py <template> --days 60 --source api`.

Command: `uv run pytest test/test_bk_backtests.py -o addopts="" -q`

## T11 CI, build, lint and docs (R6)

File: `test/test_bk_ci.py` (13 cases). Before: the workflow checks pass (the
test author already wired the files); the three docs checks fail until T11.

1. Every `test/test_bk_*.py`, plus `test_paper_broker.py` and
   `test_buckleson_bridge.py`, is in the Windows "Backend tests" step.
2. Every file that step names exists; the step passes `-o addopts=""`.
3. Each new vitest file exists and is covered by the "Frontend tests" step
   (by path or by a listed directory) (5); every path the step names exists.
4. `scripts/bk_smoke.py` exists and its pytest wrapper is in the step.
5. `docs/CHANGELOG.md` has a Buckleson heading whose stanza names Zerodha,
   Sandbox, TradingView and Claude.
6. `CLAUDE.md`: the Unified Broker API row names no TradingView, Amibroker or
   ChartInk; the Security sentence about TradingView/GoCharting/Chartink is
   gone; `docs/buckleson/` is linked.
7. Every board row in `docs/buckleson/TODO.md` reads `done`.

Also run (not a test file): `npm run build`, Biome and Ruff on changed files,
the full backend suite compared with the baseline by test name, and the smoke
script with the server up.

Command: `uv run pytest test/test_bk_ci.py -o addopts="" -q`

## Everything at once

```bash
uv run pytest test/test_paper_broker.py test/test_buckleson_bridge.py test/test_bk_zerodha_only.py test/test_bk_broker_login.py test/test_bk_platforms_removed.py test/test_bk_claude_connect.py test/test_bk_paper_history.py test/test_bk_backtests.py test/test_bk_sandbox_smoke.py test/test_bk_ci.py -o addopts="" -q
cd frontend && npx vitest run src/stores src/components/layout src/components/auth src/components/claude src/components/portfolio/SymbolSearchInput.test.tsx src/config src/pages/Trading.test.tsx src/pages/Positions.test.tsx src/pages/OrderSurfaces.test.tsx src/components/trading/PlaceOrderDialog.test.tsx
uv run python scripts/bk_smoke.py
```

The first two lines are the Windows workflow's own commands.
