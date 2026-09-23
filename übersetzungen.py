"""Deutsche und englische Texte sowie die Sprachwahl für Tetra Decode."""

import argparse
from datetime import date
import locale
import re
import string
import sys


ENGLISCHE_TEXTE = {
    "SDR-Scanner": "SDR Scanner",
    "Starten": "Start",
    "Stopp": "Stop",
    "Stoppe": "Stopping",
    "Frequenz: k. A.": "Frequency: n/a",
    "Frequenz: {wert0:.3f} MHz": "Frequency: {wert0:.3f} MHz",
    "Frequenz [Hz]": "Frequency [Hz]",
    "Leistung [dB]": "Power [dB]",
    "Frequenz (MHz)": "Frequency (MHz)",
    "Leistung (dB)": "Power (dB)",
    "Spektrum": "Spectrum",
    "Spektrum als PNG speichern": "Save spectrum as PNG",
    "Modus: Automatisch": "Mode: Automatic",
    "Modus: {wert0}": "Mode: {wert0}",
    "Manuell": "Manual",
    "Automatisch": "Automatic",
    "Letzte Frequenzen:": "Recent frequencies:",
    "Aktivität:": "Activity:",
    "Dekodiertes Audio wiedergeben": "Play decoded audio",
    "als WAV speichern": "Save as WAV",
    "Neu suchen": "Refresh",
    "Gerät:": "Device:",
    "Frequenzbereich:": "Frequency range:",
    "AGC-Level:": "AGC level:",
    "Hell": "Light",
    "Dunkel": "Dark",
    "Design:": "Theme:",
    "Sprache:": "Language:",
    "Sprache sofort ändern; laufende Scans und Dekodierungen bleiben erhalten.": "Change language immediately; running scans and decoding continue.",
    "Scheduler aktiv": "Enable scheduler",
    "Intervall (min):": "Interval (min):",
    "Scheduler:": "Scheduler:",
    "Telegram Token:": "Telegram token:",
    "Chat-ID:": "Chat ID:",
    "Dekodierung starten": "Start decoding",
    "Automatisch nach Scan": "Automatically after scan",
    "Regex-Filter": "Regex filter",
    "Zell-ID": "Cell ID",
    "Frequenz": "Frequency",
    "CSV-Export": "Export CSV",
    "Auswahl": "Selection",
    "Treffer": "Hits",
    "Letzte Aktivität": "Last activity",
    "Alle auswählen": "Select all",
    "Alle abwählen": "Deselect all",
    "Spektrum & Steuerung": "Spectrum & Control",
    "Audio & Aktivität": "Audio & Activity",
    "Einstellungen": "Settings",
    "TETRA-Dekodierung": "TETRA Decoding",
    "Zellen": "Cells",
    "Statistik": "Statistics",
    "Sprechgruppen": "Talkgroups",
    "Pakettyp": "Packet type",
    "Anzahl": "Count",
    "Verschlüsseltes Signal erkannt": "Encrypted signal detected",
    "CSV speichern": "Save CSV",
    "CSV-Dateien (*.csv)": "CSV files (*.csv)",
    "Starte automatische Prüfung der Zusatzprogramme...": "Checking additional programs automatically...",
    "Fehlende Programme: ": "Missing programs: ",
    "Fehlende Python-Module: ": "Missing Python modules: ",
    "Fehlende Zusatzwerkzeuge: ": "Missing additional tools: ",
    "Setup abgeschlossen": "Setup completed",
    "Alle benötigten Zusatzprogramme wurden bereits gefunden.": "All required additional programs were found.",
    "Installiere {wert0} über apt ({wert1})": "Installing {wert0} using apt ({wert1})",
    "Installiere {wert0} über choco ({wert1})": "Installing {wert0} using choco ({wert1})",
    "{wert0} fehlt - bitte {wert1} manuell installieren": "{wert0} is missing - please install {wert1} manually",
    "Installiere Python-Modul {wert0}": "Installing Python module {wert0}",
    "Installiere Zadig über choco": "Installing Zadig using choco",
    "Konnte {wert0} nicht ausführen: {wert1}": "Could not run {wert0}: {wert1}",
    "Starte install.sh, um fehlende Abhängigkeiten zu installieren...": "Running install.sh to install missing dependencies...",
    "Starte install.ps1, um fehlende Abhängigkeiten zu installieren...": "Running install.ps1 to install missing dependencies...",
    "Audioausgabe aktiviert ({wert0}), Pfad: {wert1}": "Audio output enabled ({wert0}), path: {wert1}",
    "{wert0} nicht im PATH gefunden": "{wert0} was not found in PATH",
    "Decoder konnte nicht gestartet werden: {wert0}": "Could not start decoder: {wert0}",
    "Automatische Frequenz ignoriert (Manuell aktiv): {wert0:.3f} MHz": "Automatic frequency ignored (manual mode active): {wert0:.3f} MHz",
    "Manuell ausgewählt: {wert0:.3f} MHz": "Manually selected: {wert0:.3f} MHz",
    "Gewählte Frequenz: {wert0:.3f} MHz": "Selected frequency: {wert0:.3f} MHz",
    "Modus gewechselt: {wert0}": "Mode changed: {wert0}",
    "ohne Index": "no index",
    "Dekodierung gestartet mit Gerät {wert0} ({wert1}) bei {wert2:.3f} MHz": "Decoding started with device {wert0} ({wert1}) at {wert2:.3f} MHz",
    "Scan gestartet mit Gerät {wert0} ({wert1}) ({wert2:.0f}-{wert3:.0f} MHz)": "Scan started with device {wert0} ({wert1}) ({wert2:.0f}-{wert3:.0f} MHz)",
    "Spektrum gespeichert: {wert0}": "Spectrum saved: {wert0}",
    "TETRA-Aktivität auf {wert0:.4f} MHz: {wert1} empfangen": "TETRA activity on {wert0:.4f} MHz: received {wert1}",
    "Der Frequenzbereich muss zwei positive Werte in MHz (Start < Ende) enthalten.": "The frequency range must contain two positive values in MHz (start < end).",
    "Starte das Programm im Kommandozeilenmodus.": "Starting the program in command-line mode.",
    "\n=== TETRA-Decoder (CLI-Modus) ===": "\n=== TETRA Decoder (CLI mode) ===",
    "Hinweis: Für die grafische Oberfläche müssen X11/Qt-xcb verfügbar sein.": "Note: X11/Qt-xcb must be available for the graphical interface.",
    "\nGefundene SDR-Geräte:": "\nDetected SDR devices:",
    "\nBeende den CLI-Modus mit Strg+C.": "\nPress Ctrl+C to exit CLI mode.",
    "TETRA-Decoder im CLI-Modus": "TETRA decoder in CLI mode",
    "Name des SDR-Geräts (wie in der Geräte-Liste angezeigt).": "Name of the SDR device (as shown in the device list).",
    "Index des SDR-Geräts (z. B. 0).": "Index of the SDR device (e.g. 0).",
    "PPM-Korrektur für den SDR-Empfänger.": "PPM correction for the SDR receiver.",
    "Frequenzbereich in MHz (z. B. 380 430).": "Frequency range in MHz (e.g. 380 430).",
    "Regex-Filter für die Ausgabe im CLI-Modus.": "Regex filter for output in CLI mode.",
    "Sprechgruppen-ID für die Anzeige (mehrfach nutzbar).": "Talkgroup ID to display (can be specified more than once).",
    "Datei mit Sprechgruppen-IDs (eine pro Zeile oder kommagetrennt).": "File containing talkgroup IDs (one per line or comma-separated).",
    "CSV-Export der erkannten Zellen in die angegebene Datei.": "Export detected cells to the specified CSV file.",
    "Gibt beim Beenden eine kurze Statistik aus.": "Print a brief summary of statistics on exit.",
    "Automatische Dekodierung nach der Frequenzauswahl aktivieren.": "Enable automatic decoding after frequency selection.",
    "Automatische Dekodierung deaktivieren.": "Disable automatic decoding.",
    "Dekodiertes Audio wiedergeben.": "Play decoded audio.",
    "Audio-Wiedergabe deaktivieren.": "Disable audio playback.",
    "Dekodiertes Audio als WAV speichern (setzt Audio-Wiedergabe voraus).": "Save decoded audio as WAV (requires audio playback).",
    "Audio-Aufnahme deaktivieren.": "Disable audio recording.",
    "Sprache wählen (de oder en).": "Select language (de or en).",
    "Warnung: Konnte Sprechgruppen-Datei nicht lesen: {wert0}": "Warning: Could not read talkgroup file: {wert0}",
    "Frequenz {wert0:.3f} MHz, Leistung {wert1:.1f} dB": "Frequency {wert0:.3f} MHz, power {wert1:.1f} dB",
    "Frequenz {wert0:.3f} MHz erkannt (Auto-Dekodierung aus).": "Frequency {wert0:.3f} MHz detected (automatic decoding disabled).",
    "Starte Dekoder auf {wert0:.3f} MHz": "Starting decoder on {wert0:.3f} MHz",
    "Talkgroup {wert0} empfangen": "Received talkgroup {wert0}",
    "Dekoder gestoppt.": "Decoder stopped.",
    "Ungültige Eingabe: {wert0}": "Invalid input: {wert0}",
    "Bitte eine Frequenz in MHz angeben: freq <MHz>": "Please enter a frequency in MHz: freq <MHz>",
    "Ungültige Frequenz. Beispiel: freq 395.625": "Invalid frequency. Example: freq 395.625",
    "Bitte Verzeichnis nach --png-dir angeben.": "Please specify a directory after --png-dir.",
    "Unbekannter Befehl. Verfügbar: lock, unlock, freq <MHz>, save-png [--png-dir <Pfad>]": "Unknown command. Available: lock, unlock, freq <MHz>, save-png [--png-dir <path>]",
    "Kein Spektrum zum Speichern vorhanden.": "No spectrum available to save.",
    "Konnte CSV nicht schreiben: {wert0}": "Could not write CSV: {wert0}",
    "CSV-Export abgeschlossen: {wert0}": "CSV export completed: {wert0}",
    "\nStatistik (CLI):": "\nStatistics (CLI):",
    "- Zellen erkannt: {wert0}": "- Cells detected: {wert0}",
    "- Pakettypen: {wert0}": "- Packet types: {wert0}",
    "- Pakettypen: keine": "- Packet types: none",
    "- Sprechgruppen: {wert0}": "- Talkgroups: {wert0}",
    "- Sprechgruppen: keine": "- Talkgroups: none",
    "an": "on",
    "aus": "off",
    ", Aufnahme an": ", recording on",
    "CLI-Start mit Gerät {wert0} ({wert1}), PPM {wert2}, Frequenzbereich {wert3:.1f}-{wert4:.1f} MHz, Auto-Dekodierung {wert5}, Audio {wert6}": "CLI started with device {wert0} ({wert1}), PPM {wert2}, frequency range {wert3:.1f}-{wert4:.1f} MHz, automatic decoding {wert5}, audio {wert6}",
    "\nCLI-Modus beendet.": "\nCLI mode ended.",
    "Fehlendes Python-Modul 'numpy'. Bitte installiere es, z. B. mit 'python3 -m pip install numpy'.": "Missing Python module 'numpy'. Please install it, for example with 'python3 -m pip install numpy'.",
    "Fehlendes Python-Modul 'numpy' und 'pip' ist nicht verfügbar. Installiere zuerst pip (z. B. 'python3 -m ensurepip --upgrade' oder 'sudo apt-get install python3-pip') und danach 'python3 -m pip install numpy'.": "Missing Python module 'numpy', and 'pip' is unavailable. First install pip (e.g. 'python3 -m ensurepip --upgrade' or 'sudo apt-get install python3-pip'), then run 'python3 -m pip install numpy'.",
    "Fehlende Systembibliothek 'libGL.so.1'. Bitte installiere 'libgl1' (z. B. 'sudo apt-get install libgl1') und starte das Programm erneut.": "Missing system library 'libGL.so.1'. Please install 'libgl1' (e.g. 'sudo apt-get install libgl1') and restart the program.",
    "Qt-Plugin 'xcb' nicht gefunden. Bitte installiere die fehlenden System-Pakete für X11/Qt-xcb (z. B. libxcb, libxkbcommon-x11) oder starte das Programm in einer Umgebung mit grafischer Oberfläche. Alternativ kannst du 'QT_QPA_PLATFORM=offscreen' setzen, wenn eine headless Ausführung gewünscht ist.": "Qt plugin 'xcb' not found. Please install the missing X11/Qt-xcb system packages (e.g. libxcb, libxkbcommon-x11), or run the program in a graphical environment. Alternatively, set 'QT_QPA_PLATFORM=offscreen' for headless execution.",
    "Qt konnte nicht gestartet werden. Bitte prüfe, ob die X11/Qt-xcb System-Pakete installiert sind oder ob du dich in einer headless Umgebung befindest. Fehlerdetails: {wert0}": "Could not start Qt. Please check whether the X11/Qt-xcb system packages are installed or whether this is a headless environment. Error details: {wert0}",
}

