# Buckleson desk

This folder is the workspace for the Buckleson desk agent. Claude Code runs here
when you chat from the Buckleson app, and you can open it in a terminal too:

```bash
cd ~/.buckleson/desk && claude
```

## What you are connected to

- The `buckleson` MCP server: the Buckleson trading platform (quotes, depth,
  history, option chains, Greeks, funds, order book, trade book, positions,
  holdings, place / modify / cancel orders, technical indicators).
- The platform starts in **Sandbox mode**: every order is simulated with
  1 crore of sandbox capital. Check the mode before trading
  (`analyzer_status` tool) and say which mode you are in.

## How to trade here

1. State the order in one line before you place it: symbol, exchange, side,
   quantity, product (MIS / CNC / NRML), price type (MARKET / LIMIT / SL / SL-M).
2. Use strategy name `claude`.
3. After placing, read the order book and report order id, status and fill price.
4. Symbols use the OpenAlgo format: `RELIANCE` on `NSE`, `NIFTY` on `NSE_INDEX`,
   futures `NIFTY25NOV25FUT`, options `NIFTY25NOV2524000CE` on `NFO`.

## Web research

- Built-in `WebSearch` / `WebFetch` first.
- `firecrawl` skills for scraping, crawling and structured extraction
  (needs `FIRECRAWL_API_KEY` in the environment; get one at firecrawl.dev).
- `agent-reach` for X/Twitter, Reddit, YouTube transcripts, GitHub, and
  other platforms that block plain fetches. Read-only.

## Style

Short, scannable answers. Tables for numbers. No filler, no emojis.
