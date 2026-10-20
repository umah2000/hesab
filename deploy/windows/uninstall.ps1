<#
.SYNOPSIS
  Remove the NEXTCAM server program from this Windows server.

.DESCRIPTION
  Removes the scheduled tasks, firewall rules and program files. The database, the
  backups and (unless -RemoveConfig) the settings are KEPT: dropping a shop's books is
  never done by a script. Take a final backup first:  flask --app app backup
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$Root = "C:\nextcam",
    [switch]$RemoveConfig
)
. "$PSScriptRoot\common.ps1"

Write-Step "Stopping and removing scheduled tasks"
Stop-NextcamServer $Root
foreach ($t in @($TaskServer, $TaskBackup, $TaskRestoreTest)) {
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Write-Step "Removing firewall rules"
Get-NetFirewallRule -DisplayName "NEXTCAM*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule

Write-Step "Removing program files"
$current = Join-Path $Root "current"
if (Test-Path $current) { cmd /c rmdir "$current" | Out-Null }
Remove-Item -Recurse -Force (Join-Path $Root "releases") -ErrorAction SilentlyContinue
if ($RemoveConfig) {
    Write-Warn "removing $Root\config (.env with the backup key: make sure the key is kept elsewhere)"
    Remove-Item -Recurse -Force (Join-Path $Root "config")
}
Write-Host ""
Write-Host "Kept: the SQL Server database, the backup folders, $Root\logs" -ForegroundColor Yellow
if (-not $RemoveConfig) { Write-Host "Kept: $Root\config (.env)" -ForegroundColor Yellow }
