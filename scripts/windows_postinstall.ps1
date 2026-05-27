[CmdletBinding()]
param(
    [switch] $InstallGnuRadio,
    [switch] $RequireBundledGnuRadio
)

$ErrorActionPreference = 'Continue'
$InstallRoot = Join-Path ${env:ProgramData} 'tetra-decode'
$LogPath = Join-Path $InstallRoot 'windows-postinstall.log'
$InstallationOk = $true

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
    Write-Log "PATH geprüft: $toolPath"
}

$requiredRtl = @('rtl_sdr.exe', 'rtl_fm.exe', 'rtl_power.exe', 'rtl_test.exe')
foreach ($binary in $requiredRtl) {
    $candidate = Join-Path (Join-Path $InstallRoot 'rtl-sdr\x64') $binary
    if (Test-Path $candidate) {
        Write-Log "RTL-SDR vorhanden: $binary"
    } else {
        Write-Log "WARNUNG: RTL-SDR fehlt: $binary"
        $InstallationOk = $false
    }
}

$zadig = Join-Path $InstallRoot 'zadig\zadig.exe'
if (Test-Path $zadig) {
    Write-Log "Zadig vorhanden: $zadig"
} else {
    Write-Log 'WARNUNG: Zadig wurde nicht im Installer-Payload gefunden.'
    $InstallationOk = $false
}

$osmocomRoot = Join-Path $InstallRoot 'osmocom-tetra'
$requiredOsmocom = @('tetra-rx.exe', 'float_to_bits.exe', 'msys-2.0.dll', 'msys-gcc_s-seh-1.dll')
$osmocomComplete = $true
foreach ($binary in $requiredOsmocom) {
    $candidate = Join-Path $osmocomRoot $binary
    if (Test-Path $candidate) {
        Write-Log "Osmocom-TETRA vorhanden: $binary"
    } else {
        Write-Log "WARNUNG: Osmocom-TETRA fehlt: $binary"
        $osmocomComplete = $false
        $InstallationOk = $false
    }
}

$sourceInstaller = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'ensure_osmocom_tetra.ps1'
if ($osmocomComplete) {
    Write-Log 'Native Osmocom-TETRA-Binaries sind vorhanden; WSL-/Source-Fallback wird übersprungen.'
} elseif (Test-Path $sourceInstaller) {
    Write-Log 'Prüfe Osmocom-TETRA Source-/WSL-Integration.'
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $sourceInstaller *>&1 |
            ForEach-Object { Write-Log $_.ToString() }
    } catch {
        Write-Log "WARNUNG: Osmocom-TETRA Source-/WSL-Integration fehlgeschlagen: $_"
    }
} else {
    Write-Log 'WARNUNG: ensure_osmocom_tetra.ps1 wurde nicht gefunden.'
}

$demodScript = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) 'third_party\osmo-tetra\src\demod\simdemod3.py'
if (Test-Path $demodScript) {
    Write-Log "Osmocom-TETRA-Demodulator vorhanden: $demodScript"
} else {
    Write-Log 'WARNUNG: simdemod3.py fehlt. Die native Windows-Pipeline benötigt das initialisierte osmo-tetra-Submodule.'
    $InstallationOk = $false
}

if ($InstallGnuRadio) {
    $gnuradioInstaller = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'ensure_gnuradio_windows.ps1'
    if (Test-Path $gnuradioInstaller) {
        Write-Log 'Prüfe GNU Radio/Radioconda für Live-Demodulation.'
        try {
            $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $gnuradioInstaller)
            if ($RequireBundledGnuRadio) {
                $args += '-RequireBundledGnuRadio'
            }
            & powershell @args *>&1 |
                ForEach-Object { Write-Log $_.ToString() }
            if ($LASTEXITCODE -ne 0) {
                Write-Log "WARNUNG: GNU Radio/Radioconda Setup meldete Exitcode $LASTEXITCODE."
                $InstallationOk = $false
            }
        } catch {
            Write-Log "WARNUNG: GNU Radio/Radioconda konnte nicht automatisch eingerichtet werden: $_"
            $InstallationOk = $false
        }
    } else {
        Write-Log 'WARNUNG: ensure_gnuradio_windows.ps1 wurde nicht gefunden.'
        $InstallationOk = $false
    }
} else {
    Write-Log 'GNU Radio/Radioconda Installation wurde nicht angefordert.'
}

if ($InstallationOk) {
    Write-Log 'Windows-Nachinstallation abgeschlossen.'
    exit 0
}

Write-Log 'Windows-Nachinstallation mit Fehlern beendet.'
exit 1

# © 2026 Erik Schauer, do1ffe@darc.de
