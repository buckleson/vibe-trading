# ADR-001: Zerodha-only, sandbox on the paper broker, Claude Code built in

- Status: Accepted
- Date: 2026-11-13
- Deciders: Buckleson orchestrator (Opus), on the operator's requirements
- Supersedes: nothing (first Buckleson ADR)
- Requirements: R1 to R6 in [TODO.md](TODO.md)

## Context

Buckleson is a rebrand of OpenAlgo (Flask + React 19) for one operator who
trades from their own machine. The operator asked for:

1. No sign-in screens. The app opens straight onto the desk.
2. Sandbox trading and backtesting that work with no broker account at all.
3. One real broker later: Zerodha (its API now, its MCP server later). Every
   other broker plugin and every external charting/webhook platform removed.
4. Claude Code reachable from inside the app with whatever plan the operator
   has: Pro, Max, Team, Enterprise, a Console API key, Bedrock or Vertex.
5. A Windows build that is tested and packaged in CI.

Upstream OpenAlgo is built for a different shape: about 475,000 self-hosted
installs, 38 brokers, external platforms (TradingView, GoCharting, Chartink)
posting webhooks, multi-device sessions, and a gthread/eventlet production
story on Linux. Much of that code exists to serve users Buckleson does not
have.

The engineering principle for this project is YAGNI: build only what the
requirements need, delete rather than keep dead code, and add no abstraction
that has a single caller.

## Decisions

### D1. Local mode replaces authentication (already built)

`utils/local_mode.py` bootstraps one operator account (`buckleson`), an API
key, a `paper` broker session and Sandbox (analyzer) mode on startup. A
`before_request` hook gives every browser request the operator session. React
routes `/login`, `/setup` and `/` redirect to `/dashboard`.

The app binds to 127.0.0.1 and trusts whoever can reach the port, as a desktop
app trusts whoever sits at it. The auth machinery underneath (users table,
broker tokens, CSRF, API keys for `/api/v1/`) stays, because the Sandbox
engine, the REST API and the MCP server all key off it. Only the screens and
the need to use them are gone.

### D2. The `paper` broker is the default data and execution source (already built)

`broker/paper/` is a keyless plugin ("Sandbox (No Broker)"). It serves quotes,
depth, history and a streaming adapter from Yahoo when reachable and from a
deterministic simulator otherwise, over a master contract of about 1,621
instruments (NIFTY 50 and liquid NSE/BSE equities, indices, index futures,
NIFTY and BANKNIFTY options). Orders never reach it: in Sandbox mode every
order goes to the existing Sandbox engine (`sandbox/`, `sandbox.db`), which
prices fills from the paper broker's quotes.

This run adds one data-correctness rule (task T07): **history for past days
follows exchange sessions** (weekdays, 09:15 to 15:30 IST) whatever
`PAPER_MARKET_HOURS` says. Live quotes may tick around the clock
(`PAPER_MARKET_HOURS=always`, the default) so the operator can practise in the
evening, but a backtest over simulated weekend and night bars produces
returns, Sharpe ratios and SIP schedules that no exchange could have produced.
Today's bars still follow the live setting, so the chart joins the live quote.
Exchange holidays are not modelled.

### D3. Zerodha is the only real broker plugin

Every `broker/<name>/` directory except `zerodha` and `paper` is deleted (37
directories), with every reference to them: `VALID_BROKERS` defaults, the
broker key and setup-guide tables, the broker login branches, websocket and
order-update adapter registrations, postback mappers, broker probe hosts,
frontend login forms (BrokerTOTP, SamcoAuth) and tests that exist only for a
removed broker. `VALID_BROKERS` becomes `paper,zerodha`.

The Zerodha plugin stays importable and its login path (Kite redirect with
`redirect_params` state) stays intact, so the operator can add keys on Broker
Configuration later. Select Broker and Broker Configuration stay (they are
data driven from `GET /api/broker/list`), they simply list two brokers.

