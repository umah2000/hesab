<#
.SYNOPSIS
  Remove the NEXTCAM Device Agent service from a register PC (run by setup.exe's uninstaller).

.DESCRIPTION
  Stops and removes the "NEXTCAM Device Agent" service and its Python environment.
  The agent's settings, token and offline queue in C:\ProgramData\NEXTCAM\agent stay:
  sales made offline and not yet sent must never be lost by an uninstall.
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param([string]$Root = "C:\NEXTCAM")
$ErrorActionPreference = "Continue"
$py = Join-Path $Root "agent-venv\Scripts\python.exe"
if (Test-Path $py) {
    & $py -m nextcam_agent.service stop 2>$null | Out-Null
    & $py -m nextcam_agent.service remove 2>$null | Out-Null
    Remove-Item -Recurse -Force (Join-Path $Root "agent-venv") -ErrorAction SilentlyContinue
}
Write-Host "Device Agent removed. Settings and unsent offline sales stay in C:\ProgramData\NEXTCAM\agent."
