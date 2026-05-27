[CmdletBinding()]
param(
    [switch] $KeinePythonErstellung,
    [switch] $KeinePaketInstallation,
    [string] $InnoSetupCompiler = '',
    [string] $Version = ''
)

$ErrorActionPreference = 'Stop'

$ProjektWurzel = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistOrdner = Join-Path $ProjektWurzel 'dist'
$InstallerOrdner = Join-Path $ProjektWurzel 'dist-installer'
$AppExe = Join-Path $DistOrdner 'tetra-decode.exe'
$InstallerSkript = Join-Path $ProjektWurzel 'installer.iss'
$InstallerDatei = Join-Path $InstallerOrdner 'TETRA-Decode-Windows-Setup.exe'
$PruefsummenDatei = "$InstallerDatei.sha256"

function Schreibe-Schritt {
    param([string] $Nachricht)
    Write-Host "[Windows-Paket] $Nachricht"
}

function Starte-Befehl {
    param(
        [Parameter(Mandatory)] [string] $Programm,
        [Parameter(Mandatory)] [string[]] $Argumente,
        [Parameter(Mandatory)] [string] $Fehlertext
    )

    & $Programm @Argumente
    if ($LASTEXITCODE -ne 0) {
        throw "$Fehlertext Exitcode: $LASTEXITCODE"
    }
}

function Finde-Python {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }
    throw 'Python wurde nicht gefunden. Bitte Python 3 installieren und erneut starten.'
}

function Initialisiere-Submodule {
    $demodulator = Join-Path $ProjektWurzel 'third_party\osmo-tetra\src\demod\simdemod3.py'
    if (Test-Path $demodulator) {
        Schreibe-Schritt "Osmocom-TETRA-Submodule ist vorhanden."
        return
    }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        throw 'Git wurde nicht gefunden. Das osmo-tetra-Submodule kann nicht initialisiert werden.'
    }

    Schreibe-Schritt 'Initialisiere osmo-tetra-Submodule...'
    Starte-Befehl -Programm $git.Source -Argumente @(
        '-C', $ProjektWurzel, 'submodule', 'update', '--init', '--recursive', 'third_party/osmo-tetra'
    ) -Fehlertext 'Git-Submodule konnte nicht initialisiert werden.'
}

