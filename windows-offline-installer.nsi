Unicode true
ManifestSupportedOS all
RequestExecutionLevel admin
SetCompressor zlib
ShowInstDetails show
ShowUninstDetails show

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!define APPNAME "TETRA Decode"
!define APPVERSION "1.0.0"
!define APPEXE "tetra-decode.exe"
!define PUBLISHER "Erik Schauer"

Name "${APPNAME}"
OutFile "dist-installer\TETRA-Decode-Windows-Offline-Setup.exe"
InstallDir "$PROGRAMFILES64\${APPNAME}"
InstallDirRegKey HKLM "Software\${APPNAME}" "InstallDir"

VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=1031 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1031 "CompanyName" "${PUBLISHER}"
VIAddVersionKey /LANG=1031 "FileDescription" "${APPNAME} Offline-Windows-Installer"
VIAddVersionKey /LANG=1031 "FileVersion" "${APPVERSION}"
VIAddVersionKey /LANG=1031 "ProductVersion" "${APPVERSION}"
VIAddVersionKey /LANG=1031 "LegalCopyright" "© 2026 Erik Schauer, do1ffe@darc.de"

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "German"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Dieses Installationspaket benötigt ein 64-Bit-Windows."
    Abort
  ${EndIf}
FunctionEnd

Section "TETRA Decode installieren" SEC_APP
  SectionIn RO
  SetShellVarContext all
  SetOverwrite on
  ReadEnvStr $R9 "ProgramData"
  ${If} $R9 == ""
    MessageBox MB_ICONSTOP "Die Windows-Umgebungsvariable ProgramData wurde nicht gefunden."
    Abort
  ${EndIf}

  CreateDirectory "$INSTDIR"
  SetOutPath "$INSTDIR"
  File /oname=${APPEXE} "${APPEXE}"
  File "README.md"
  File "requirements.txt"
  File "setup.ps1"
  File "install.ps1"

  SetOutPath "$INSTDIR\scripts"
  File /r "scripts\*"

  SetOutPath "$INSTDIR\third_party\osmo-tetra"
  File /r /x ".git" "third_party\osmo-tetra\*"

  SetOutPath "$R9\tetra-decode\rtl-sdr\x64"
  File /r "installer_payload\rtl-sdr\x64\*"

  SetOutPath "$R9\tetra-decode\osmocom-tetra"
  File /r "installer_payload\osmocom-tetra\*"

  SetOutPath "$R9\tetra-decode\zadig"
  File "installer_payload\zadig\zadig.exe"

  SetOutPath "$R9\tetra-decode\gnuradio"
  File /r "installer_payload\gnuradio\*"

  WriteRegStr HKLM "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${APPEXE}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Zadig (RTL-SDR Treiber).lnk" "$R9\tetra-decode\zadig\zadig.exe"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Deinstallieren.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

Section "Desktop-Verknüpfung erstellen" SEC_DESKTOP
  SetShellVarContext current
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPEXE}"
  SetShellVarContext all
SectionEnd

Section "-Laufzeitkomponenten einrichten" SEC_POSTINSTALL
  SetShellVarContext all
  DetailPrint "Richte gebündelte Laufzeitkomponenten ein..."
  ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\windows_postinstall.ps1" -InstallGnuRadio -RequireBundledGnuRadio' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Die Nachinstallation der gebündelten Laufzeitkomponenten ist fehlgeschlagen. Details stehen in %ProgramData%\tetra-decode\windows-postinstall.log."
    Abort
  ${EndIf}
SectionEnd

Section "Deinstallieren"
  SetShellVarContext all
  ReadEnvStr $R9 "ProgramData"

  SetShellVarContext current
  Delete "$DESKTOP\${APPNAME}.lnk"
  SetShellVarContext all
  Delete "$DESKTOP\${APPNAME}.lnk"

  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Zadig (RTL-SDR Treiber).lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Deinstallieren.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"

  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$INSTDIR"

  ${If} $R9 != ""
    RMDir /r "$R9\tetra-decode\rtl-sdr"
    RMDir /r "$R9\tetra-decode\osmocom-tetra"
    RMDir /r "$R9\tetra-decode\zadig"
    RMDir /r "$R9\tetra-decode\gnuradio"
    RMDir "$R9\tetra-decode"
  ${EndIf}

  DeleteRegKey HKLM "Software\${APPNAME}"
SectionEnd

; © 2026 Erik Schauer, do1ffe@darc.de
