#!/usr/bin/env bash
# Install the web skills the Buckleson desk agent uses, for every Claude Code
# session on this machine (~/.claude/skills) and the desk workspace.
#   - firecrawl CLI + its agent skills (scrape, crawl, search, map, interact)
#   - agent-reach (read X/Twitter, Reddit, YouTube, GitHub and more)
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
command -v npm >/dev/null || { echo "Node.js 18+ is required for the firecrawl CLI"; exit 1; }

echo "Installing firecrawl CLI..."
npm install -g firecrawl-cli

echo "Installing agent-reach..."
uv tool install --force https://github.com/Panniantong/Agent-Reach/releases/latest/download/agent-reach.zip
uv tool update-shell >/dev/null 2>&1 || true
"$HOME/.local/bin/agent-reach" setup >/dev/null || agent-reach setup >/dev/null || true

echo "Copying skills into ~/.claude/skills ..."
mkdir -p "$HOME/.claude/skills"
cp -R "$here/desk/.claude/skills/"* "$HOME/.claude/skills/"

echo "Done. Set FIRECRAWL_API_KEY (https://firecrawl.dev) to enable firecrawl."