function Lade-GnuRadioPayload {
    $zielOrdner = Join-Path $ProjektWurzel 'installer_payload\gnuradio'
    New-Item -ItemType Directory -Force -Path $zielOrdner | Out-Null

    Schreibe-Schritt 'Ermittle aktuelle Radioconda/GNU-Radio-Version...'
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/radioconda/radioconda-installer/releases/latest'
    $assets = @($release.assets)
    $installerAsset = $assets |
        Where-Object { $_.name -like 'radioconda-*-Windows-x86_64.exe' } |
        Select-Object -First 1
    if (-not $installerAsset) {
        throw 'Konnte keinen Radioconda-Windows-Installer im aktuellen Release finden.'
    }
    $shaAsset = $assets |
        Where-Object { $_.name -eq "$($installerAsset.name).sha256" } |
        Select-Object -First 1

    $installerZiel = Join-Path $zielOrdner $installerAsset.name
    $shaZiel = "$installerZiel.sha256"
    if (-not (Test-Path $installerZiel)) {
        Schreibe-Schritt "Lade Radioconda/GNU Radio: $($installerAsset.name)"
        Invoke-WebRequest -Uri $installerAsset.browser_download_url -OutFile $installerZiel
    } else {
        Schreibe-Schritt "Radioconda/GNU Radio ist bereits vorhanden: $installerZiel"
    }

    if ($shaAsset) {
        Invoke-WebRequest -Uri $shaAsset.browser_download_url -OutFile $shaZiel
        $erwartet = ((Get-Content -Path $shaZiel -TotalCount 1) -split '\s+')[0].ToLowerInvariant()
        $erhalten = (Get-FileHash -Path $installerZiel -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($erwartet -ne $erhalten) {
            throw "Radioconda-Prüfsumme stimmt nicht. Erwartet: $erwartet, erhalten: $erhalten"
        }
        Schreibe-Schritt "Radioconda-Prüfsumme geprüft: $erhalten"
    } else {
        Write-Warning 'Für den Radioconda-Installer wurde keine SHA256-Datei gefunden.'
    }
}

function Pruefe-Payload {
    $benoetigteDateien = @(
        @{ Pfad = 'requirements.txt'; Beschreibung = 'Python-Abhängigkeiten' },
        @{ Pfad = 'installer_payload\rtl-sdr\x64\rtl_sdr.exe'; Beschreibung = 'RTL-SDR rtl_sdr.exe' },
        @{ Pfad = 'installer_payload\rtl-sdr\x64\rtl_fm.exe'; Beschreibung = 'RTL-SDR rtl_fm.exe' },
        @{ Pfad = 'installer_payload\rtl-sdr\x64\rtl_power.exe'; Beschreibung = 'RTL-SDR rtl_power.exe' },
        @{ Pfad = 'installer_payload\rtl-sdr\x64\rtl_test.exe'; Beschreibung = 'RTL-SDR rtl_test.exe' },
        @{ Pfad = 'installer_payload\rtl-sdr\x64\rtlsdr.dll'; Beschreibung = 'RTL-SDR Laufzeitbibliothek' },
        @{ Pfad = 'installer_payload\rtl-sdr\x64\pthreadVC2.dll'; Beschreibung = 'RTL-SDR pthread-Laufzeitbibliothek' },
        @{ Pfad = 'installer_payload\rtl-sdr\x64\msvcr100.dll'; Beschreibung = 'Microsoft C-Laufzeitbibliothek' },
        @{ Pfad = 'installer_payload\osmocom-tetra\tetra-rx.exe'; Beschreibung = 'Osmocom-TETRA tetra-rx.exe' },
        @{ Pfad = 'installer_payload\osmocom-tetra\float_to_bits.exe'; Beschreibung = 'Osmocom-TETRA float_to_bits.exe' },
        @{ Pfad = 'installer_payload\osmocom-tetra\msys-2.0.dll'; Beschreibung = 'MSYS2-Laufzeitbibliothek' },
        @{ Pfad = 'installer_payload\osmocom-tetra\msys-gcc_s-seh-1.dll'; Beschreibung = 'GCC-SEH-Laufzeitbibliothek' },
        @{ Pfad = 'installer_payload\zadig\zadig.exe'; Beschreibung = 'Zadig-Treiberwerkzeug' },
        @{ Pfad = 'third_party\osmo-tetra\src\demod\simdemod3.py'; Beschreibung = 'Osmocom-TETRA Demodulator-Skript' }
    )

    $fehlend = @()
    foreach ($datei in $benoetigteDateien) {
        $vollerPfad = Join-Path $ProjektWurzel $datei.Pfad
        if (-not (Test-Path $vollerPfad)) {
            $fehlend += "  - $($datei.Beschreibung): $($datei.Pfad)"
        }
    }

    if ($fehlend.Count -gt 0) {
        throw "Die Windows-Nutzlast ist unvollständig:`n$($fehlend -join [Environment]::NewLine)"
    }

    $gnuradioInstaller = Get-ChildItem -Path (Join-Path $ProjektWurzel 'installer_payload\gnuradio') -Filter 'radioconda-*-Windows-x86_64.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $gnuradioInstaller) {
        throw 'Radioconda/GNU Radio sollte eingebettet werden, aber der Installer fehlt.'
    }

    Schreibe-Schritt 'Windows-Nutzlast ist vollständig.'
}

