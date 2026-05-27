; Inno-Setup-Skript für das komplette TETRA-Decode-Windows-Paket.

#define AppName "TETRA Decode"
#ifndef AppVersion
#define AppVersion "1.0.0"
#endif
#define AppPublisher "Erik Schauer"
#define AppExeName "tetra-decode.exe"
#ifexist "dist\tetra-decode.exe"
#define AppExeSource "dist\tetra-decode.exe"
#else
#define AppExeSource "tetra-decode.exe"
#endif

[Setup]
AppId={{C5E7D93E-9C2B-4B47-9A3B-54E7CBEF9B1B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=© 2026 Erik Schauer, do1ffe@darc.de
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist-installer
OutputBaseFilename=TETRA-Decode-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
ChangesEnvironment=yes
CloseApplications=yes
RestartApplications=no
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Windows-Komplettpaket
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoCopyright=© 2026 Erik Schauer, do1ffe@darc.de

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"; Flags: checkedonce

[Files]
Source: "{#AppExeSource}"; DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "third_party\osmo-tetra\*"; DestDir: "{app}\third_party\osmo-tetra"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "installer_payload\rtl-sdr\x64\*"; DestDir: "{commonappdata}\tetra-decode\rtl-sdr\x64"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer_payload\osmocom-tetra\*"; DestDir: "{commonappdata}\tetra-decode\osmocom-tetra"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer_payload\zadig\zadig.exe"; DestDir: "{commonappdata}\tetra-decode\zadig"; Flags: ignoreversion
Source: "installer_payload\gnuradio\*"; DestDir: "{commonappdata}\tetra-decode\gnuradio"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\Zadig (RTL-SDR Treiber)"; Filename: "{commonappdata}\tetra-decode\zadig\zadig.exe"

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{commonappdata}\tetra-decode\rtl-sdr\x64"; Check: NeedsAddPath(ExpandConstant('{commonappdata}\tetra-decode\rtl-sdr\x64')); Flags: preservestringtype
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{commonappdata}\tetra-decode\osmocom-tetra"; Check: NeedsAddPath(ExpandConstant('{commonappdata}\tetra-decode\osmocom-tetra')); Flags: preservestringtype
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{commonappdata}\tetra-decode\zadig"; Check: NeedsAddPath(ExpandConstant('{commonappdata}\tetra-decode\zadig')); Flags: preservestringtype

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function PostInstallParameters(): string;
begin
  Result := '-NoProfile -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\scripts\windows_postinstall.ps1') +
    '" -InstallGnuRadio -RequireBundledGnuRadio';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    WizardForm.StatusLabel.Caption := 'Gebündelte Laufzeitkomponenten werden eingerichtet...';
    if not Exec('powershell.exe', PostInstallParameters(), '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
      RaiseException('Die Windows-Nachinstallation konnte nicht gestartet werden.');
    end;
    if ResultCode <> 0 then begin
      RaiseException('Die Windows-Nachinstallation wurde mit Fehlern beendet. Details stehen in %ProgramData%\tetra-decode\windows-postinstall.log.');
    end;
  end;
end;

function NeedsAddPath(Path: string): Boolean;
var
  CurrentPath: string;
begin
  if not RegQueryStringValue(
    HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path',
    CurrentPath
  ) then begin
    CurrentPath := '';
  end;

  Result := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(CurrentPath) + ';') = 0;
end;

; © 2026 Erik Schauer, do1ffe@darc.de
