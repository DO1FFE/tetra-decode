; Inno Setup script for the complete TETRA Decode Windows package.

#define AppName "TETRA Decode"
#define AppVersion "1.0.0"
#define AppPublisher "TETRA Decode"
#define AppExeName "tetra-decode.exe"

[Setup]
AppId={{C5E7D93E-9C2B-4B47-9A3B-54E7CBEF9B1B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
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

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknuepfung erstellen"; GroupDescription: "Zusaetzliche Symbole:"; Flags: unchecked
Name: "postinstalltools"; Description: "Zusatzkomponenten einrichten (RTL-SDR, Zadig, Osmocom-TETRA)"; GroupDescription: "Installation:"; Flags: checkedonce

[Files]
Source: "{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "third_party\osmo-tetra\*"; DestDir: "{app}\third_party\osmo-tetra"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer_payload\rtl-sdr\x64\*"; DestDir: "{commonappdata}\tetra-decode\rtl-sdr\x64"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer_payload\osmocom-tetra\*"; DestDir: "{commonappdata}\tetra-decode\osmocom-tetra"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer_payload\zadig\zadig.exe"; DestDir: "{commonappdata}\tetra-decode\zadig"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\Zadig (RTL-SDR Treiber)"; Filename: "{commonappdata}\tetra-decode\zadig\zadig.exe"

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{commonappdata}\tetra-decode\rtl-sdr\x64"; Check: NeedsAddPath(ExpandConstant('{commonappdata}\tetra-decode\rtl-sdr\x64')); Flags: preservestringtype
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{commonappdata}\tetra-decode\osmocom-tetra"; Check: NeedsAddPath(ExpandConstant('{commonappdata}\tetra-decode\osmocom-tetra')); Flags: preservestringtype
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{commonappdata}\tetra-decode\zadig"; Check: NeedsAddPath(ExpandConstant('{commonappdata}\tetra-decode\zadig')); Flags: preservestringtype

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows_postinstall.ps1"""; StatusMsg: "Zusatzkomponenten werden eingerichtet..."; Flags: runhidden waituntilterminated; Tasks: postinstalltools
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
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
