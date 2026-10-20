<#
.SYNOPSIS
  Install (or update) the NEXTCAM Device Agent on a register PC (docs/install/device-agent.md).

.DESCRIPTION
  Run from the extracted release package, in an elevated PowerShell on the register:

    powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-agent.ps1 `
        -Server https://nextcam.local -PairCode ABCD-EFGH

  The pairing code comes from "Registers → Devices → New device" (valid 15 minutes, shown
  once). Without -PairCode an already paired agent is only updated and restarted.
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$Server = "",
    [string]$PairCode = "",
    [string]$Root = "C:\NEXTCAM",
    [string]$Python = "py"
)
$ErrorActionPreference = "Stop"
$package = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path (Join-Path $package "VERSION"))) { throw "run from the extracted release package" }

$ver = & $Python -3.13 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
if ($LASTEXITCODE -ne 0 -or $ver -ne "3.13") { throw "Python 3.13 (64-bit) is required" }

$venv = Join-Path $Root "agent-venv"
$py = Join-Path $venv "Scripts\python.exe"
if (Test-Path $py) {
    Write-Host "stopping the running agent service"
    & $py -m nextcam_agent.service stop 2>$null | Out-Null
} else {
    & $Python -3.13 -m venv $venv
}
$wheels = Join-Path $package "wheels"
$source = @()
if (Test-Path $wheels) { $source = @("--no-index", "--find-links", $wheels) }
& $py -m pip install --quiet @source --upgrade (Join-Path $package "packages\nextcam-core") ((Join-Path $package "device-agent") + "[windows,serial]")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
# pywin32 needs its post-install step inside a virtual environment (error 1053 otherwise).
$post = Join-Path $venv "Scripts\pywin32_postinstall.py"
if (Test-Path $post) { & $py $post -install | Out-Null }

if ($PairCode) {
    if (-not $Server) { throw "-Server is required with -PairCode" }
    & (Join-Path $venv "Scripts\nextcam-agent.exe") pair --server $Server --code $PairCode
    if ($LASTEXITCODE -ne 0) { throw "pairing failed (code expired or already used?)" }
}
& $py -m nextcam_agent.service --startup auto install 2>$null | Out-Null
& $py -m nextcam_agent.service --startup auto update | Out-Null
& $py -m nextcam_agent.service start
Write-Host "Device Agent installed. Register page: http://127.0.0.1:47616/  Status: http://127.0.0.1:47615/" -ForegroundColor Green