function Baue-AppExe {
    if ($KeinePythonErstellung) {
        if (-not (Test-Path $AppExe)) {
            throw "Python-Erstellung wurde übersprungen, aber $AppExe fehlt."
        }
        Schreibe-Schritt "Nutze vorhandene EXE: $AppExe"
        return
    }

    $python = Finde-Python
    Schreibe-Schritt 'Installiere Python-Abhängigkeiten für den Windows-Build...'
    Starte-Befehl -Programm $python -Argumente @('-m', 'pip', 'install', '--upgrade', 'pip') `
        -Fehlertext 'pip konnte nicht aktualisiert werden.'
    Starte-Befehl -Programm $python -Argumente @('-m', 'pip', 'install', '-r', (Join-Path $ProjektWurzel 'requirements.txt')) `
        -Fehlertext 'Python-Abhängigkeiten konnten nicht installiert werden.'
    Starte-Befehl -Programm $python -Argumente @('-m', 'pip', 'install', 'pyinstaller') `
        -Fehlertext 'PyInstaller konnte nicht installiert werden.'

    Schreibe-Schritt 'Baue portable EXE mit PyInstaller...'
    Starte-Befehl -Programm $python -Argumente @(
        '-m', 'PyInstaller',
        '--clean',
        '--onefile',
        '--windowed',
        '--name', 'tetra-decode',
        (Join-Path $ProjektWurzel 'sdr_gui.py')
    ) -Fehlertext 'PyInstaller-Build ist fehlgeschlagen.'

    if (-not (Test-Path $AppExe)) {
        throw "PyInstaller wurde ausgeführt, aber $AppExe wurde nicht erzeugt."
    }
}

function Finde-InnoSetup {
    if ($InnoSetupCompiler) {
        if (Test-Path $InnoSetupCompiler) {
            return (Resolve-Path $InnoSetupCompiler).Path
        }
        throw "Der angegebene Inno-Setup-Compiler wurde nicht gefunden: $InnoSetupCompiler"
    }

    foreach ($name in @('iscc.exe', 'iscc')) {
        $befehl = Get-Command $name -ErrorAction SilentlyContinue
        if ($befehl) {
            return $befehl.Source
        }
    }

    $kandidaten = New-Object System.Collections.Generic.List[string]
    foreach ($wurzel in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
        if (-not $wurzel) {
            continue
        }
        $kandidaten.Add((Join-Path $wurzel 'Inno Setup 6\ISCC.exe'))
        $kandidaten.Add((Join-Path $wurzel 'Inno Setup 5\ISCC.exe'))
        $kandidaten.Add((Join-Path $wurzel 'Programs\Inno Setup 6\ISCC.exe'))
    }

    foreach ($kandidat in $kandidaten) {
        if (Test-Path $kandidat) {
            return $kandidat
        }
    }

    return $null
}

function Installiere-InnoSetup {
    if ($KeinePaketInstallation) {
        return
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Schreibe-Schritt 'Installiere Inno Setup über winget...'
        & $winget.Source install --id JRSoftware.InnoSetup -e --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0 -and (Finde-InnoSetup)) {
            return
        }
        Write-Warning "winget konnte Inno Setup nicht vollständig installieren. Exitcode: $LASTEXITCODE"
    }

    $choco = Get-Command choco -ErrorAction SilentlyContinue
    if ($choco) {
        Schreibe-Schritt 'Installiere Inno Setup über Chocolatey...'
        & $choco.Source install innosetup -y
        if ($LASTEXITCODE -eq 0 -and (Finde-InnoSetup)) {
            return
        }
        Write-Warning "Chocolatey konnte Inno Setup nicht vollständig installieren. Exitcode: $LASTEXITCODE"
    }
}

function Baue-Installer {
    $iscc = Finde-InnoSetup
    if (-not $iscc) {
        Installiere-InnoSetup
        $iscc = Finde-InnoSetup
    }
    if (-not $iscc) {
        throw 'Inno Setup Compiler (ISCC.exe) wurde nicht gefunden. Bitte Inno Setup installieren.'
    }

    New-Item -ItemType Directory -Force -Path $InstallerOrdner | Out-Null
    $argumente = @()
    if ($Version) {
        $argumente += "/DAppVersion=$Version"
    }
    $argumente += $InstallerSkript

    Schreibe-Schritt "Baue Installer mit $iscc..."
    Starte-Befehl -Programm $iscc -Argumente $argumente -Fehlertext 'Inno-Setup-Build ist fehlgeschlagen.'

    if (-not (Test-Path $InstallerDatei)) {
        throw "Inno Setup wurde ausgeführt, aber $InstallerDatei wurde nicht erzeugt."
    }
}

Push-Location $ProjektWurzel
try {
    Initialisiere-Submodule
    Lade-GnuRadioPayload
    Pruefe-Payload
    Baue-AppExe
    Baue-Installer

    $hash = (Get-FileHash -Path $InstallerDatei -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -Path $PruefsummenDatei -Value "$hash  TETRA-Decode-Windows-Setup.exe" -Encoding ascii
    Schreibe-Schritt "Installer fertig: $InstallerDatei"
    Schreibe-Schritt "SHA256: $hash"
} finally {
    Pop-Location
}

# © 2026 Erik Schauer, do1ffe@darc.de