ENGLISCHE_TEXTE.update({
    "TETRA Decode - SDR-Scanner": "TETRA Decode - SDR Scanner",
    "TETRA Decode Alpha - SDR-Scanner": "TETRA Decode Alpha - SDR Scanner",
    "RTL-SDR TETRA-Suche, Sprechgruppen und Live-Audio": "RTL-SDR TETRA search, talkgroups and live audio",
    "Alle Bereiche": "All ranges",
    "380-385 MHz (BOS Unterband)": "380-385 MHz (public safety uplink)",
    "390-395 MHz (BOS Oberband/Basis)": "390-395 MHz (public safety downlink/base)",
    "406,1-410 MHz (BOS DMO)": "406.1-410 MHz (public safety DMO)",
    "410-420 MHz (Bündelfunk Unterband)": "410-420 MHz (trunked radio uplink)",
    "420-430 MHz (Bündelfunk Oberband/Basis)": "420-430 MHz (trunked radio downlink/base)",
    "430-440 MHz (Amateurfunk 70 cm)": "430-440 MHz (amateur radio 70 cm)",
    "440-443 MHz (Bündelfunk Unterband)": "440-443 MHz (trunked radio uplink)",
    "445-448 MHz (Bündelfunk Oberband/Basis)": "445-448 MHz (trunked radio downlink/base)",
    "SDR-Gerät": "SDR device", "wird geprüft": "checking", "Kalibrierung": "Calibration",
    "bereit": "ready", "PPM und RF-Gain": "PPM and RF gain", "Überwachung": "Monitoring",
    "gestoppt": "stopped", "alle aktivierten Bereiche": "all enabled ranges",
    "0 bestätigt": "0 confirmed", "keine aktive Frequenz": "no active frequency",
    "wartet": "waiting", "Modus: automatisch": "Mode: automatic", "keine Aktivität": "no activity",
    "Überwachung starten": "Start monitoring", "Überwachung stoppen": "Stop monitoring",
    "Kalibrieren": "Calibrate", "Einmal suchen": "Search once", "Suche stoppen": "Stop search",
    "Auswahl dekodieren": "Decode selection", "Spektrum starten": "Start spectrum", "Alles stoppen": "Stop all",
    "Pegel": "Level", "Letzte Sichtung": "Last seen", "TETRA-Signale suchen": "Search TETRA signals",
    "Ausgewählte Frequenz dekodieren": "Decode selected frequency", "Bereich:": "Range:",
    "Alle gefundenen Kandidaten prüfen": "Check all detected candidates", "Max. Kandidaten:": "Max. candidates:",
    "Nur ausgewählte anzeigen": "Show selected only", "Auswahl löschen": "Clear selection",
    "TG-ID/Adresse": "TG ID/address", "Audio-Modus:": "Audio mode:",
    "Nur unverschlüsselt": "Unencrypted only", "Immer versuchen": "Always attempt", "Aus": "Off",
    "Decoder-Audio": "Decoder audio", "WAV speichern": "Save WAV",
    "Aktiviert Audio aus der internen TETRA-Decoder-Kette.": "Enable audio from the internal TETRA decoder pipeline.",
    "Schreibt nur dann WAV-Dateien, wenn dieser Haken bewusst gesetzt ist.": "Write WAV files only when this option is explicitly enabled.",
    "Zeit": "Time", "Typ": "Type", "Inhalt": "Content", "PNG speichern": "Save PNG",
    "Referenzfrequenz:": "Reference frequency:", "Suchbreite ±:": "Search span ±:",
    "PPM berechnen": "Calculate PPM", "RF-Gain automatisch": "Automatic RF gain", "Start-Kalibrierung": "Startup calibration",
    "Kalibrierung:": "Calibration:", "beim Programmstart": "at startup",
    "Referenz: WDR 2 Essen 99,200 MHz": "Reference: WDR 2 Essen 99.200 MHz", "Auto-Kalibrierung:": "Auto calibration:",
    "RF-Gain:": "RF gain:", "Audio-AGC-Ziel:": "Audio AGC target:",
    "vollständige Decoderzeilen in tetra.log schreiben": "Write complete decoder output to tetra.log",
    "Datei-Logging:": "File logging:", "Übersicht": "Overview", "Kanäle": "Channels",
    "Audio && Daten": "Audio && Data", "Netz": "Network", "Daten": "Data",
    "Spektrum && Steuerung": "Spectrum && Control", "Audio && Aktivität": "Audio && Activity",
    "immer versuchen": "always attempt", "nur unverschlüsselt": "unencrypted only",
    "Modus: immer versuchen": "Mode: always attempt", "Modus: nur unverschlüsselt": "Mode: unencrypted only",
    "Modus: aus": "Mode: off", "Modus: Manuell": "Mode: Manual",
    "Modus gewechselt: Manuell": "Mode changed: Manual", "Modus gewechselt: Automatisch": "Mode changed: Automatic",
    "ohne festen Index": "no fixed index", "kein Gerät": "no device", "RTL-SDR nicht erkannt": "RTL-SDR not detected",
    "läuft dauerhaft": "running continuously", "Suche läuft": "search running", "Spektrum läuft": "spectrum running",
    "{wert0} bestätigt": "{wert0} confirmed", "{wert0} ausgewählt": "{wert0} selected", "alle anzeigen": "show all",
    "bestätigt": "confirmed", "unklar": "unclear", "möglich": "possible", "Fehler": "Error", "kein TETRA": "no TETRA",
    "nicht geprüft": "not checked", "verschlüsselt": "encrypted", "unverschlüsselt": "unencrypted",
    "unverschlüsselt, Backend fehlt": "unencrypted, backend missing", "Audio möglich": "audio possible", "keine Audioframes": "no audio frames",
    "Dauerhafte TETRA-Überwachung gestartet.": "Continuous TETRA monitoring started.",
    "Dauerhafte TETRA-Überwachung gestoppt.": "Continuous TETRA monitoring stopped.",
    "Kalibrierung läuft bereits.": "Calibration is already running.", "Kalibrierung läuft...": "Calibration running...",
    "Kalibrierung beendet.": "Calibration finished.",
    "Kalibrierung reagierte nicht rechtzeitig und wird hart beendet.": "Calibration did not respond in time and is being terminated.",
    "Kalibrierung mit Gerät {wert0} ({wert1}), Referenz {wert2:.4f} MHz": "Calibration with device {wert0} ({wert1}), reference {wert2:.4f} MHz",
    "PPM-Kalibrierung verworfen: Ergebnis {wert0} ppm (Änderung {wert1:+.1f} ppm) ist für die WFM-Referenz unplausibel. Aktueller PPM-Wert bleibt erhalten.": "PPM calibration rejected: result {wert0} ppm (change {wert1:+.1f} ppm) is implausible for the WFM reference. Current PPM value retained.",
    "PPM {wert0} -> {wert1} (Restfehler {wert2:+.1f} Hz, SNR {wert3:.1f} dB){wert4}": "PPM {wert0} -> {wert1} (residual error {wert2:+.1f} Hz, SNR {wert3:.1f} dB){wert4}",
    "RF-Gain automatisch: {wert0:.1f} dB (SNR {wert1:.1f} dB, Clipping {wert2:.2f}%)": "Automatic RF gain: {wert0:.1f} dB (SNR {wert1:.1f} dB, clipping {wert2:.2f}%)",
    "alle gefundenen Kandidaten": "all detected candidates",
    "TETRA-Signalsuche gestartet.": "TETRA signal search started.",
    "TETRA-Signalsuche beendet.": "TETRA signal search finished.",
    "TETRA-Signalsuche reagierte nicht rechtzeitig und wird hart beendet.": "TETRA signal search did not respond in time and is being terminated.",
    "[Signalsuche] {wert0}": "[Signal search] {wert0}",
    "TETRA-Signal bestätigt auf {wert0:.4f} MHz.": "TETRA signal confirmed on {wert0:.4f} MHz.",
    "Bitte zuerst eine Frequenz aus der Signalsuche markieren.": "Please select a frequency from the signal search first.",
    "{wert0:.4f} MHz ist nicht bestätigt ({wert1}); Dekodierung wird trotzdem gestartet.": "{wert0:.4f} MHz is not confirmed ({wert1}); starting decoding anyway.",
    "Bestätigte TETRA-Frequenz übernommen: {wert0:.4f} MHz": "Confirmed TETRA frequency selected: {wert0:.4f} MHz",
    "Der Kanal signalisiert Luftschnittstellen-Verschlüsselung; Audio wird deshalb nicht ausgegeben.": "The channel signals air-interface encryption; audio output is disabled.",
    "Verschlüsseltes TETRA-Signal erkannt; Audioausgabe bleibt aus.": "Encrypted TETRA signal detected; audio output remains disabled.",
    "Audioausgabe ist nur bei unverschlüsselter Sprache und audiofähiger Decoder-Kette möglich.": "Audio output requires unencrypted speech and an audio-capable decoder pipeline.",
    "Alle installierten Basiswerkzeuge wurden gefunden.": "All installed basic tools were found.",
    "Osmocom-TETRA-Binaries gefunden. Fuer Live-Demodulation wird zusaetzlich GNU Radio Python oder WSL mit GNU Radio benoetigt.": "Osmocom-TETRA binaries found. Live demodulation additionally requires GNU Radio Python or WSL with GNU Radio.",
    "osmocom-tetra Decoder fehlt. Bitte install.sh ausfuehren oder GNU Radio, tetra-rx und float_to_bits installieren.": "osmocom-tetra decoder missing. Please run install.sh or install GNU Radio, tetra-rx and float_to_bits.",
    "osmocom-tetra Decoder fehlt. Der Windows-Installer bringt tetra-rx/float_to_bits mit; fuer Live-Demodulation wird zusaetzlich GNU Radio Python oder WSL benoetigt.": "osmocom-tetra decoder missing. The Windows installer includes tetra-rx/float_to_bits; live demodulation additionally requires GNU Radio Python or WSL.",
    "osmocom-tetra Decoder fehlt - bitte manuell installieren.": "osmocom-tetra decoder missing - please install it manually.",
    "install.ps1 benoetigt Administratorrechte. Starte die App als Administrator oder nutze den Windows-Installer erneut.": "install.ps1 requires administrator privileges. Run the app as administrator or run the Windows installer again.",
    "rtl_sdr nicht gefunden; Kalibrierung nicht möglich.": "rtl_sdr not found; calibration is unavailable.",
    "RF-Gain-Automatik fehlgeschlagen: {wert0}": "Automatic RF gain failed: {wert0}",
    "PPM-Kalibrierung übersprungen, weil der RTL-SDR keine IQ-Daten liefert.": "PPM calibration skipped because the RTL-SDR is not delivering IQ data.",
    "PPM-Kalibrierung fehlgeschlagen: {wert0}": "PPM calibration failed: {wert0}",
    "PPM-Kalibrierung auf {wert0:.4f} MHz startet...": "Starting PPM calibration on {wert0:.4f} MHz...",
    "Referenzsignal schwach; Ergebnis prüfen.": "Weak reference signal; check the result.",
    "RF-Gain-Automatik fand keine brauchbare Messung.": "Automatic RF gain found no usable measurement.",
    "rtl_power nicht gefunden; Signalsuche nicht möglich.": "rtl_power not found; signal search is unavailable.",
    "Hinweis: TETRA-Prüfung braucht rtl_sdr, tetra-rx, GNU Radio Python und simdemod3.py.": "Note: TETRA validation requires rtl_sdr, tetra-rx, GNU Radio Python and simdemod3.py.",
    "Keine auffälligen TETRA-Kandidaten gefunden.": "No potential TETRA candidates found.",
    "Signalsuche wurde gestoppt": "Signal search was stopped",
    "Dekoderkette für die Prüfung nicht vollständig gefunden": "The decoder pipeline required for validation is incomplete",
    "keine IQ-/Demodulationsdaten; RTL-SDR vermutlich belegt oder Treiberzugriff blockiert": "no IQ/demodulation data; RTL-SDR may be busy or driver access blocked",
    "Prüfung fehlgeschlagen: {wert0}": "Validation failed: {wert0}",
    "GNU Radio/simdemod3.py nicht verfügbar": "GNU Radio/simdemod3.py unavailable",
    "CLI-Modus wurde per --cli angefordert.": "CLI mode requested with --cli.",
    "Gain in dB oder 'max' für den höchsten verfügbaren Gain-Wert.": "Gain in dB or 'max' for the highest available gain.",
    "Der Gain-Wert darf nicht leer sein.": "Gain must not be empty.",
    "Der Gain-Wert muss eine Zahl in dB oder 'max' sein.": "Gain must be a number in dB or 'max'.",
    "rtl_sdr-Aufnahme abgebrochen.": "rtl_sdr recording cancelled.",
    "Zu wenige IQ-Samples für FFT-Auswertung.": "Too few IQ samples for FFT analysis.",
    "Sprechgruppen-Filter aktiv": "Talkgroup filter enabled", "Sprechgruppen-Filter aus": "Talkgroup filter disabled",
})

