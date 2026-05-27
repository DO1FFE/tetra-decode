[CmdletBinding()]
param(
    [switch] $RequireBundledGnuRadio
)

$ErrorActionPreference = 'Continue'
$InstallRoot = Join-Path ${env:ProgramData} 'tetra-decode'
$BundledGnuRadioRoot = Join-Path $InstallRoot 'gnuradio'

function Write-Step {
    param([string] $Message)
    Write-Host "[gnuradio] $Message"
}

function Join-IfRoot {
    param(
        [string] $Root,
        [string] $Child
    )
    if (-not $Root) { return $null }
    return (Join-Path $Root $Child)
}

function Get-GnuRadioPythonCandidates {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($name in @('python3.exe', 'python.exe')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates.Add($cmd.Source) }
    }

    foreach ($root in @(
        $env:RADIOCONDA_ROOT,
        $env:CONDA_PREFIX,
        (Join-IfRoot $env:USERPROFILE 'radioconda'),
        (Join-IfRoot $env:LOCALAPPDATA 'radioconda'),
        (Join-IfRoot $env:ProgramFiles 'radioconda'),
        (Join-IfRoot ${env:ProgramFiles(x86)} 'radioconda'),
        (Join-IfRoot $env:ProgramData 'radioconda')
    )) {
        if ($root) { $candidates.Add((Join-Path $root 'python.exe')) }
    }

    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData)) {
        if (-not $root -or -not (Test-Path $root)) { continue }
        Get-ChildItem -Path $root -Directory -Filter 'GNU Radio*' -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add((Join-Path $_.FullName 'bin\python.exe')) }
        Get-ChildItem -Path $root -Directory -Filter 'GNURadio*' -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add((Join-Path $_.FullName 'bin\python.exe')) }
    }

    $candidates | Where-Object { $_ -and (Test-Path $_) } | Sort-Object -Unique
}

function Get-GnuRadioPathPrefix {
    param([Parameter(Mandatory)] [string] $Python)
    $root = Split-Path -Parent $Python
    $paths = @(
        $root,
        (Join-Path $root 'Library\bin'),
        (Join-Path $root 'Scripts'),
        (Join-Path $root 'bin')
    )
    if ((Split-Path -Leaf $root).ToLowerInvariant() -eq 'bin') {
        $parent = Split-Path -Parent $root
        $paths += @(
            $parent,
            (Join-Path $parent 'Library\bin'),
            (Join-Path $parent 'Scripts')
        )
    }
    $paths | Where-Object { $_ -and (Test-Path $_) } | Sort-Object -Unique
}

function Test-GnuRadioPython {
    param([string] $Python)
    if (-not $Python -or -not (Test-Path $Python)) { return $false }

    $oldPath = $env:Path
    try {
        $prefix = Get-GnuRadioPathPrefix -Python $Python
        if ($prefix) {
            $env:Path = (($prefix + ($oldPath -split ';')) | Where-Object { $_ } | Select-Object -Unique) -join ';'
        }
        & $Python -c 'import gnuradio' *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $env:Path = $oldPath
    }
}

function Find-GnuRadioPython {
    foreach ($candidate in Get-GnuRadioPythonCandidates) {
        if (Test-GnuRadioPython -Python $candidate) {
            return $candidate
        }
    }
    return $null
}

function Test-InstallerChecksum {
    param([Parameter(Mandatory)] [System.IO.FileInfo] $Installer)

    $checksumPath = "$($Installer.FullName).sha256"
    if (-not (Test-Path $checksumPath)) {
        Write-Step "Keine Prüfsumme für $($Installer.Name) gefunden; überspringe Integritätsprüfung."
        return $true
    }

    try {
        $expected = ((Get-Content -Path $checksumPath -TotalCount 1) -split '\s+')[0].ToLowerInvariant()
        $actual = (Get-FileHash -Path $Installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($expected -ne $actual) {
            Write-Warning "Radioconda-Prüfsumme stimmt nicht. Erwartet: $expected, erhalten: $actual"
            return $false
        }
        Write-Step "Radioconda-Prüfsumme geprüft: $actual"
        return $true
    } catch {
        Write-Warning "Radioconda-Prüfsumme konnte nicht geprüft werden: $_"
        return $false
    }
}

function Install-BundledRadioconda {
    $python = Find-GnuRadioPython
    if ($python) {
        Write-Step "GNU Radio Python gefunden: $python"
        return $true
    }

    if (-not (Test-Path $BundledGnuRadioRoot)) {
        return $false
    }

    $installer = Get-ChildItem -Path $BundledGnuRadioRoot -Filter 'radioconda-*-Windows-x86_64.exe' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $installer) {
        return $false
    }

    if (-not (Test-InstallerChecksum -Installer $installer)) {
        return $false
    }

    $target = Join-Path ${env:ProgramData} 'radioconda'
    Write-Step "Installiere gebündelte Radioconda/GNU-Radio-Version nach $target ..."
    $process = Start-Process -FilePath $installer.FullName -ArgumentList @('/S', "/D=$target") -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        Write-Warning "Gebündelte Radioconda-Installation meldete Exitcode $($process.ExitCode)."
        return $false
    }

    $python = Find-GnuRadioPython
    if ($python) {
        Write-Step "GNU Radio Python installiert: $python"
        return $true
    }

    Write-Warning 'Gebündelte Radioconda-Installation wurde ausgeführt, aber GNU Radio Python wurde nicht erkannt.'
    return $false
}

function Install-GnuRadio {
    $python = Find-GnuRadioPython
    if ($python) {
        Write-Step "GNU Radio Python gefunden: $python"
        return $true
    }

    if (Install-BundledRadioconda) {
        return $true
    }

    if ($RequireBundledGnuRadio) {
        Write-Warning 'Gebündeltes Radioconda/GNU Radio wurde angefordert, ist aber nicht installierbar. Netzwerk-Fallbacks werden übersprungen.'
        return $false
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Step 'Installiere Radioconda/GNU Radio über winget...'
        & winget install --id ryanvolz.radioconda --source winget --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "winget konnte Radioconda/GNU Radio nicht installieren. Exitcode: $LASTEXITCODE"
        }
        $python = Find-GnuRadioPython
        if ($python) {
            Write-Step "GNU Radio Python installiert: $python"
            return $true
        }
    }

    $choco = Get-Command choco -ErrorAction SilentlyContinue
    if ($choco) {
        Write-Step 'Installiere GNU Radio über Chocolatey...'
        & choco install -y gnuradio
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Chocolatey konnte GNU Radio nicht installieren. Exitcode: $LASTEXITCODE"
        }
        $python = Find-GnuRadioPython
        if ($python) {
            Write-Step "GNU Radio Python installiert: $python"
            return $true
        }
    }

    Write-Warning 'GNU Radio Python konnte nicht automatisch installiert oder erkannt werden.'
    return $false
}

if (Install-GnuRadio) {
    exit 0
}
exit 1

# © 2026 Erik Schauer, do1ffe@darc.de
