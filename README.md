# TETRA Decode

Dieses Repository enthält eine einfache PyQt5-Anwendung, die demonstriert, wie man mit einem SDR (z.B. RTL-SDR, HackRF, LimeSDR) im Bereich von 380 bis 430 MHz nach Signalen sucht. Die stärkste Frequenz wird automatisch ausgewählt und über externe Werkzeuge wie `rtl_power` und `rtl_fm` zu Audio demoduliert. Außerdem sind die osmocom-tetra-Programme (`receiver1`, `demod_float`, `tetra-rx`) eingebunden, um unverschlüsselte TETRA-Kontrollkanäle zu dekodieren.

Die grafische Oberfläche zeigt ein Echtzeit-Spektrum, bietet Start- und Stopp-Steuerung und gibt den empfangenen Ton über PyAudio wieder.

Zusätzliche Funktionen umfassen einen Scheduler für automatische Scan- und Dekodierzyklen, eine Anzeige von Zell-Informationen mit CSV-Export, einfache Paketstatistiken, Telegram-Benachrichtigungen bei Aktivität, Audioaufnahmen und Spektrum-Screenshots. In den Einstellungen kann zwischen einem hellen und einem dunklen Design gewählt werden.

Das Programm startest du mit:

```bash
python sdr_gui.py
```

Externe SDR-Werkzeuge sowie die osmocom-tetra-Binärdateien müssen installiert und im Systempfad verfügbar sein.

## Funktionen

- **Frequenzscan** – `rtl_power` durchsucht einen wählbaren Bereich und wählt automatisch das stärkste Signal aus.
- **Live-Spektrum** – das Spektrum wird während des Scans kontinuierlich dargestellt.
- **Audio-Demodulation** – `rtl_fm` demoduliert die gewählte Frequenz und PyAudio spielt den Ton ab. Eine anpassbare AGC hält die Lautstärke stabil.
- **TETRA-Dekodierung** – `receiver1`, `demod_float` und `tetra-rx` dekodieren unverschlüsselte Kontrollkanäle. Die Ausgabe erscheint in einem eigenen Tab und kann per Regex gefiltert werden.
- **Aktivitätserkennung** – Pegelüberwachung signalisiert Aktivität und kann optional Telegram-Benachrichtigungen senden. Erkanntes wird als WAV aufgezeichnet.
- **Zell-Informationen** – Dekodierte Cell-IDs, LAC, MCC/MNC und die genutzte Frequenz werden in einer Tabelle gespeichert und lassen sich als CSV exportieren.
- **Paketstatistiken** – Ein Balkendiagramm zeigt die empfangenen TETRA-Pakettypen.
- **Scheduler** – Automatische Scan- und Dekodierzyklen laufen periodisch mit konfigurierbarem Intervall.
- **Spektrum-Screenshots** – Das aktuell angezeigte Spektrum kann als PNG gespeichert werden.
- **Designauswahl** – Zwischen hellem und dunklem Modus umschalten.
- **Konfiguration und Gerätauswahl** – Erkannte SDR-Geräte und die meisten Einstellungen werden in `~/.tetra_gui_config.json` abgelegt.
- **Setup-Assistent** – Prüft benötigte Tools und Python-Module und installiert sie bei Bedarf.
- **PPM-Korrektur** – Einstellbarer PPM-Wert für RTL-SDR wird an alle SDR-Werkzeuge übergeben.

---

# TETRA Decode (English)

This repository contains a simple PyQt5 application demonstrating how to scan frequencies with an SDR (e.g. RTL-SDR, HackRF, LimeSDR) between 380 and 430 MHz. The strongest frequency is automatically selected and demodulated to audio using external command line tools such as `rtl_power` and `rtl_fm`. It also integrates the osmocom-tetra tools (`receiver1`, `demod_float`, `tetra-rx`) to decode unencrypted TETRA control information.

The GUI shows a realtime spectrum, provides start/stop controls, and plays received audio through the speakers using PyAudio.

Additional features include a scheduler for automatic scan/decoding cycles, cell information display with CSV export, basic packet statistics, Telegram notifications on activity, audio recording and spectrum snapshots. A light and dark theme can be selected in the settings tab.

Run the application with:

```bash
python sdr_gui.py
```

External SDR utilities as well as the osmocom-tetra binaries must be installed and accessible in the system path.

## Features

- **Frequency scanning** – uses `rtl_power` to sweep a selectable range. The strongest signal is automatically picked for further processing.
- **Realtime spectrum display** – the spectrum is plotted continuously while scanning.
- **Audio demodulation** – `rtl_fm` demodulates the selected frequency and PyAudio plays the audio. An adjustable AGC keeps the volume stable.
- **TETRA decoding** – integrates `receiver1`, `demod_float` and `tetra-rx` to decode unencrypted control channels. Output appears in its own tab and can be filtered by regex.
- **Activity detection** – audio level monitoring lights up an indicator and optionally sends Telegram notifications. Detected activity is recorded to WAV files.
- **Cell information** – decoded cell IDs, LAC, MCC/MNC and the used frequency are stored in a table and can be exported to CSV.
- **Packet statistics** – shows a bar chart of the received TETRA packet types.
- **Scheduler** – automatic scan and decode cycles can run periodically with a configurable interval.
- **Spectrum snapshots** – save the currently displayed spectrum as a PNG file.
- **Theme selection** – switch between light and dark mode.
- **Configuration and device selection** – detected SDR devices and most settings are stored in `~/.tetra_gui_config.json`.
- **Setup assistant** – checks for required tools and Python modules and installs them when missing.
- **PPM correction** – adjustable RTL-SDR PPM value applied to all SDR commands.

## Windows-EXE erstellen

Um das Programm unter Windows als Einzeldatei auszuführen, kannst du [PyInstaller](https://www.pyinstaller.org/) verwenden. Installiere zunächst Python 3 zusammen mit den Abhängigkeiten:

```bash
pip install -r requirements.txt
pip install pyinstaller
```

Anschließend erzeugt folgender Befehl eine portable EXE-Datei:

```bash
pyinstaller --onefile --windowed sdr_gui.py
```

Die Datei `sdr_gui.exe` findest du danach im Ordner `dist`.
