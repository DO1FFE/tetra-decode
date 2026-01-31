; Inno Setup Skript für TETRA Decode
; Erstellt einen Windows-Installer basierend auf der PyInstaller-EXE.

#define AppName "TETRA Decode"
#define AppVersion "1.0.0"
#define AppPublisher "TETRA Decode"
#define AppExeName "sdr_gui.exe"

[Setup]
AppId={{C5E7D93E-9C2B-4B47-9A3B-54E7CBEF9B1B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist-installer
OutputBaseFilename=TETRA-Decode-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\\German.isl"

[Files]
Source: "dist\\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"
Name: "{autodesktop}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"; Flags: unchecked

[Run]
Filename: "{app}\\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