# Statuswerte bleiben intern deutsch und werden erst bei der Anzeige übersetzt.
for _deutsch, _englisch in {
    "wartet": "waiting", "Wiedergabe aktiv": "playback active",
    "wartet auf unverschlüsselte Sprache": "waiting for unencrypted speech",
    "Audiogerät nicht verfügbar": "audio device unavailable",
    "keine audiofähige Decoder-Kette verfügbar": "no audio-capable decoder pipeline available",
    "ausgeschaltet": "disabled", "gestoppt": "stopped", "Signal verschlüsselt": "signal encrypted",
    "Dekoder gestoppt": "decoder stopped", "TETRA-Audio-Backend fehlt.": "TETRA audio backend missing.",
    "Backend gestartet, wartet auf unverschlüsselte Sprache.": "backend started, waiting for unencrypted speech.",
    "Backend gestartet, PCM wird wiedergegeben.": "backend started, playing PCM.",
    "unverschlüsselte Sprache erkannt, PCM aktiv.": "unencrypted speech detected, PCM active.",
    "verschlüsseltes Signal erkannt, PCM stumm.": "encrypted signal detected, PCM muted.",
    "Live-Backend konnte nicht gestartet werden.": "could not start live backend.",
    "WSL-tetra-rx für Audio fehlt.": "WSL-tetra-rx for audio is missing.",
    "mit der aktuellen Windows-Osmocom-Pipeline nicht verfügbar; Steuerdaten, Netzinfos und Sprechgruppen/Adressen werden dekodiert.": "unavailable with the current Windows Osmocom pipeline; control data, network information and talkgroups/addresses are decoded.",
    "nicht verfügbar, weil kein audiofähiger Legacy-Decoder gefunden wurde.": "unavailable because no audio-capable legacy decoder was found.",
    "unverschlüsselte TETRA-Sprache ist signalisiert; das Audio-Backend kann PCM ausgeben.": "unencrypted TETRA speech is signalled; the audio backend can output PCM.",
    "unverschlüsselte TETRA-Sprache ist signalisiert, aber die aktuelle Windows-Pipeline liefert kein PCM-Audio.": "unencrypted TETRA speech is signalled, but the current Windows pipeline does not deliver PCM audio.",
    "TETRA-Sprache ist verschlüsselt; Audioausgabe bleibt aus.": "TETRA speech is encrypted; audio output remains disabled.",
}.items():
    ENGLISCHE_TEXTE[_deutsch] = _englisch
    for _präfix, _zielpräfix in (("Audio-Status: ", "Audio status: "), ("Audioausgabe: ", "Audio output: "), ("Audiohinweis: ", "Audio note: ")):
        ENGLISCHE_TEXTE[_präfix + _deutsch] = _zielpräfix + _englisch


