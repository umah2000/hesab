<#
.SYNOPSIS
  Upgrade an installed NEXTCAM server to the release this script ships with.

.DESCRIPTION
  Run from the extracted NEW release package, in an elevated PowerShell, preferably after
  closing time (registers with the Device Agent keep selling offline meanwhile):

    powershell -ExecutionPolicy Bypass -File .\deploy\windows\upgrade.ps1

  1. installs the new release side by side (<Root>\releases\<version>) while the old runs;
  2. stops the server;
  3. "flask upgrade" from the new release: backup first, migrations in one transaction,
     integrity checks (see docs/install/upgrade.md);
  4. on success switches <Root>\current to the new release and starts it; if the database
     step stopped or rolled back, the old release is started again unchanged.
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$Root = "C:\nextcam",
    [int]$Port = 8080,
    [string]$Python = "py",
    [int]$KeepReleases = 3
)
. "$PSScriptRoot\common.ps1"

$package = Get-PackageRoot
$version = Get-PackageVersion $package
$old = Get-CurrentRelease $Root
if (-not $old) { throw "no NEXTCAM installation in $Root; use install.ps1" }
$oldVersion = Split-Path -Leaf $old
Write-Host "NEXTCAM $oldVersion -> $version ($Root)"
if ($oldVersion -eq $version) { Write-Warn "this version is already installed; reinstalling its files" }
Assert-Prerequisites $Python

$new = Install-ReleaseFiles $package $Root $version $Python

Write-Step "Stopping the server"
Stop-NextcamServer $Root

Write-Step "Upgrading the database (backup, migrations, checks)"
# --force: the activity check is for manual runs; this script has just stopped the server.
$code = Invoke-Nextcam $Root $new @("upgrade", "--force")

if ($code -eq 1) {
    Write-Warn "the database was NOT changed (see the message above); starting $oldVersion again"
    Start-ScheduledTask -TaskName $TaskServer
    if (-not (Wait-Ready $Port)) { Write-Warn "the old release did not answer; see $Root\logs\server.log" }
    exit 1
}

Set-CurrentRelease $Root $new
Register-NextcamTasks $Root
Write-Step "Starting $version"
Start-ScheduledTask -TaskName $TaskServer
if (-not (Wait-Ready $Port)) {
    Write-Warn "$version does not answer on port $Port. The database is already upgraded, so the old release may not fit it."
    Write-Warn "See $Root\logs\server.log and docs\install\upgrade.md (restore from the pre-upgrade backup if needed)."
    exit 3
}
if ($code -eq 2) {
    Write-Warn "$version is running, but integrity checks reported problems (see above). Contact support."
    exit 2
}
Remove-OldReleases $Root $KeepReleases
Write-Host "NEXTCAM $version is running." -ForegroundColor Green
