# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $IsWindows -or $env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'This bootstrap is only for ephemeral GitHub-hosted Windows runners.'
}

# The source and object directory need more than the hosted image guarantees.
# Reclaim only unused Android, Java and Haskell tools on this disposable runner;
# keep MSVC, the Windows SDK, Rust, Node, Python and all security protections.
Get-PSDrive -PSProvider FileSystem | Select-Object Name, Used, Free | Format-Table
$unused = @(
    'C:\Android', 'C:\ghcup', 'C:\Program Files\Java',
    'C:\Program Files\Eclipse Adoptium'
)
$unused += @(Get-ChildItem -LiteralPath 'C:\hostedtoolcache\windows' -Filter 'Java*' -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$unused += @(Get-ChildItem -LiteralPath 'C:\Program Files\Microsoft' -Filter 'jdk*' -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
foreach ($path in $unused) {
    if ((Get-PSDrive C).Free -ge 45GB) {
        break
    }
    if (Test-Path -LiteralPath $path) {
        Write-Output "Reclaiming unused tool directory: $path"
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
$freeGiB = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Write-Output "Free space on C: after cleanup: $freeGiB GiB"
if ((Get-PSDrive C).Free -lt 45GB) {
    throw "The Windows build needs at least 45 GiB free on C:; available: $freeGiB GiB."
}

# A short source path avoids MAX_PATH failures in vendored dependency names.
# Keep the checkout intact for the checkout action's authentication cleanup.
$source = 'C:\bonsai'
if (Test-Path -LiteralPath $source) {
    throw 'Unexpected existing C:\bonsai; refusing to overwrite it.'
}
Copy-Item -LiteralPath $env:GITHUB_WORKSPACE -Destination $source -Recurse

$version = $env:BONSAI_VERSION
if ([string]::IsNullOrEmpty($version)) {
    $configuration = Get-Content -LiteralPath "$source\surfer.json" -Raw | ConvertFrom-Json
    $version = $configuration.brands.release.release.displayVersion
}
if ($version -notmatch '^[0-9][0-9A-Za-z.]*-bonsai\.[0-9]+\z') {
    throw 'Expected a Bonsai release version, such as 1.25t-bonsai.1.'
}
"BONSAI_VERSION=$version" | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8

$installer = Join-Path $env:RUNNER_TEMP 'MozillaBuildSetup-4.2.1.exe'
Invoke-WebRequest -Uri 'https://ftp.mozilla.org/pub/mozilla/libraries/win32/MozillaBuildSetup-4.2.1.exe' -OutFile $installer
$expected = '8ef5b3d2087e4867dc75bf19f5e62f12e917f518239415723cc70896b6f1e3d8'
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'MozillaBuild installer SHA-256 does not match the pinned official download.'
}
if (Test-Path -LiteralPath 'C:\mozilla-build') {
    throw 'Unexpected existing MozillaBuild installation; refusing to overwrite it.'
}
$process = Start-Process -FilePath $installer -ArgumentList '/S' -PassThru
if (-not $process.WaitForExit(300000)) {
    $process.Kill($true)
    throw 'MozillaBuild installation exceeded five minutes.'
}
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath 'C:\mozilla-build\start-shell.bat')) {
    throw "MozillaBuild installation failed with exit code $($process.ExitCode)."
}
# Do not add Defender exclusions or disable its protection to speed up a build.
