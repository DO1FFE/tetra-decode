[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
    throw 'WSL wird für das lokale TETRA-Audio-Backend benötigt.'
}

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string] $Path)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath -match '^([A-Za-z]):\\(.*)$') {
        $drive = $Matches[1].ToLowerInvariant()
        $rest = $Matches[2] -replace '\\', '/'
        return "/mnt/$drive/$rest"
    }
    throw "Pfad kann nicht nach WSL umgerechnet werden: $fullPath"
}

$wslProjectRoot = Convert-ToWslPath -Path $ProjectRoot
$quotedRoot = $wslProjectRoot.Replace("'", "'\''")
& wsl.exe -- bash -lc "cd '$quotedRoot' && chmod +x scripts/ensure_tetra_audio_backend.sh && scripts/ensure_tetra_audio_backend.sh"
if ($LASTEXITCODE -ne 0) {
    throw 'Der Build des TETRA-Audio-Backends ist fehlgeschlagen.'
}

# © 2026 Erik Schauer, do1ffe@darc.de
