param(
    [Parameter(Mandatory = $true)]
    [string]$InstanceDir,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$instance = (Resolve-Path -LiteralPath $InstanceDir).Path
$manifestPath = Join-Path $repoRoot 'assets/productions/v10-master-draft-20261009/shots-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$entries = @()

foreach ($master in $manifest.masters.PSObject.Properties) {
    $entries += [pscustomobject]@{
        Source = Join-Path $repoRoot $master.Value.file
        Target = Join-Path $instance "replays/$($master.Name).mcpr"
        Sha256 = $master.Value.sha256
    }
}
foreach ($pack in $manifest.resourcepacks.PSObject.Properties) {
    $entries += [pscustomobject]@{
        Source = Join-Path $repoRoot $pack.Value.path
        Target = Join-Path $instance "resourcepacks/$($pack.Value.profile_id.Substring(5))"
        Sha256 = $pack.Value.sha256
    }
}

# Preflight all inputs and destinations before copying any file.
foreach ($entry in $entries) {
    if (-not (Test-Path -LiteralPath $entry.Source -PathType Leaf)) {
        throw "Missing pinned source: $($entry.Source). See docs/FILM_MASTER.md for the external school resource pack."
    }
    $actual = (Get-FileHash -LiteralPath $entry.Source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Sha256) {
        throw "Pinned source hash mismatch: $($entry.Source)"
    }
    if (Test-Path -LiteralPath $entry.Target) {
        $installed = (Get-FileHash -LiteralPath $entry.Target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($installed -ne $entry.Sha256) {
            throw "Instance already has a different file at $($entry.Target); no file was overwritten."
        }
    }
}

if (-not $Apply) {
    Write-Host "Validated $($entries.Count) pinned files. Pass -Apply to copy missing files into $instance."
    return
}

foreach ($entry in $entries) {
    if (Test-Path -LiteralPath $entry.Target) { continue }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $entry.Target) | Out-Null
    Copy-Item -LiteralPath $entry.Source -Destination $entry.Target
    $installed = (Get-FileHash -LiteralPath $entry.Target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($installed -ne $entry.Sha256) {
        throw "Copied file failed hash check: $($entry.Target)"
    }
}
Write-Host "Pinned replay masters and resource packs are installed in $instance."
