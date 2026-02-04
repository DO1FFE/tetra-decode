[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-Administrator {
    $currentUser = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Bitte starte dieses Skript in einer administrativen PowerShell."
    }
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
    if ($LASTEXITCODE -ne 0) {
        throw "Chocolatey konnte das Paket '$Name' nicht installieren."
    }
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
        [Parameter(Mandatory)] [string[]] $Urls,
        [hashtable] $Checksums,
        [string[]] $ManualSteps
    )

    $tempFile = Join-Path ([System.IO.Path]::GetTempPath()) (([System.IO.Path]::GetRandomFileName()) + '.zip')
    $fehler = @()
    foreach ($url in $Urls) {
        try {
            Write-Host "Lade $Name von $url ..."
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tempFile
            if ($Checksums -and $Checksums.ContainsKey($url)) {
                $expected = $Checksums[$url]
                $actual = (Get-FileHash -Path $tempFile -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($actual -ne $expected.ToLowerInvariant()) {
                    Write-Warning "Pruefsumme fuer $url stimmt nicht. Erwartet: $expected, erhalten: $actual."
                    $fehler += "Pruefsumme passt nicht fuer $url."
                    Remove-Item -ErrorAction SilentlyContinue $tempFile
                    continue
                }
            }
            if (Test-ZipFile -Path $tempFile) {
                Write-Host "$Name erfolgreich heruntergeladen."
                return $tempFile
            } else {
                Write-Warning "Die heruntergeladene Datei von $url war kein gueltiges ZIP-Archiv."
                $fehler += "Defektes ZIP von $url."
                Remove-Item -ErrorAction SilentlyContinue $tempFile
            }
        } catch {
            Write-Warning "Download von $url fehlgeschlagen: $_"
            $fehler += "Download fehlgeschlagen von $url."
            Remove-Item -ErrorAction SilentlyContinue $tempFile
        }
    }
    Remove-Item -ErrorAction SilentlyContinue $tempFile
    $manualText = ''
    if ($ManualSteps) {
        $manualText = "Manuelle Schritte:" + [Environment]::NewLine + (($ManualSteps | ForEach-Object { "  - $_" }) -join [Environment]::NewLine)
    }
    $detailText = ''
    if ($fehler.Count -gt 0) {
        $detailText = "Details:" + [Environment]::NewLine + (($fehler | ForEach-Object { "  - $_" }) -join [Environment]::NewLine)
    }
    $message = @(
        "Konnte $Name nicht herunterladen oder das ZIP ist defekt."
        $manualText
        $detailText
    ) | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.TrimEnd() }
    throw ($message -join [Environment]::NewLine)
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
        [Parameter(Mandatory)] [string[]] $BinaryNames,
        [hashtable] $Checksums,
        [string[]] $ManualSteps
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

    $archive = Download-Archive -Name $Name -Urls $Urls -Checksums $Checksums -ManualSteps $ManualSteps
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
            $manualText = ''
            if ($ManualSteps) {
                $manualText = [Environment]::NewLine + "Manuelle Schritte:" + [Environment]::NewLine + (($ManualSteps | ForEach-Object { "  - $_" }) -join [Environment]::NewLine)
            }
            throw "$Name wurde entpackt, aber $binary konnte nicht gefunden werden.$manualText"
        }
        $binaryDirectories += $resolved.DirectoryName
    }

    $binaryDirectories | Sort-Object -Unique | ForEach-Object { Add-ToPath $_ }
}

function Install-PythonRequirements {
    param([string] $ProjectRoot)
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Warning "Python 3 wurde nicht gefunden. Ueberspringe Python-Abhaengigkeiten."
        return
    }
    python -m pip install --upgrade pip
    python -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
}

function Ensure-PythonAndPip {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "Python nicht gefunden. Installiere Python ueber Chocolatey..."
        Ensure-Chocolatey
        Install-ChocoPackage -Name python
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Warning "Python konnte nicht installiert werden. Ueberspringe Python-Abhaengigkeiten."
        return
    }
    $pipAvailable = $true
    try {
        python -m pip --version | Out-Null
    } catch {
        $pipAvailable = $false
    }
    if (-not $pipAvailable) {
        Write-Host "pip nicht gefunden. Installiere pip ueber ensurepip..."
        python -m ensurepip --upgrade
    }
}

Assert-Administrator

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installRoot = Join-Path ${env:ProgramData} 'tetra-decode'
Ensure-Directory $installRoot

Ensure-Chocolatey
Install-ChocoPackage -Name zadig
try {
    Install-ChocoPackage -Name sox.portable
} catch {
    Write-Warning "SoX konnte nicht automatisch installiert werden. Bitte installiere es manuell (z. B. 'choco install sox.portable')."
}

$toolTargets = @(
    @{ Name = 'RTL-SDR Werkzeuge';
       Urls = @(
           'https://github.com/rtlsdrblog/rtl-sdr-blog/releases/download/v1.3.6/Release.zip',
           'https://github.com/rtlsdrblog/rtl-sdr-blog/releases/download/1.3.5/Release.zip',
           'https://ftp.osmocom.org/binaries/windows/rtl-sdr/rtl-sdr-64bit-20190526.zip'
       );
       Target = Join-Path $installRoot 'rtl-sdr';
       Binaries = @('rtl_fm.exe','rtl_power.exe','rtl_test.exe') },
    @{ Name = 'osmocom-tetra Werkzeuge';
       Urls = @(
           'https://osmocom.org/attachments/download/3446/osmo-tetra-win64-20200512.zip',
           'https://archive.org/download/osmo-tetra-win64-20200512/osmo-tetra-win64-20200512.zip',
           'https://downloads.osmocom.org/attachments/download/3446/osmo-tetra-win64-20200512.zip'
       );
       ManualSteps = @(
           'Lade das Windows-Binary-Archiv von der OsmocomTETRA-Wiki-Seite: https://osmocom.org/projects/tetra/wiki/OsmocomTETRA',
           'Entpacke das Archiv nach ' + (Join-Path $installRoot 'osmocom-tetra') + ' und stelle sicher, dass die Tools (receiver1.exe, tetra-rx.exe, demod_float.exe) enthalten sind.',
           'Stelle sicher, dass das Zielverzeichnis im PATH liegt.'
       );
       Target = Join-Path $installRoot 'osmocom-tetra';
       Binaries = @('receiver1.exe','tetra-rx.exe','demod_float.exe') }
)

foreach ($tool in $toolTargets) {
    try {
        Install-ToolArchive -Name $tool.Name -Urls $tool.Urls -TargetDirectory $tool.Target -BinaryNames $tool.Binaries -Checksums $tool.Checksums -ManualSteps $tool.ManualSteps
    } catch {
        Write-Warning $_
    }
}

Ensure-PythonAndPip
Install-PythonRequirements -ProjectRoot $projectRoot

Write-Host "install.ps1 abgeschlossen. Starte die PowerShell neu, damit PATH-Aenderungen aktiv werden."