**Not built now: the Zerodha MCP integration.** Nothing calls it yet, so it is
deferred (see [HANDOFF.md](HANDOFF.md#deliberately-deferred)).

### D4. External charting and webhook platforms are removed

Removed: the Platforms, TradingView, GoCharting and Chartink pages and routes;
`blueprints/tv_json.py`, `gc_json.py`, `chartink.py`, `platforms.py`;
`database/chartink_db.py`; and their registration, shutdown hooks, session
registries and URL-redaction entries. The portfolio symbol search, which
borrowed `/chartink/search`, moves to the general `/search/api/search`.

Kept, because the operator uses them or they are the platform's own surfaces:
REST `/api/v1`, Python strategies, Flow (including its generic webhook
trigger), the Strategy module (including its signal mode), Scalping, Tools,
Historify, alerts (Telegram, Slack, Discord, WhatsApp), the `/agent` page and
the Claude bridge.

The nginx location regex in the installers that lists `chartink` among webhook
paths is left alone: it is harmless, the Windows build does not use nginx, and
editing installers that are not shipped buys nothing.

### D5. Claude Code is reached through the operator's own CLI

`blueprints/claude_bridge.py` runs the local `claude` CLI in print mode with
`--output-format stream-json` and the platform MCP server (`mcp/mcpserver.py`)
attached, and streams events to the page as SSE. The CLI already carries the
operator's identity and plan, so Buckleson never stores an Anthropic
credential, never proxies the Anthropic API and never needs its own OAuth
client.

This run adds (tasks T05, T06):

- **Plan detection.** `claude auth status --json` (`loggedIn`, `authMethod`,
  `apiProvider`, and a subscription field when the CLI reports one),
  `CLAUDE_CODE_USE_BEDROCK` / `CLAUDE_CODE_USE_VERTEX` /
  `CLAUDE_CODE_USE_FOUNDRY`, `ANTHROPIC_API_KEY`, and, when present, only the
  `subscriptionType` field of the CLI's credentials file (never a token). The
  result is one pure function, `detect_plan`, and a `plan` object on
  `/claude/api/status` that the UI shows ("Claude Max", "Anthropic API key",
  "Amazon Bedrock", ...).
- **One-click Connect.** When the CLI is installed but signed out, the server
  runs `claude auth login` in the background, reads the sign-in address it
  prints from a log file, and the UI shows it as a link. If the CLI asks for
  the code shown after sign-in, the UI takes it and the server writes it to
  the process. The UI polls until the CLI reports signed in.
- **Install help** when the CLI is missing, per operating system.
- **Windows process handling.** The binary is found as `claude.exe` or
  `claude.cmd` on PATH, in `%USERPROFILE%\.local\bin` or `%APPDATA%\npm`;
  child processes start in a new process group and are stopped with
  `taskkill /PID <pid> /T /F` instead of `os.killpg`.

### D6. CI is one Windows workflow

`.github/workflows/windows.yml` on `windows-latest`: `uv sync --frozen`, the
Buckleson backend tests, `npm ci`, a vitest subset, `npm run build`, and the
packaged zip (`scripts/windows/package.ps1`), released on tags. Every new test
file is added to that workflow's commands explicitly (task T11).

## Alternatives rejected (YAGNI)

| Alternative | Why rejected |
| --- | --- |
| Keep all brokers but hide them from the UI | Thousands of lines of dead plugin code, 100+ tests and adapter registrations to keep green for brokers nobody uses. Deleting is cheaper than maintaining. |
| Keep brokers behind a plugin-download mechanism | A distribution system for one future broker. Zerodha is kept in tree instead. |
| Build the Zerodha MCP integration now | No caller exists until the operator moves to live trading. |
| A Buckleson-owned Anthropic OAuth flow or API proxy | Duplicates what the CLI already does for every plan, and would put credentials in Buckleson's database. |
| Parse plan names from the Anthropic web API | Needs a token Buckleson does not hold. The CLI's own status and credentials-file field are enough to label the plan. |
| A pty/terminal emulator for `claude auth login` | The CLI prints the sign-in address and reads the code on plain stdin; a log file plus a stdin pipe is enough. |
| Auto-fallback from Historify (`source=db`) to the broker API in backtests | Changes documented semantics; the UI already defaults to the broker API and the error names the fix. |
| Model exchange holidays in the simulator | Weekday sessions remove the material distortion; a holiday calendar has no requirement behind it. |
| Strip every crypto code path with Delta Exchange | Crypto paths are keyed on exchange names and spread through shared services. `CRYPTO_BROKERS` becomes an empty set; nothing else changes. |
| Keep Linux gthread/eventlet CI jobs | The product ships as a Windows bundle; one workflow is what the operator runs. The gthread tests stay in the repo for anyone who restores the Linux job. |
| Rewrite installers (install.sh, Docker) | Only their broker lists change. They are not the shipped path. |

## Consequences

Positive:

- The tree loses 37 broker plugins and roughly 120 broker-specific tests, so a
  change touches less and the suite runs faster.
- A new user runs the app, gets a working desk with Sandbox orders and
  backtests on simulated data, and connects Claude with one click, with no
  account anywhere but Claude.
- Backtests on simulated history no longer include weekend or night bars.

Negative and accepted:

- Upstream OpenAlgo merges will conflict in every file this run edits. Buckleson
  is a fork from here on.
- Only `zerodha` can be added later without restoring code. Another broker
  means restoring its plugin and registrations from upstream.
- `PAPER_MARKET_HOURS=always` makes today's chart show bars outside exchange
  hours while past days show sessions only. This is deliberate (D2).
- Plan detection depends on what the installed CLI version reports. When no
  plan field is available the UI shows the auth method ("Claude subscription",
  "Anthropic API key") rather than guessing a tier.
- The sign-in flow depends on the CLI printing a sign-in URL and reading the
  code on stdin, which is true of the CLI version tested (2.1.x). A future CLI
  that changes this output needs a parser update in one function.
- Removing Chartink drops its database tables from new installs only; an
  existing `openalgo.db` keeps the old tables untouched (no destructive
  migration).