ENGLISCHE_TEXTE.update({
    "Sprechgruppen/Adressen: {wert0}": "Talkgroups/addresses: {wert0}",
    "gültige TETRA-Bursts": "valid TETRA bursts",
    "Dekoder-Ausgabe ohne gültige CRC": "decoder output without valid CRC",
    "zu wenige Demodulationsbits ({wert0} Byte)": "too few demodulation bits ({wert0} bytes)",
    "keine gültigen TETRA-Bursts": "no valid TETRA bursts", "abgebrochen": "cancelled", "Kandidat": "candidate",
    "Unbehandelte Ausnahme": "Unhandled exception",
    "\nUnbehandelte Ausnahme {wert0}\n": "\nUnhandled exception {wert0}\n",
    "rtl_sdr liefert keine IQ-Daten (Timeout nach {wert0:.1f} Sekunden).": "rtl_sdr is not delivering IQ data (timeout after {wert0:.1f} seconds).",
    "rtl_sdr-Aufnahme fehlgeschlagen: {wert0}": "rtl_sdr recording failed: {wert0}",
    "rtl_sdr lieferte zu wenige IQ-Daten ({wert0} Byte).": "rtl_sdr delivered too little IQ data ({wert0} bytes).",
    "RTL-SDR liefert keine IQ-Daten. Kalibrierung abgebrochen. Bitte Stick kurz abziehen/einstecken, USB-Port wechseln und mit Zadig WinUSB für Bulk-In Interface 0 prüfen. Technik: {wert0}": "RTL-SDR is not delivering IQ data. Calibration cancelled. Please reconnect the dongle, try another USB port, and check WinUSB for Bulk-In Interface 0 in Zadig. Details: {wert0}",
    "RF-Gain-Automatik auf {wert0:.4f} MHz testet bis zu {wert1} Stufen...": "Automatic RF gain on {wert0:.4f} MHz is testing up to {wert1} levels...",
    "Gain {wert0:.1f} dB konnte nicht gemessen werden: {wert1}": "Could not measure gain {wert0:.1f} dB: {wert1}",
    "Gain {wert0:.1f} dB: SNR {wert1:.1f} dB, Clipping {wert2:.2f}%": "Gain {wert0:.1f} dB: SNR {wert1:.1f} dB, clipping {wert2:.2f}%",
    "rtl_power lieferte keine Spektrumsdaten; nutze Simulationsdaten.": "rtl_power delivered no spectrum data; using simulated data.",
    "Scanne {wert0} nach TETRA-Kandidaten...": "Scanning {wert0} for TETRA candidates...",
    "{wert0}: keine Spektrumsdaten empfangen.": "{wert0}: no spectrum data received.",
    "{wert0}: {wert1} Kandidaten aus Pegeldaten.": "{wert0}: {wert1} candidates from signal level data.",
    "Pegel {wert0:+.1f} dB über Median; Dekoderprüfung startet": "Level {wert0:+.1f} dB above median; starting decoder validation",
    "Prüfe Kandidat {wert0}/{wert1}: {wert2:.4f} MHz": "Checking candidate {wert0}/{wert1}: {wert2:.4f} MHz",
    "rtl_power-Scan fehlgeschlagen: {wert0}": "rtl_power scan failed: {wert0}",
    "{wert0}; Prüfmitte {wert1:.4f} MHz, IQ {wert2}, Kanalversatz {wert3:+.0f} Hz": "{wert0}; probe centre {wert1:.4f} MHz, IQ {wert2}, channel offset {wert3:+.0f} Hz",
    "{wert0}; geprüft: {wert1}": "{wert0}; checked: {wert1}",
    "Audioausgabe: Backend konnte nicht starten: {wert0}": "Audio output: could not start backend: {wert0}",
    "Audio-Status: Backend konnte nicht starten: {wert0}": "Audio status: could not start backend: {wert0}",
    "Backend konnte nicht starten: {wert0}": "Could not start backend: {wert0}",
    "Nutze audiofähige TETRA-Pipeline (rtl_sdr -> Kanalfilter -> simdemod3.py -> WSL-tetra-rx -> ETSI-Codec).": "Using audio-capable TETRA pipeline (rtl_sdr -> channel filter -> simdemod3.py -> WSL-tetra-rx -> ETSI codec).",
    "Audiofähige TETRA-Dekodierung fehlgeschlagen: {wert0}": "Audio-capable TETRA decoding failed: {wert0}",
    "Nutze Windows-kompatible Osmocom-TETRA Pipeline (rtl_sdr -> u8/complex64-Konverter -> 25-kHz-Kanalfilter -> simdemod3.py -> tetra-rx).": "Using Windows-compatible Osmocom-TETRA pipeline (rtl_sdr -> u8/complex64 converter -> 25 kHz channel filter -> simdemod3.py -> tetra-rx).",
    "Zu wenige Demodulationsbits empfangen ({wert0} Byte).": "Too few demodulation bits received ({wert0} bytes).",
    "Decoderblock wurde begrenzt, damit die Oberfläche bedienbar bleibt.": "Decoder block limited to keep the interface responsive.",
    "TETRA-Daten empfangen; Rohdaten ohne neue Netz-, Sprechgruppen- oder Audioinfos wurden ausgeblendet.": "TETRA data received; raw data without new network, talkgroup or audio information was hidden.",
    "Weitere Decoderzeilen in diesem Block wurden ausgeblendet, damit die Oberfläche reaktionsfähig bleibt.": "Additional decoder lines in this block were hidden to keep the interface responsive.",
    "Keine gültigen TETRA-Bursts in diesem Zeitfenster dekodiert.": "No valid TETRA bursts decoded in this time window.",
    "Windows-TETRA-Dekodierung fehlgeschlagen: {wert0}": "Windows TETRA decoding failed: {wert0}",
    "Windows-Dekodierlauf beendet; weitere Blöcke können bei Bedarf erneut gestartet werden.": "Windows decoding run ended; additional blocks can be started again as needed.",
    "Nutze offizielle Osmocom-TETRA Pipeline (rtl_sdr -> simdemod3.py -> tetra-rx).": "Using the official Osmocom-TETRA pipeline (rtl_sdr -> simdemod3.py -> tetra-rx).",
    "Dekodierung gestartet mit Gerät {wert0} ({wert1}) bei {wert2:.3f} MHz (Tuning {wert3:.4f} MHz, Kanalversatz {wert4:+.0f} Hz, IQ {wert5})": "Decoding started with device {wert0} ({wert1}) at {wert2:.3f} MHz (tuning {wert3:.4f} MHz, channel offset {wert4:+.0f} Hz, IQ {wert5})",
    "maximal {wert0} Kandidaten": "up to {wert0} candidates",
    "TETRA-Signalsuche gestartet mit Gerät {wert0}, PPM {wert1}, Gain {wert2:.1f} dB, Bereich {wert3}, {wert4}.": "TETRA signal search started with device {wert0}, PPM {wert1}, gain {wert2:.1f} dB, range {wert3}, {wert4}.",
    "Kalibrierung mit Gerät {wert0} auf {wert1:.4f} MHz.": "Calibrating with device {wert0} on {wert1:.4f} MHz.",
    "Scan gestartet mit Gerät {wert0} ({wert1}) ({wert2}, {wert3:.0f}-{wert4:.0f} MHz)": "Scan started with device {wert0} ({wert1}) ({wert2}, {wert3:.0f}-{wert4:.0f} MHz)",
    "Frequenz {wert0:.4f} MHz ist nicht bestätigt ({wert1}); Dekodierung wird trotzdem gestartet.": "Frequency {wert0:.4f} MHz is not confirmed ({wert1}); starting decoding anyway.",
    "Bestätigte TETRA-Frequenz übernommen: {wert0:.4f} MHz (Tuning {wert1:.4f} MHz, Kanalversatz {wert2:+.0f} Hz, IQ {wert3}).": "Confirmed TETRA frequency selected: {wert0:.4f} MHz (tuning {wert1:.4f} MHz, channel offset {wert2:+.0f} Hz, IQ {wert3}).",
    "Audio-Status: {wert0}": "Audio status: {wert0}", "Audioausgabe: {wert0}": "Audio output: {wert0}",
    "TETRA-Netzinfo: {wert0}": "TETRA network information: {wert0}",
    "DL {wert0:.4f} MHz, UL {wert1:.4f} MHz, Service {wert2}": "DL {wert0:.4f} MHz, UL {wert1:.4f} MHz, service {wert2}",
    "Sprechgruppen-Filter aktiv.": "Talkgroup filter enabled.", "Sprechgruppen-Filter aus.": "Talkgroup filter disabled.",
    "CLI-Start mit Gerät {wert0} ({wert1}), PPM {wert2}, Frequenzbereich {wert3:.1f}-{wert4:.1f} MHz, Gain {wert5:.1f} dB, Auto-Dekodierung {wert6}, Audio {wert7}": "CLI started with device {wert0} ({wert1}), PPM {wert2}, frequency range {wert3:.1f}-{wert4:.1f} MHz, gain {wert5:.1f} dB, automatic decoding {wert6}, audio {wert7}",
})

