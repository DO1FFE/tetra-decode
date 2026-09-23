# TETRA Decode

[Deutsche Dokumentation](README.md)

This German/English edition is an **alpha version**.

TETRA Decode is a Python/PyQt5 application for SDR frequency scans and TETRA
monitoring. It provides a spectrum display, decoder output, cell information,
talkgroup selection, packet statistics, scheduled scans and audio controls.
Reception depends on the connected SDR, its driver, the available signal and
the external decoder components.

## Select English

Open **Einstellungen → Sprache** and select **English**. In English, these
controls are labelled **Settings → Language**. The application saves your
selection in `~/.tetra_gui_config.json` (`%USERPROFILE%\.tetra_gui_config.json`
on Windows).

Without a saved choice, the interface uses German on a system with German as
its language and English on other systems. You can also choose the language
when starting the application:

```powershell
.\tetra-decode.exe --language en
.\tetra-decode.exe --language de
```

`--sprache` is the German alias for `--language`.

The language support described here is part of the current source code and
new packages built from it. Older executables do not gain English support
until they are replaced with a new build. External decoder output and helper
installation scripts may still use their original language.

## Windows package

The alpha Inno Setup package is named `TETRA-Decode-Windows-Alpha-DE-EN-Setup.exe`. Select
**English** in its language dialog, then follow the installation steps. The
desktop shortcut is optional. The installer language and the application's
saved language are separate settings.

The complete package includes the application, RTL-SDR tools, Zadig,
Osmocom-TETRA components, GNU Radio/Radioconda and the WSL audio backend.
Installation requires administrator rights. The portable `tetra-decode.exe`
contains the Python GUI dependencies but requires the external SDR and
decoder tools separately.

Connect your receiver and make sure its driver is configured before starting
a scan. In **Settings**, select the receiver and check its tuning settings.
Then use the scan and decoder controls for your intended frequency range.
TETRA voice playback requires the audio backend, usable WSL on Windows and
an unencrypted voice channel. An English interface does not change decoder
or hardware support.

If the installer reports a post-installation error, consult
`%ProgramData%\tetra-decode\windows-postinstall.log`.

## Run from source

Install Python and the packages listed in `requirements.txt` in a virtual
environment. For example, in Windows PowerShell from the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe sdr_gui.py --language en
```

The RTL-SDR and Osmocom-TETRA tools are separate from the Python packages.
The native Windows demodulation pipeline also uses GNU Radio. For source
builds of Osmocom-TETRA, initialize the submodule first:

```powershell
git submodule update --init --recursive
```

`setup.ps1` and `install.ps1` are developer/fallback installation helpers.
On Linux, `setup.sh` and `install.sh` provide dependency setup. Review the
[German setup notes](README.md#einrichtung) for platform-specific details.

## Build the Windows installer

Use `scripts/build_windows_installer.ps1` to prepare the payload and build a
new executable and Inno Setup package. The complete build instructions and
component list are in [WINDOWS_INSTALLER.md](WINDOWS_INSTALLER.md).

---

© 2026 Erik Schauer, do1ffe@darc.de
