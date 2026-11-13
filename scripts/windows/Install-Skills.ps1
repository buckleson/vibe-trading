# Installs the web skills the Buckleson desk agent uses, for every Claude Code
# session on this machine: firecrawl CLI + skills, and agent-reach.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$uv = Join-Path $root 'tools/uv.exe'
if (-not (Test-Path $uv)) { $uv = 'uv' }

if (Get-Command npm -ErrorAction SilentlyContinue) {
  Write-Host 'Installing firecrawl CLI...'
  npm install -g firecrawl-cli
} else {
  Write-Host 'Node.js is not installed: skipping the firecrawl CLI (https://nodejs.org).'
}

Write-Host 'Installing agent-reach...'
& $uv tool install --force https://github.com/Panniantong/Agent-Reach/releases/latest/download/agent-reach.zip
& $uv tool update-shell | Out-Null

$skills = Join-Path $HOME '.claude/skills'
New-Item -ItemType Directory -Force -Path $skills | Out-Null
Copy-Item -Recurse -Force (Join-Path $root 'desk/.claude/skills/*') $skills
Write-Host "Skills copied to $skills. Set FIRECRAWL_API_KEY to enable firecrawl."