# Nur fachliche Zustände verschachtelt übersetzen, niemals Gerätenamen/IDs.
_ÜBERSETZBARE_FELDER = {
    "Audio-Status: {wert0}": ("wert0",), "Audioausgabe: {wert0}": ("wert0",),
    "[Signalsuche] {wert0}": ("wert0",), "TETRA-Netzinfo: {wert0}": ("wert0",),
    "Scanne {wert0} nach TETRA-Kandidaten...": ("wert0",),
    "{wert0}: keine Spektrumsdaten empfangen.": ("wert0",),
    "{wert0}: {wert1} Kandidaten aus Pegeldaten.": ("wert0",),
    "TETRA-Signalsuche gestartet mit Gerät {wert0}, PPM {wert1}, Gain {wert2:.1f} dB, Bereich {wert3}, {wert4}.": ("wert3", "wert4"),
    "Scan gestartet mit Gerät {wert0} ({wert1}) ({wert2}, {wert3:.0f}-{wert4:.0f} MHz)": ("wert0", "wert2"),
    "Dekodierung gestartet mit Gerät {wert0} ({wert1}) bei {wert2:.3f} MHz (Tuning {wert3:.4f} MHz, Kanalversatz {wert4:+.0f} Hz, IQ {wert5})": ("wert0",),
    "Frequenz {wert0:.4f} MHz ist nicht bestätigt ({wert1}); Dekodierung wird trotzdem gestartet.": ("wert1",),
    "{wert0}; Prüfmitte {wert1:.4f} MHz, IQ {wert2}, Kanalversatz {wert3:+.0f} Hz": ("wert0",),
    "{wert0}; geprüft: {wert1}": ("wert0",),
    "CLI-Start mit Gerät {wert0} ({wert1}), PPM {wert2}, Frequenzbereich {wert3:.1f}-{wert4:.1f} MHz, Gain {wert5:.1f} dB, Auto-Dekodierung {wert6}, Audio {wert7}": ("wert0", "wert6", "wert7"),
}


