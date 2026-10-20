<#
.SYNOPSIS
  First installation of the NEXTCAM server on the shop's Windows server (docs/install/windows-installer.md).

.DESCRIPTION
  Before running: SQL Server 2019 with the database and login from create-database.sql,
  Python 3.13 (64-bit, with the py launcher) and ODBC Driver 18 for SQL Server.
  Run from the extracted release package, in an elevated PowerShell:

    powershell -ExecutionPolicy Bypass -File .\deploy\windows\install.ps1 -OrgName "سوپرمارکت ..."

  Creates <Root>\releases\<version>, <Root>\current, <Root>\config\.env (secrets, locked
  down), the database schema, the administrator, scheduled tasks and the firewall rule.
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OrgName,
    [string]$Root = "C:\nextcam",
    [string]$SqlServer = "localhost",
    [string]$Database = "nextcam",
    [string]$SqlUser = "nextcam_app",
    [int]$Port = 8080,
    [string]$BackupDir = "D:\nextcam-backup",
    # Second destination for encrypted backup copies (USB disk, NAS share, synced folder).
    [string]$CopyDir = "",
    # Behind Caddy on the same machine (deploy\https): listen on 127.0.0.1 only.
    [switch]$Https,
    [string]$Python = "py"
)
. "$PSScriptRoot\common.ps1"

$package = Get-PackageRoot
$version = Get-PackageVersion $package
Write-Host "NEXTCAM $version -> $Root"
if (Get-CurrentRelease $Root) { throw "NEXTCAM is already installed in $Root; use upgrade.ps1" }
Assert-Prerequisites $Python

foreach ($d in @("config", "logs", "releases")) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
if ($CopyDir) { New-Item -ItemType Directory -Force -Path $CopyDir | Out-Null }

# Settings and secrets: only Administrators (S-1-5-32-544) and SYSTEM (S-1-5-18), by SID so
# that a Persian (or any) Windows language works.
$config = Join-Path $Root "config"
icacls $config /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
$envFile = Join-Path $config ".env"
$backupKey = $null
if (Test-Path $envFile) {
    Write-Warn "$envFile exists: keeping it"
} else {
    Write-Step "Writing $envFile"
    $secure = Read-Host "SQL Server password for login '$SqlUser'" -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    $pwd = [uri]::EscapeDataString($plain)
    $rand = { param($n) $b = New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $b }
    $secret = [Convert]::ToBase64String((& $rand 48))
    $backupKey = [Convert]::ToBase64String((& $rand 32)).Replace("+", "-").Replace("/", "_")
    $lines = @(
        "NEXTCAM_ENV=production",
        "NEXTCAM_DATABASE_URL=mssql+pyodbc://${SqlUser}:${pwd}@${SqlServer}/${Database}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes",
        "NEXTCAM_SECRET_KEY=$secret",
        "NEXTCAM_STATIC_DIR=$Root\current\frontend-dist",
        "NEXTCAM_PORT=$Port",
        "NEXTCAM_LOG_LEVEL=WARNING",
        "NEXTCAM_BACKUP_DIR=$BackupDir",
        "NEXTCAM_BACKUP_KEEP=14",
        "NEXTCAM_BACKUP_KEY=$backupKey"
    )
    if ($CopyDir) { $lines += "NEXTCAM_BACKUP_COPY_DIR=$CopyDir"; $lines += "NEXTCAM_BACKUP_COPY_KEEP=30" }
    if ($Https) {
        $lines += "NEXTCAM_HOST=127.0.0.1"; $lines += "NEXTCAM_TRUSTED_PROXY=127.0.0.1"; $lines += "NEXTCAM_COOKIE_SECURE=true"
    } else {
        $lines += "# Until HTTPS is set up (docs/install/https.md):"; $lines += "NEXTCAM_COOKIE_SECURE=false"
    }
    # UTF-8 without BOM: a BOM would hide the first setting from the program.
    [IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding $false))
    $plain = $null
}

$release = Install-ReleaseFiles $package $Root $version $Python
Set-CurrentRelease $Root $release

Write-Step "Creating the database schema"
if ((Invoke-Nextcam $Root $release @("upgrade", "--skip-backup")) -ne 0) { throw "creating the schema failed (see above)" }
Write-Step "Organization and administrator (you will be asked for the admin password)"
if ((Invoke-Nextcam $Root $release @("setup", "--org-name", $OrgName)) -ne 0) { throw "setup failed" }
if ((Invoke-Nextcam $Root $release @("check-integrity")) -ne 0) { throw "integrity check failed after installation" }

Register-NextcamTasks $Root
Write-Step "Firewall (private network only)"
if ($Https) {
    New-NetFirewallRule -DisplayName "NEXTCAM HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80, 443 -Action Allow -Profile Private | Out-Null
} else {
    New-NetFirewallRule -DisplayName "NEXTCAM $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private | Out-Null
}

Write-Step "Starting the server"
Start-ScheduledTask -TaskName $TaskServer
if (Wait-Ready $Port) { Write-Host "NEXTCAM $version is running: http://<this server>:$Port/" -ForegroundColor Green }
else { Write-Warn "the server did not answer yet; see $Root\logs\server.log" }

Write-Step "Backup now (and the encrypted copy, if configured)"
Invoke-Nextcam $Root $release @("backup") | Out-Null

if ($backupKey) {
    Write-Host ""
    Write-Host "BACKUP KEY (write it down and keep it OUTSIDE this server; without it encrypted backups cannot be restored):" -ForegroundColor Yellow
    Write-Host "    $backupKey" -ForegroundColor Yellow
    Write-Host "It is also in $envFile (Administrators only)."
}
