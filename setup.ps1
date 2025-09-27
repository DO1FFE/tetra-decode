[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-Administrator {
    $currentUser = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Bitte starte dieses Skript in einer administrativen PowerShell." }
}

function Ensure-Chocolatey {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        return
    }

    Write-Host "Chocolatey nicht gefunden. Installiere Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    $installScript = Invoke-WebRequest -UseBasicParsing "https://community.chocolatey.org/install.ps1"
    Invoke-Expression $installScript.Content
}

function Install-ChocoPackage {
    param(
        [Parameter(Mandatory)] [string] $Name
    )

    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) { return }
    $alreadyInstalled = choco list --local-only --exact $Name | Select-String "^$Name " -Quiet
    if ($alreadyInstalled) {
        return
    }
    choco install -y $Name
}

function Test-ZipFile {
    param([string] $Path)
    try {
        [System.IO.Compression.ZipFile]::OpenRead($Path).Dispose()
        return $true
    } catch {
        return $false
    }
}

function Download-Archive {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string[]] $Urls
    )

    $tempFile = Join-Path ([System.IO.Path]::GetTempPath()) (([System.IO.Path]::GetRandomFileName()) + '.zip')
    foreach ($url in $Urls) {
        try {
            Write-Host "Lade $Name von $url ..."
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tempFile
            if (Test-ZipFile -Path $tempFile) {
                Write-Host "$Name erfolgreich heruntergeladen."
                return $tempFile
            } else {
                Write-Warning "Die heruntergeladene Datei von $url war kein gültiges ZIP-Archiv."
                Remove-Item -ErrorAction SilentlyContinue $tempFile
            }
        } catch {
            Write-Warning "Download von $url fehlgeschlagen: $_"
            Remove-Item -ErrorAction SilentlyContinue $tempFile
        }
    }
    Remove-Item -ErrorAction SilentlyContinue $tempFile
    throw "Konnte $Name nicht herunterladen. Bitte manuell installieren."
}

function Ensure-Directory {
    param([string] $Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Add-ToPath {
    param([string] $Directory)
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if (-not $machinePath) { $machinePath = '' }
    $paths = $machinePath.Split(';') | Where-Object { $_ }
    if ($paths -contains $Directory) { return }
    $newPath = ($paths + $Directory) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'Machine')
    if (-not ($env:Path.Split(';') -contains $Directory)) {
        $env:Path = $env:Path + ';' + $Directory
    }
}

function Install-ToolArchive {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string[]] $Urls,
        [Parameter(Mandatory)] [string] $TargetDirectory,
        [Parameter(Mandatory)] [string[]] $BinaryNames
    )

    $existing = $true
    foreach ($binary in $BinaryNames) {
        if (-not (Get-Command $binary -ErrorAction SilentlyContinue)) {
            $existing = $false
            break
        }
    }
    if ($existing -and (Test-Path $TargetDirectory)) {
        Write-Host "$Name ist bereits installiert."
        Add-ToPath $TargetDirectory
        return
    }

    $archive = Download-Archive -Name $Name -Urls $Urls
    $parent = Split-Path $TargetDirectory -Parent
    Ensure-Directory $parent
    if (Test-Path $TargetDirectory) {
        Remove-Item -Recurse -Force $TargetDirectory
    }

    $tempExtract = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
    Ensure-Directory $tempExtract
    Expand-Archive -Path $archive -DestinationPath $tempExtract -Force

    $payload = Get-ChildItem -Path $tempExtract
    $payloadPath = $tempExtract
    if ($payload.Count -eq 1 -and $payload[0].PSIsContainer) {
        $payloadPath = $payload[0].FullName
    }

    Ensure-Directory $TargetDirectory
    Get-ChildItem -Path $payloadPath | ForEach-Object {
        Move-Item -Path $_.FullName -Destination $TargetDirectory -Force
    }

    Remove-Item -Recurse -Force $tempExtract
    Remove-Item $archive -Force

    $binaryDirectories = @()
    foreach ($binary in $BinaryNames) {
        $resolved = Get-ChildItem -Path $TargetDirectory -Filter $binary -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $resolved) {
            throw "$Name wurde entpackt, aber $binary konnte nicht gefunden werden."
        }
        $binaryDirectories += $resolved.DirectoryName
    }

    $binaryDirectories | Sort-Object -Unique | ForEach-Object { Add-ToPath $_ }
}

function Install-PythonRequirements {
    param([string] $ProjectRoot)
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python 3 wurde nicht gefunden. Bitte installiere Python 3 und starte das Skript erneut."
    }
    python -m pip install --upgrade pip
    python -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
}

Assert-Administrator

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installRoot = Join-Path ${env:ProgramData} 'tetra-decode'
Ensure-Directory $installRoot

Ensure-Chocolatey
Install-ChocoPackage -Name zadig
Install-ChocoPackage -Name sox

$toolTargets = @(
    @{ Name = 'RTL-SDR Werkzeuge';
       Urls = @(
           'https://downloads.osmocom.org/binaries/windows/rtl-sdr/rtl-sdr-release.zip',
           'https://github.com/librtlsdr/rtl-sdr/releases/latest/download/rtl-sdr-win64.zip'
       );
       Target = Join-Path $installRoot 'rtl-sdr';
       Binaries = @('rtl_fm.exe','rtl_power.exe','rtl_test.exe') },
    @{ Name = 'osmocom-tetra Werkzeuge';
       Urls = @(
           'https://www.osmocom.org/attachments/download/3446/osmo-tetra-win64-20200512.zip',
           'https://gitlab.com/varosi/osmo-tetra-win64/-/raw/master/osmo-tetra-win64.zip?inline=false'
       );
       Target = Join-Path $installRoot 'osmocom-tetra';
       Binaries = @('receiver1.exe','tetra-rx.exe','demod_float.exe') }
)

foreach ($tool in $toolTargets) {
    try {
        Install-ToolArchive -Name $tool.Name -Urls $tool.Urls -TargetDirectory $tool.Target -BinaryNames $tool.Binaries
    } catch {
        Write-Warning $_
    }
}

Install-PythonRequirements -ProjectRoot $projectRoot

Write-Host "Setup abgeschlossen. Stelle sicher, dass du die PowerShell neu startest, damit PATH-Änderungen aktiv werden."