def _anzeigemuster_erstellen():
    muster = []
    formatierer = string.Formatter()
    for deutsch, englisch in ENGLISCHE_TEXTE.items():
        teile = list(formatierer.parse(deutsch))
        if not any(feld is not None for _, feld, _, _ in teile):
            continue
        regex = ""
        for text, feld, _, _ in teile:
            regex += re.escape(text)
            if feld is not None:
                regex += "(?P<" + feld + ">.*?)"
        ziel = "".join(text + ("{" + feld + "}" if feld is not None else "") for text, feld, _, _ in formatierer.parse(englisch))
        muster.append((re.compile("^" + regex + "$", re.DOTALL), ziel, len(deutsch), _ÜBERSETZBARE_FELDER.get(deutsch, ())))
    return sorted(muster, key=lambda eintrag: eintrag[2], reverse=True)


_ANZEIGEMUSTER = _anzeigemuster_erstellen()


def anzeigetext(text):
    """Übersetzt nur an Ausgabegrenzen; die deutschen Protokollwerte bleiben stabil."""
    text = str(text)
    if _sprache == "de":
        return text
    if text in ENGLISCHE_TEXTE:
        return ENGLISCHE_TEXTE[text]
    for muster, ziel, _, fachwerte in _ANZEIGEMUSTER:
        treffer = muster.fullmatch(text)
        if treffer:
            werte = treffer.groupdict()
            for feld in fachwerte:
                if werte[feld] != text:
                    werte[feld] = anzeigetext(werte[feld])
            return ziel.format(**werte)
    for präfix in ("Fehlende Programme: ", "Fehlende Python-Module: ", "Fehlende Zusatzwerkzeuge: "):
        if text.startswith(präfix):
            return ENGLISCHE_TEXTE[präfix] + text[len(präfix):]
    if "; " in text:
        return "; ".join(anzeigetext(teil) for teil in text.split("; "))
    return text


