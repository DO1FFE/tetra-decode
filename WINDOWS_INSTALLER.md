# Windows-Installationspaket

Diese deutsch-englische Fassung ist eine **Alpha-Version**.

Das Windows-Komplettpaket wird mit Inno Setup gebaut. Das deutsch-englische Alpha-Paket wird als `dist-installer/TETRA-Decode-Windows-Alpha-DE-EN-Setup.exe` bereitgestellt.

## Sprache

Der Inno-Setup-Installer bietet beim Start **Deutsch** und **English** an.
Auch die Desktop-Verknüpfungsoption und die eigenen Fehlermeldungen des
Installers werden in der gewählten Sprache angezeigt. Die englische
[Benutzerdokumentation](README.en.md) wird mit installiert.

Die Anwendung hat eine eigene Sprachwahl unter **Einstellungen → Sprache**
beziehungsweise **Settings → Language**. Sie speichert die Auswahl;
ohne gespeicherte Auswahl entscheidet die Systemsprache (Deutsch bei
deutscher Systemsprache, sonst Englisch). Für einen englischen Start ist
auch `tetra-decode.exe --language en` möglich. Die Installer-Sprachauswahl
überschreibt die Anwendungseinstellung nicht. Externe Programme und die
Protokolle der vorhandenen PowerShell-Hilfsskripte werden nicht übersetzt.

Die Sprachänderung setzt einen Neubau der EXE und des Installers voraus.
Die folgende Beschreibung des alternativen NSIS-Installers betrifft einen
separaten Buildweg; dessen Installationsoberfläche wird dadurch nicht
übersetzt.

## Enthaltene Komponenten

- `tetra-decode.exe`: per PyInstaller gebaute GUI mit den Python-Abhängigkeiten aus `requirements.txt`.
- RTL-SDR-Werkzeuge: `rtl_sdr.exe`, `rtl_fm.exe`, `rtl_power.exe`, `rtl_test.exe` und benötigte Laufzeitbibliotheken.
- Osmocom-TETRA: `tetra-rx.exe`, `float_to_bits.exe`, MSYS2-Laufzeitbibliotheken und das offizielle `simdemod3.py` aus `third_party/osmo-tetra`.
- TETRA-Audio-Backend: vorgebaute x86_64-Linux-Werkzeuge für WSL, audiofähiges `tetra-rx`, `cdecoder`, `sdecoder`, `tetra-audio-backend` und benötigte Linux-Bibliotheken.
- Zadig: Treiberwerkzeug für WinUSB/libusb-Geräte.
- GNU Radio/Radioconda: wird als großer Installer-Payload eingebettet und während der Installation lokal installiert. Dadurch ist kein winget-, Chocolatey- oder Internet-Zugriff auf dem Zielsystem nötig.

## Build auf Windows

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
git submodule update --init --recursive
.\scripts\build_windows_installer.ps1
```

Das Skript lädt Radioconda/GNU Radio automatisch in `installer_payload\gnuradio`, prüft vor dem Build die gesamte Nutzlast, baut `dist\tetra-decode.exe`, ruft den Inno-Setup-Compiler auf und schreibt zusätzlich `dist-installer\TETRA-Decode-Windows-Alpha-DE-EN-Setup.exe.sha256`.

Für einen Release-Build kannst du das Paket lokal oder auf einem Windows-Builder mit `.\scripts\build_windows_installer.ps1` erzeugen und den Installer anschließend als GitHub-Release-Artefakt hochladen.

## Offline-Installer lokal unter Linux bauen

Falls kein Windows/Inno-Setup-Compiler verfügbar ist, kann ein vollständiger NSIS-Offline-Installer auch unter Linux gebaut werden:

```bash
sudo apt-get install nsis
./scripts/build_wsl_audio_payload.sh
./scripts/build_windows_offline_nsis.sh
```

Das Ergebnis liegt unter `dist-installer/TETRA-Decode-Windows-Offline-Setup.exe` und enthält die App, RTL-SDR, Zadig, Osmocom-TETRA, Radioconda/GNU Radio und das vollständige WSL-Live-Audio-Backend ohne nachträglichen Codec-Download.

Im Installer gibt es eine Komponenten-Seite. `Desktop-Verknüpfung erstellen`
ist dort standardmäßig aktiviert und kann bei Bedarf abgewählt werden.

---

© 2026 Erik Schauer, do1ffe@darc.de
