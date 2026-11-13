# Builds out/Buckleson-windows.zip: the committed source, the freshly built UI,
# a bundled uv.exe (which fetches Python 3.12 and the dependencies on first
# start) and Start-Buckleson.bat. Run from the repository root after
# `npm run build` in frontend/.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$out = Join-Path $root 'out'
$stage = Join-Path $out 'Buckleson'

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Path $stage | Out-Null

# Source exactly as committed.
git -C $root archive --format=zip -o "$out/src.zip" HEAD
Expand-Archive -Path "$out/src.zip" -DestinationPath $stage
Remove-Item "$out/src.zip"

# The UI built in this run.
if (-not (Test-Path "$root/frontend/dist/index.html")) { throw 'frontend/dist is missing: run npm run build first' }
if (Test-Path "$stage/frontend/dist") { Remove-Item -Recurse -Force "$stage/frontend/dist" }
Copy-Item -Recurse "$root/frontend/dist" "$stage/frontend/dist"

# uv for Windows.
New-Item -ItemType Directory -Path "$stage/tools" | Out-Null
Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile "$out/uv.zip"
Expand-Archive -Path "$out/uv.zip" -DestinationPath "$out/uv"
$uv = Get-ChildItem -Path "$out/uv" -Recurse -Filter 'uv.exe' | Select-Object -First 1
if (-not $uv) { throw 'uv.exe not found in the uv download' }
Copy-Item $uv.FullName "$stage/tools/uv.exe"

Copy-Item "$root/scripts/windows/Start-Buckleson.bat" "$stage/Start-Buckleson.bat"
Copy-Item "$root/scripts/windows/Install-Skills.ps1" "$stage/Install-Skills.ps1"

Compress-Archive -Path $stage -DestinationPath "$out/Buckleson-windows.zip"
$size = [math]::Round((Get-Item "$out/Buckleson-windows.zip").Length / 1MB, 1)
Write-Host "Built out/Buckleson-windows.zip ($size MB)"
