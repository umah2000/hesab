# Shared helpers for install.ps1 / upgrade.ps1 / uninstall.ps1 (Windows PowerShell 5.1+).
# Layout on the server:
#   <Root>\releases\<version>\   one folder per installed release (with its own .venv)
#   <Root>\current               junction to the running release
#   <Root>\config\.env           settings and secrets; readable by Administrators and SYSTEM only
#   <Root>\logs\                 output of the scheduled tasks

$ErrorActionPreference = "Stop"
$TaskServer = "NEXTCAM Server"
$TaskBackup = "NEXTCAM Backup"
$TaskRestoreTest = "NEXTCAM Restore Test"

function Write-Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Warn([string]$Text) { Write-Host "!!  $Text" -ForegroundColor Yellow }

function Get-PackageRoot {
    # deploy\windows\<script> -> package root (holds VERSION)
    $root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    if (-not (Test-Path (Join-Path $root "VERSION"))) { throw "VERSION not found: run the script from the extracted release package" }
    return $root
}

function Get-PackageVersion([string]$PackageRoot) {
    return (Get-Content (Join-Path $PackageRoot "VERSION") -Raw).Trim()
}

function Assert-Prerequisites([string]$Python) {
    Write-Step "Checking prerequisites"
    $ver = & $Python -3.13 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -ne 0 -or $ver -ne "3.13") { throw "Python 3.13 (64-bit) is required: install it from python.org with the 'py' launcher" }
    $odbc = Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server" -ErrorAction SilentlyContinue
    if (-not $odbc) { throw "ODBC Driver 18 for SQL Server is required (Microsoft download)" }
    Write-Host "Python $ver, ODBC Driver 18: ok"
}

function Install-ReleaseFiles([string]$PackageRoot, [string]$Root, [string]$Version, [string]$Python) {
    $target = Join-Path $Root "releases\$Version"
    Write-Step "Copying release $Version to $target"
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    # robocopy exit codes below 8 mean success
    robocopy $PackageRoot $target /MIR /NFL /NDL /NJH /NJS /XD wheels | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "copy failed (robocopy $LASTEXITCODE)" }

    Write-Step "Creating the Python environment"
    $venv = Join-Path $target "backend\.venv"
    & $Python -3.13 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    $py = Join-Path $venv "Scripts\python.exe"
    $wheels = Join-Path $PackageRoot "wheels"
    $source = @()
    if (Test-Path $wheels) { $source = @("--no-index", "--find-links", $wheels) } else { Write-Warn "no wheels folder: installing from the internet" }
    & $py -m pip install --quiet @source --upgrade pip
    & $py -m pip install --quiet @source -e (Join-Path $target "packages\nextcam-core") -e (Join-Path $target "backend")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    return $target
}

function Set-CurrentRelease([string]$Root, [string]$Target) {
    $current = Join-Path $Root "current"
    if (Test-Path $current) { cmd /c rmdir "$current" | Out-Null }
    cmd /c mklink /J "$current" "$Target" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "could not point $current at $Target" }
}

function Get-CurrentRelease([string]$Root) {
    $current = Join-Path $Root "current"
    if (-not (Test-Path $current)) { return $null }
    return (Get-Item $current).Target | Select-Object -First 1
}

function Invoke-Nextcam([string]$Root, [string]$Release, [string[]]$Arguments) {
    # Runs "flask --app app <args>" with the config folder as working directory (.env there).
    $py = Join-Path $Release "backend\.venv\Scripts\python.exe"
    Push-Location (Join-Path $Root "config")
    try {
        & $py -m flask --app app @Arguments
        return $LASTEXITCODE
    } finally { Pop-Location }
}

function Stop-NextcamServer([string]$Root) {
    Stop-ScheduledTask -TaskName $TaskServer -ErrorAction SilentlyContinue
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*app.serve*" -and $_.ExecutablePath -like "$Root*" }
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Wait-Ready([int]$Port, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:$Port/api/v1/system/ready"
            if ($r.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

function Register-NextcamTasks([string]$Root) {
    Write-Step "Registering scheduled tasks"
    $py = Join-Path $Root "current\backend\.venv\Scripts\python.exe"
    $config = Join-Path $Root "config"
    $logs = Join-Path $Root "logs"
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $server = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    $serverAction = New-ScheduledTaskAction -Execute "cmd.exe" -WorkingDirectory $config `
        -Argument "/c `"`"$py`" -m app.serve >> `"$logs\server.log`" 2>&1`""
    Register-ScheduledTask -TaskName $TaskServer -Action $serverAction -Principal $principal -Settings $server `
        -Trigger (New-ScheduledTaskTrigger -AtStartup) -Description "NEXTCAM web server" -Force | Out-Null

    $jobs = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4)
    $backupAction = New-ScheduledTaskAction -Execute "cmd.exe" -WorkingDirectory $config `
        -Argument "/c `"`"$py`" -m flask --app app backup >> `"$logs\backup.log`" 2>&1`""
    Register-ScheduledTask -TaskName $TaskBackup -Action $backupAction -Principal $principal -Settings $jobs `
        -Trigger (New-ScheduledTaskTrigger -Daily -At "23:30") -Description "NEXTCAM daily backup + encrypted copy" -Force | Out-Null
    $restoreAction = New-ScheduledTaskAction -Execute "cmd.exe" -WorkingDirectory $config `
        -Argument "/c `"`"$py`" -m flask --app app backup-restore-test >> `"$logs\backup.log`" 2>&1`""
    Register-ScheduledTask -TaskName $TaskRestoreTest -Action $restoreAction -Principal $principal -Settings $jobs `
        -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "04:00") -Description "NEXTCAM weekly restore test" -Force | Out-Null
}

function Remove-OldReleases([string]$Root, [int]$Keep = 3) {
    $current = Get-CurrentRelease $Root
    Get-ChildItem (Join-Path $Root "releases") -Directory | Sort-Object CreationTime -Descending |
        Select-Object -Skip $Keep | Where-Object { $_.FullName -ne $current } |
        ForEach-Object { Write-Host "removing old release $($_.Name)"; Remove-Item -Recurse -Force $_.FullName }
}