def startsprache(gespeichert=None, argumente=None, systemsprache=None):
    """Priorität: --language/--sprache, gespeicherte Wahl, Betriebssystem."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--language", "--sprache", choices=("de", "en"))
    optionen, _ = parser.parse_known_args(sys.argv[1:] if argumente is None else argumente)
    if optionen.language:
        return optionen.language
    if gespeichert in ("de", "en"):
        return gespeichert
    if systemsprache is None:
        try:
            systemsprache = locale.getlocale()[0]
        except (ValueError, TypeError):
            systemsprache = None
        if not systemsprache and sys.platform.startswith("win"):
            try:
                import ctypes
                systemsprache = locale.windows_locale.get(
                    ctypes.windll.kernel32.GetUserDefaultUILanguage(), "en"
                )
            except (AttributeError, OSError):
                systemsprache = None
    return "de" if str(systemsprache or "en").lower().startswith("de") else "en"


_sprache = "de"


def sprache_festlegen(sprache):
    """Ändert nur die Textsprache, ohne Geräte oder Prozesse anzufassen."""
    if sprache not in ("de", "en"):
        raise ValueError("Sprache muss 'de' oder 'en' sein.")
    global _sprache
    _sprache = sprache


def aktuelle_sprache():
    return _sprache


def übersetzen(text, **werte):
    """Übersetzt Vorlagen vor der Formatierung; Gerätedaten bleiben unverändert."""
    vorlage = ENGLISCHE_TEXTE.get(text, text) if _sprache == "en" else text
    return vorlage.format(**werte) if werte else vorlage


def übersetzungsquelle(text):
    """Ermittelt den deutschen Ursprung bereits übersetzter statischer Texte."""
    if text in ENGLISCHE_TEXTE:
        return text
    return next((deutsch for deutsch, englisch in ENGLISCHE_TEXTE.items() if englisch == text), text)


def copyright_text(jahr=None):
    jahr = date.today().year if jahr is None else jahr
    zeitraum = "2026" if jahr <= 2026 else f"2026 - {jahr}"
    return f"© {zeitraum} Erik Schauer, do1ffe@darc.de"


# © 2026 Erik Schauer, do1ffe@darc.de
