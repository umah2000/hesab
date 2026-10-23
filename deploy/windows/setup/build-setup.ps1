<#
.SYNOPSIS
  Build dist\nextcam-setup-<version>.exe (docs/install/windows-installer.md, «ساخت setup.exe»).

.DESCRIPTION
  On a Windows PC with the repository, Python 3.13, Node.js 22 and Inno Setup 6:

    powershell -ExecutionPolicy Bypass -File deploy\windows\setup\build-setup.ps1

  1. builds the web app and the release package with Windows wheels (works without
     internet on the shop's server): tools/release/build_release.py --build-frontend --wheels
  2. downloads the Visual C++ runtime into deploy\windows\setup\redist if it is not there
     (Python and ODBC Driver 18 are added by hand, see the guide);
  3. compiles deploy\windows\setup\nextcam.iss with Inno Setup.
#>
[CmdletBinding()]
param(
    [string]$Python = "py",
    [string]$Iscc = "",
    [switch]$SkipPackage
)
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$redist = Join-Path $PSScriptRoot "redist"
New-Item -ItemType Directory -Force -Path $redist | Out-Null

$version = (Select-String -Path (Join-Path $repo "backend\app\version.py") -Pattern '^VERSION = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "NEXTCAM $version" -ForegroundColor Cyan

if (-not $SkipPackage) {
    Write-Host "==> release package (web app + wheels)" -ForegroundColor Cyan
    Push-Location $repo
    try {
        & $Python -3.13 tools\release\build_release.py --out dist --build-frontend --wheels
        if ($LASTEXITCODE -ne 0) { throw "build_release.py failed" }
    } finally { Pop-Location }
}
$package = Join-Path $repo "dist\nextcam-$version"
if (-not (Test-Path (Join-Path $package "VERSION"))) { throw "$package is missing: run without -SkipPackage" }

Write-Host "==> prerequisites in $redist" -ForegroundColor Cyan
$vc = Join-Path $redist "vc_redist.x64.exe"
if (-not (Test-Path $vc)) {
    Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vc -UseBasicParsing
}
foreach ($f in @("python-amd64.exe", "msodbcsql.msi")) {
    if (Test-Path (Join-Path $redist $f)) { Write-Host "  ${f}: included" }
    else { Write-Warning "${f} is not in ${redist}: setup.exe will need it installed on the server already" }
}
if (-not (Test-Path (Join-Path $PSScriptRoot "Farsi.isl"))) {
    Write-Warning "Farsi.isl not found: the wizard's buttons will be in English (our pages are in Persian)"
}

if (-not $Iscc) {
    $Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) not found: install it from jrsoftware.org or pass -Iscc" }
Write-Host "==> compiling setup" -ForegroundColor Cyan
& $Iscc "/DAppVersion=$version" "/DPackageDir=$package" (Join-Path $PSScriptRoot "nextcam.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
$exe = Join-Path $repo "dist\nextcam-setup-$version.exe"
Write-Host "$exe" -ForegroundColor Green
Write-Host ("sha256 " + (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower())
