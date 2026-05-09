[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SourceDir = Join-Path $ProjectRoot 'third_party\osmo-tetra'

function Write-Step {
    param([string] $Message)
    Write-Host "[osmocom-tetra] $Message"
}

if (-not (Test-Path (Join-Path $SourceDir 'src\Makefile'))) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git wird benoetigt, um third_party/osmo-tetra zu initialisieren."
    }
    Write-Step "Initialisiere third_party/osmo-tetra..."
    git -C $ProjectRoot submodule update --init --recursive third_party/osmo-tetra
    if ($LASTEXITCODE -ne 0) {
        throw "Git-Submodule konnte nicht initialisiert werden."
    }
}

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
    Write-Warning "Native Windows-Binaries fuer osmocom-tetra werden nicht mehr zuverlaessig bereitgestellt."
    Write-Warning "Das Source-Submodule ist vorhanden. Baue es unter Linux/WSL mit scripts/ensure_osmocom_tetra.sh."
    return
}

try {
    $wslProjectRoot = (& wsl.exe wslpath -a $ProjectRoot 2>$null).Trim()
    if (-not $wslProjectRoot) {
        throw "wslpath lieferte keinen Pfad."
    }
    $quotedRoot = $wslProjectRoot.Replace("'", "'\''")
    Write-Step "Baue osmocom-tetra in WSL..."
    & wsl.exe -- bash -lc "cd '$quotedRoot' && chmod +x scripts/ensure_osmocom_tetra.sh && scripts/ensure_osmocom_tetra.sh"
    if ($LASTEXITCODE -ne 0) {
        throw "WSL-Build ist fehlgeschlagen."
    }
} catch {
    Write-Warning $_
    Write-Warning "Installiere in WSL die Pakete build-essential, pkg-config, libosmocore-dev und gnuradio und fuehre scripts/ensure_osmocom_tetra.sh erneut aus."
}
