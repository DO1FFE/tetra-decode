[CmdletBinding()]
param(
    [switch] $InstallGnuRadio
)

$ErrorActionPreference = 'Continue'
$InstallRoot = Join-Path ${env:ProgramData} 'tetra-decode'
$LogPath = Join-Path $InstallRoot 'windows-postinstall.log'

function Write-Log {
    param([string] $Message)
    $line = "$(Get-Date -Format s) $Message"
    Write-Host $line
    Add-Content -Path $LogPath -Value $line -ErrorAction SilentlyContinue
}

function Add-ToPath {
    param([string] $Directory)
    if (-not (Test-Path $Directory)) { return }
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if (-not $machinePath) { $machinePath = '' }
    $paths = $machinePath.Split(';') | Where-Object { $_ }
    if ($paths -contains $Directory) {
        return
    }
    [Environment]::SetEnvironmentVariable('Path', (($paths + $Directory) -join ';'), 'Machine')
    if (-not ($env:Path.Split(';') -contains $Directory)) {
        $env:Path = $env:Path + ';' + $Directory
    }
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Write-Log 'Starte Windows-Nachinstallation.'

foreach ($toolPath in @(
    (Join-Path $InstallRoot 'rtl-sdr\x64'),
    (Join-Path $InstallRoot 'osmocom-tetra'),
    (Join-Path $InstallRoot 'zadig')
)) {
    Add-ToPath $toolPath
    Write-Log "PATH geprueft: $toolPath"
}

$requiredRtl = @('rtl_sdr.exe', 'rtl_fm.exe', 'rtl_power.exe', 'rtl_test.exe')
foreach ($binary in $requiredRtl) {
    $candidate = Join-Path (Join-Path $InstallRoot 'rtl-sdr\x64') $binary
    if (Test-Path $candidate) {
        Write-Log "RTL-SDR vorhanden: $binary"
    } else {
        Write-Log "WARNUNG: RTL-SDR fehlt: $binary"
    }
}

$zadig = Join-Path $InstallRoot 'zadig\zadig.exe'
if (Test-Path $zadig) {
    Write-Log "Zadig vorhanden: $zadig"
} else {
    Write-Log 'WARNUNG: Zadig wurde nicht im Installer-Payload gefunden.'
}

$osmocomRoot = Join-Path $InstallRoot 'osmocom-tetra'
$requiredOsmocom = @('tetra-rx.exe', 'float_to_bits.exe', 'msys-2.0.dll')
$osmocomComplete = $true
foreach ($binary in $requiredOsmocom) {
    $candidate = Join-Path $osmocomRoot $binary
    if (Test-Path $candidate) {
        Write-Log "Osmocom-TETRA vorhanden: $binary"
    } else {
        Write-Log "WARNUNG: Osmocom-TETRA fehlt: $binary"
        $osmocomComplete = $false
    }
}

$sourceInstaller = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'ensure_osmocom_tetra.ps1'
if ($osmocomComplete) {
    Write-Log 'Native Osmocom-TETRA-Binaries sind vorhanden; WSL-/Source-Fallback wird uebersprungen.'
} elseif (Test-Path $sourceInstaller) {
    Write-Log 'Pruefe Osmocom-TETRA Source-/WSL-Integration.'
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $sourceInstaller *>&1 |
            ForEach-Object { Write-Log $_.ToString() }
    } catch {
        Write-Log "WARNUNG: Osmocom-TETRA Source-/WSL-Integration fehlgeschlagen: $_"
    }
} else {
    Write-Log 'WARNUNG: ensure_osmocom_tetra.ps1 wurde nicht gefunden.'
}

if ($InstallGnuRadio) {
    $gnuradioInstaller = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'ensure_gnuradio_windows.ps1'
    if (Test-Path $gnuradioInstaller) {
        Write-Log 'Pruefe GNU Radio/Radioconda fuer Live-Demodulation.'
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $gnuradioInstaller *>&1 |
                ForEach-Object { Write-Log $_.ToString() }
            if ($LASTEXITCODE -ne 0) {
                Write-Log "WARNUNG: GNU Radio/Radioconda Setup meldete Exitcode $LASTEXITCODE."
            }
        } catch {
            Write-Log "WARNUNG: GNU Radio/Radioconda konnte nicht automatisch eingerichtet werden: $_"
        }
    } else {
        Write-Log 'WARNUNG: ensure_gnuradio_windows.ps1 wurde nicht gefunden.'
    }
} else {
    Write-Log 'GNU Radio/Radioconda Installation wurde nicht angefordert.'
}

Write-Log 'Windows-Nachinstallation abgeschlossen.'
