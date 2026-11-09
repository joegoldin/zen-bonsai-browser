# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $IsWindows -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'This installation smoke test is only for an ephemeral hosted Windows runner.'
}

function Invoke-TestProcess {
    param([string]$Executable, [string[]]$Arguments, [int]$TimeoutSeconds)
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill($true)
        throw "$Executable exceeded its test deadline."
    }
    if ($process.ExitCode -ne 0) {
        throw "$Executable failed with exit code $($process.ExitCode)."
    }
}

$artifacts = 'D:\bonsai\artifacts\windows-release'
$temporary = Join-Path $env:RUNNER_TEMP ('bonsai-install-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$target = Join-Path $temporary 'application'
$settings = Join-Path $temporary 'installer.ini'
@"
[Install]
InstallDirectoryPath=$target
DesktopShortcut=false
StartMenuShortcuts=false
TaskbarShortcut=false
MaintenanceService=false
"@ | Set-Content -LiteralPath $settings -Encoding utf8
Invoke-TestProcess -Executable "$artifacts\zen.windows-x86_64.installer.exe" `
    -Arguments @('/S', "/INI=`"$settings`"") -TimeoutSeconds 180

$application = Join-Path $target 'zen.exe'
if (-not (Test-Path -LiteralPath $application)) {
    throw 'The full installer did not create zen.exe in the requested user-writable directory.'
}
$ini = Get-Content -LiteralPath (Join-Path $target 'application.ini') -Raw
if ($ini -notmatch ('(?m)^Version=' + [regex]::Escape($env:BONSAI_VERSION) + '\r?$')) {
    throw 'The installed application version does not match the requested Bonsai release.'
}
if ($ini -match 'updates\.zen-browser\.app|github\.com/zen-browser/desktop') {
    throw 'The installed application still advertises an upstream update or source endpoint.'
}

$profile = Join-Path $temporary 'profile'
New-Item -ItemType Directory -Path $profile | Out-Null
$screenshot = Join-Path $artifacts 'installed-startup.png'
Invoke-TestProcess -Executable $application -Arguments @(
    '--headless', '--no-remote', '--wait-for-browser',
    '--profile', "`"$profile`"", '--screenshot', "`"$screenshot`"", 'about:blank'
) -TimeoutSeconds 120
if (-not (Test-Path -LiteralPath $screenshot) -or (Get-Item -LiteralPath $screenshot).Length -eq 0) {
    throw 'The installed browser did not render a startup screenshot.'
}
Write-Output 'Full Windows installer, installed version, endpoint isolation, and headless startup passed.'
