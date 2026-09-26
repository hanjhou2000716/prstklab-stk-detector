$ErrorActionPreference = "Stop"

$tools = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.quality-tools"))
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$staging = Join-Path $tools "download-staging"
New-Item -ItemType Directory -Force -Path $staging | Out-Null

function Install-VerifiedArchive([string]$Url, [string]$Archive, [string]$ExpectedHash) {
    $download = Join-Path $staging $Archive
    Invoke-WebRequest -Uri $Url -OutFile $download
    $actual = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedHash.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Archive"
    }
    $extract = Join-Path $staging ([System.IO.Path]::GetFileNameWithoutExtension($Archive))
    Expand-Archive -LiteralPath $download -DestinationPath $extract -Force
    return $extract
}

try {
    $actionVersion = "1.7.7"
    $actionAsset = "actionlint_{0}_windows_amd64.zip" -f $actionVersion
    $actionBase = "https://github.com/rhysd/actionlint/releases/download/v$actionVersion"
    $checksumName = "actionlint_{0}_checksums.txt" -f $actionVersion
    $checksumPath = Join-Path $staging "actionlint-checksums.txt"
    Invoke-WebRequest -Uri "$actionBase/$checksumName" -OutFile $checksumPath
    $line = Get-Content -LiteralPath $checksumPath | Where-Object { $_ -match "\s$([regex]::Escape($actionAsset))$" } | Select-Object -First 1
    if (-not $line) { throw "Official actionlint checksum entry is missing." }
    $expected = ($line -split "\s+")[0]
    $actionDir = Install-VerifiedArchive "$actionBase/$actionAsset" $actionAsset $expected
    $actionExe = Get-ChildItem -LiteralPath $actionDir -Filter "actionlint.exe" -Recurse | Select-Object -First 1
    if (-not $actionExe) { throw "actionlint.exe missing from verified archive." }
    Copy-Item -LiteralPath $actionExe.FullName -Destination (Join-Path $tools "actionlint.exe") -Force

    $shellArchive = "shellcheck-v0.11.0.zip"
    $shellDir = Install-VerifiedArchive "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/$shellArchive" $shellArchive "8a4e35ab0b331c85d73567b12f2a444df187f483e5079ceffa6bda1faa2e740e"
    $shellExe = Get-ChildItem -LiteralPath $shellDir -Filter "shellcheck.exe" -Recurse | Select-Object -First 1
    if (-not $shellExe) { throw "shellcheck.exe missing from verified archive." }
    Copy-Item -LiteralPath $shellExe.FullName -Destination (Join-Path $tools "shellcheck.exe") -Force
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}

$env:PATH = "$tools;$env:PATH"
& (Join-Path $tools "actionlint.exe") -version
& (Join-Path $tools "shellcheck.exe") --version
Write-Host "Pinned quality tools are ready for this PowerShell session: $tools"
