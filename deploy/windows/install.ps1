<#
.SYNOPSIS
  First installation of the NEXTCAM server on the shop's Windows server (docs/install/windows-installer.md).

.DESCRIPTION
  Before running: SQL Server 2019 with the database and login from create-database.sql,
  Python 3.13 (64-bit, with the py launcher) and ODBC Driver 18 for SQL Server.
  Run from the extracted release package, in an elevated PowerShell:

    powershell -ExecutionPolicy Bypass -File .\deploy\windows\install.ps1 -OrgName "سوپرمارکت ..."

  The graphical setup.exe (deploy\windows\setup) runs this same script and passes every
  answer in NEXTCAM_INSTALL_* environment variables, so no password is ever on a command
  line; -CreateDatabase then creates the database and login (create_database.py).

  Creates <Root>\releases\<version>, <Root>\current, <Root>\config\.env (secrets, locked
  down), the database schema, the administrator, scheduled tasks and the firewall rule.
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$OrgName = $env:NEXTCAM_INSTALL_ORG,
    [string]$Root = "C:\nextcam",
    [string]$SqlServer = $(if ($env:NEXTCAM_INSTALL_SQL_SERVER) { $env:NEXTCAM_INSTALL_SQL_SERVER } else { "localhost" }),
    [string]$Database = $(if ($env:NEXTCAM_INSTALL_DATABASE) { $env:NEXTCAM_INSTALL_DATABASE } else { "nextcam" }),
    [string]$SqlUser = $(if ($env:NEXTCAM_INSTALL_SQL_USER) { $env:NEXTCAM_INSTALL_SQL_USER } else { "nextcam_app" }),
    [int]$Port = $(if ($env:NEXTCAM_INSTALL_PORT) { [int]$env:NEXTCAM_INSTALL_PORT } else { 8080 }),
    [string]$BackupDir = $(if ($env:NEXTCAM_INSTALL_BACKUP_DIR) { $env:NEXTCAM_INSTALL_BACKUP_DIR } else { "D:\nextcam-backup" }),
    # Second destination for encrypted backup copies (USB disk, NAS share, synced folder).
    [string]$CopyDir = $env:NEXTCAM_INSTALL_COPY_DIR,
    # Behind Caddy on the same machine (deploy\https): listen on 127.0.0.1 only.
    [switch]$Https,
    # Create the database and the login first (needs a sysadmin: Windows authentication,
    # or NEXTCAM_INSTALL_SQL_ADMIN_USER / _PASSWORD).
    [switch]$CreateDatabase,
    [string]$AdminUser = "admin",
    [string]$Python = "py"
)
. "$PSScriptRoot\common.ps1"

# Run from setup.exe: show the error and wait, so the window does not just vanish.
trap {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    if ($env:NEXTCAM_INSTALL_PAUSE_ON_ERROR) { Read-Host "Press Enter to close" | Out-Null }
    exit 1
}
if (-not $OrgName) { throw "-OrgName is required (the shop's name)" }

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
    if ($env:NEXTCAM_INSTALL_SQL_PASSWORD) {
        $plain = $env:NEXTCAM_INSTALL_SQL_PASSWORD
    } else {
        $secure = Read-Host "SQL Server password for login '$SqlUser'" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
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
    if ($CreateDatabase -and -not $env:NEXTCAM_INSTALL_SQL_PASSWORD) { $env:NEXTCAM_INSTALL_SQL_PASSWORD = $plain }
    $plain = $null
}

$release = Install-ReleaseFiles $package $Root $version $Python

if ($CreateDatabase) {
    Write-Step "Creating the database $Database and the login $SqlUser on $SqlServer"
    if (-not $env:NEXTCAM_INSTALL_SQL_PASSWORD) { throw "-CreateDatabase needs the SQL password (a new .env, or NEXTCAM_INSTALL_SQL_PASSWORD)" }
    $env:NEXTCAM_INSTALL_SQL_SERVER = $SqlServer
    $env:NEXTCAM_INSTALL_DATABASE = $Database
    $env:NEXTCAM_INSTALL_SQL_USER = $SqlUser
    & (Join-Path $release "backend\.venv\Scripts\python.exe") (Join-Path $PSScriptRoot "create_database.py")
    if ($LASTEXITCODE -ne 0) { throw "creating the database failed (see above)" }
}

Write-Step "Creating the database schema"
if ((Invoke-Nextcam $Root $release @("upgrade", "--skip-backup")) -ne 0) { throw "creating the schema failed (see above)" }
Write-Step "Organization and administrator"
# NEXTCAM_SETUP_ADMIN_PASSWORD (from setup.exe) answers the password prompt.
if ((Invoke-Nextcam $Root $release @("setup", "--org-name", $OrgName, "--admin-username", $AdminUser)) -ne 0) { throw "setup failed" }
if ((Invoke-Nextcam $Root $release @("check-integrity")) -ne 0) { throw "integrity check failed after installation" }
# Only now is NEXTCAM "installed": a run that failed above can simply be run again.
Set-CurrentRelease $Root $release

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

if ($env:NEXTCAM_INSTALL_RESULT) {
    # For setup.exe's last page (a file in its own temp folder, deleted by it).
    $result = @("URL=http://$($env:COMPUTERNAME):$Port/", "BACKUP_KEY=$backupKey", "ENV=$envFile")
    [IO.File]::WriteAllLines($env:NEXTCAM_INSTALL_RESULT, $result, (New-Object Text.UTF8Encoding $false))
}

if ($backupKey) {
    Write-Host ""
    Write-Host "BACKUP KEY (write it down and keep it OUTSIDE this server; without it encrypted backups cannot be restored):" -ForegroundColor Yellow
    Write-Host "    $backupKey" -ForegroundColor Yellow
    Write-Host "It is also in $envFile (Administrators only)."
}
