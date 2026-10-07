$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found. Install Astral uv, reopen PowerShell, then retry.'
}

uv python install 3.12
if ($LASTEXITCODE -ne 0) {
    throw 'uv could not install its managed Python 3.12 runtime.'
}
uv sync --locked --all-groups --python 3.12
if ($LASTEXITCODE -ne 0) {
    throw 'uv sync failed.'
}
uv run pytest
if ($LASTEXITCODE -ne 0) {
    throw 'Python tests failed.'
}
uv run minecraft-film-agent --help
if ($LASTEXITCODE -ne 0) {
    throw 'Agent CLI smoke check failed.'
}
Write-Host 'Python setup and offline checks passed. No Minecraft client was launched.'
