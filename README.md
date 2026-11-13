# Buckleson

A personal trading desk with Claude Code built in. Buckleson runs on your own
machine, opens straight to the desk with no sign-in, starts in **Sandbox mode**
(every order is simulated with 1 crore of sandbox capital), and lets you talk to
your Claude Code agent from any page: ask it to read the market, review your
positions, or place and manage trades.

Buckleson is built on [OpenAlgo](https://github.com/marketcalls/openalgo)
(AGPL-3.0). The original README is in [docs/OPENALGO_README.md](docs/OPENALGO_README.md).

## What is different from OpenAlgo

| Area | Buckleson |
| --- | --- |
| Sign-in | None. Local mode creates one operator account, an API key and a broker session on first start, and every browser on the bound address is that operator. |
| Broker | Built-in `paper` broker ("Sandbox (No Broker)"): no account needed. Prices come from Yahoo Finance when reachable, otherwise from a deterministic simulator (Black-Scholes for options). 1,600+ instruments: NIFTY 50 and other liquid NSE/BSE stocks, indices, index futures, NIFTY and BANKNIFTY option chains. You can still connect a real broker from Select Broker. |
| Claude | A docked Claude panel on every page (Ctrl+J), a full `/claude` page with conversation history, and a live connection status in the top bar. Claude reaches the platform through the bundled MCP server, so it can quote, analyse, and place, modify and cancel orders. |
| Terminal | `claude mcp add` command on `/claude`; any terminal Claude Code session then trades here and the app shows it as connected, with the last tool it used. |
| Skills | firecrawl (scrape, crawl, search, interact) and agent-reach (X, Reddit, YouTube, GitHub and more) are installed into the desk workspace. |
| Design | New shell: grouped sidebar, quiet top bar, Geist type, neutral palette with a single cobalt accent; Sandbox is a graphite desk with an amber marker. |

## Windows (one click)

Download `Buckleson-windows.zip` from the latest
[Windows build](../../actions/workflows/windows.yml) run (Artifacts) or from
[Releases](../../releases), unzip it, and double-click `Start-Buckleson.bat`.
The bundled `uv.exe` installs Python 3.12 and the dependencies on first start,
then the desk opens at http://127.0.0.1:5000. Install
[Claude Code](https://docs.claude.com/en/docs/claude-code) and run
`claude auth login` so the Claude panel can connect. `Install-Skills.ps1`
adds the firecrawl and agent-reach skills.

## Run it from source

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22 (only to
rebuild the UI), and [Claude Code](https://docs.claude.com/en/docs/claude-code)
signed in (`claude auth login`).

```bash
git clone https://github.com/buckleson/vibe-trading.git buckleson
cd buckleson
cp .sample.env .env        # first start replaces the placeholder secrets
uv run app.py
```

Open http://127.0.0.1:5000. The desk opens directly. Keep the app bound to
127.0.0.1: local mode trusts whoever can reach the port.

Optional, for the web skills on your own machine:

```bash
./scripts/install_claude_skills.sh
export FIRECRAWL_API_KEY=fc-...   # https://firecrawl.dev
```

## Talking to Claude

- **In the app:** press Ctrl+J or click the status pill. Pick **Trade** (platform
  tools and web research) or **Full access** (adds shell commands and file edits
  in the desk folder). Each turn runs your own `claude` CLI in print mode,
  streams every step (tool calls, results, the answer) into the panel, and
  resumes the conversation on the next message.
- **From a terminal:** copy the `claude mcp add buckleson ...` command from the
  `/claude` page, run it once, then use `claude` anywhere (or `cd ~/.buckleson/desk && claude`
  for the desk instructions and skills).

The desk workspace (`~/.buckleson/desk`, override with `BUCKLESON_DESK_DIR`) is
seeded from [desk/](desk/): its CLAUDE.md tells Claude how to trade here.

## Settings (.env)

| Key | Default | Meaning |
| --- | --- | --- |
| `BUCKLESON_LOCAL_MODE` | `true` | No sign-in; auto-provision operator, API key and broker session. |
| `BUCKLESON_LOCAL_BROKER` | `paper` | Broker local mode signs in to. |
| `PAPER_DATA_SOURCE` | `auto` | `auto`, `yahoo` or `simulated`. |
| `PAPER_MARKET_HOURS` | `always` | `always` (prices move around the clock) or `exchange` (09:15 to 15:30 IST). |
| `CLAUDE_CLI_PATH` | auto | Path to the `claude` binary if it is not on PATH. |
| `CLAUDE_BRIDGE_MAX_TURN_SECONDS` | `900` | Longest a single Claude turn may run. |

Sandbox rules follow the exchange: MIS (intraday) orders are refused after the
15:15 IST square-off and resume at 09:00; CNC and NRML orders work any time.

## Replacing the logo

The mark is drawn in `frontend/src/components/brand/BrandMark.tsx`. To use your
own artwork, drop it in `frontend/public/logo.svg` (plus `logo.png`,
`favicon.ico`), set `USE_IMAGE_LOGO = true` in that file, and rebuild:
`cd frontend && npm install && npm run build`.

## CI

`.github/workflows/windows.yml` runs on every push and pull request on
`windows-latest`: backend tests (paper broker, local mode, Claude bridge),
frontend tests, the UI build, and the Windows bundle, uploaded as the
`Buckleson-windows` artifact. Pushing a `v*` tag also attaches the zip to a
GitHub release.

## License

AGPL-3.0, inherited from OpenAlgo. See [License.md](License.md).
