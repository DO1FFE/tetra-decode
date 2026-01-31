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
- **Sprechgruppen** – erkannte Sprechgruppen-IDs werden gezählt, mit Zeitstempel gespeichert und lassen sich gezielt auswählen, sodass nur relevante Gruppen in der Ausgabe erscheinen.
- **Automatische Dekodierung nach Scan** – auf Wunsch startet die TETRA-Dekodierung direkt nach einem Scanvorgang.
- **Aktivitätserkennung** – Pegelüberwachung signalisiert Aktivität und kann optional Telegram-Benachrichtigungen senden. Erkanntes wird als WAV aufgezeichnet.
- **Zell-Informationen** – Dekodierte Cell-IDs, LAC, MCC/MNC und die genutzte Frequenz werden in einer Tabelle gespeichert und lassen sich als CSV exportieren.
- **Paketstatistiken** – Ein Balkendiagramm zeigt die empfangenen TETRA-Pakettypen.
- **Scheduler** – Automatische Scan- und Dekodierzyklen laufen periodisch mit konfigurierbarem Intervall.
- **Spektrum-Screenshots** – Das aktuell angezeigte Spektrum kann als PNG gespeichert werden.
- **Manueller Frequenzmodus** – die automatische Frequenzwahl kann gesperrt werden, um eine fixe Frequenz beizubehalten.
- **Designauswahl** – Zwischen hellem und dunklem Modus umschalten.
- **Konfiguration und Gerätauswahl** – Erkannte SDR-Geräte und die meisten Einstellungen werden in `~/.tetra_gui_config.json` abgelegt.
- **Setup-Assistent** – Prüft benötigte Tools und Python-Module und installiert sie bei Bedarf.
- **PPM-Korrektur** – Einstellbarer PPM-Wert für RTL-SDR wird an alle SDR-Werkzeuge übergeben.

## Einrichtung

Unter Linux installierst du alle benötigten Pakete bequem über `setup.sh`. Das Skript erkennt automatisch gängige Paketmanager (APT, DNF, Pacman, Zypper), installiert die benötigten Bibliotheken und baut die osmocom-tetra-Werkzeuge bei Bedarf direkt aus den Quellen:

```bash
./setup.sh
```

Falls du einzelne Komponenten später nachrüsten musst, führt `install.sh` eine kompakte Prüfung aus und installiert fehlende RTL-SDR- oder osmocom-tetra-Werkzeuge sowie die Python-Abhängigkeiten automatisch nach:

```bash
./install.sh
```

Auf Windows führst du stattdessen `setup.ps1` in einer administrativen PowerShell aus. Das Skript lädt fehlende Abhängigkeiten automatisch herunter, richtet die rtl-sdr-Hilfsprogramme sowie die osmocom-tetra-Binaries in `%ProgramData%\tetra-decode` ein und ergänzt den `PATH`. Chocolatey (wird bei Bedarf installiert) sorgt zusätzlich für Werkzeuge wie **Zadig** und SoX. Sollten einzelne Download-Quellen temporär nicht erreichbar sein, weist dich das Skript darauf hin und bietet die Möglichkeit zur manuellen Nachinstallation:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\setup.ps1
```

Für nachträgliche Ergänzungen steht außerdem `install.ps1` bereit. Das Skript erkennt fehlende Werkzeuge oder Python-Module und lädt sie – inklusive Chocolatey-Bootstrap – automatisch nach:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\install.ps1
```

### PowerShell-Fehler wegen Ausführungsrichtlinie

Wenn PowerShell meldet, dass das Skript nicht digital signiert ist, kannst du es für die aktuelle Sitzung freigeben oder die Dateien entsperren:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
Unblock-File -Path .\setup.ps1, .\install.ps1
.\setup.ps1
```

Alternativ kannst du das Skript direkt mit einer temporären Richtlinie starten:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\setup.ps1
```
---

# TETRA Decode (Deutsch)

Dieses Repository enthält eine einfache PyQt5-Anwendung, die demonstriert, wie man mit einem SDR (z.B. RTL-SDR, HackRF, LimeSDR) zwischen 380 und 430 MHz scannt. Die stärkste Frequenz wird automatisch ausgewählt und über externe Kommandozeilenwerkzeuge wie `rtl_power` und `rtl_fm` zu Audio demoduliert. Außerdem integriert sie die osmocom-tetra-Werkzeuge (`receiver1`, `demod_float`, `tetra-rx`), um unverschlüsselte TETRA-Kontrollinformationen zu dekodieren.

Die grafische Oberfläche zeigt ein Echtzeit-Spektrum, bietet Start-/Stopp-Steuerung und spielt empfangenes Audio über PyAudio ab.

Zusätzliche Funktionen umfassen einen Scheduler für automatische Scan-/Dekodierzyklen, eine Anzeige von Zellinformationen mit CSV-Export, einfache Paketstatistiken, Telegram-Benachrichtigungen bei Aktivität, Audioaufnahmen und Spektrum-Screenshots. In den Einstellungen kann ein helles oder dunkles Design ausgewählt werden.

Das Programm startest du mit:

```bash
python sdr_gui.py
```

Externe SDR-Werkzeuge sowie die osmocom-tetra-Binärdateien müssen installiert und im Systempfad verfügbar sein.

## Einrichtung

Unter Linux kannst du `setup.sh` ausführen. Das Hilfsskript erkennt gängige Paketmanager (APT, DNF, Pacman, Zypper), installiert alle benötigten Entwicklungs-Header und baut bei Bedarf die osmocom-tetra-Suite aus den Quellen, bevor es die Python-Abhängigkeiten installiert:

```bash
./setup.sh
```

Unter Windows startest du `setup.ps1` aus einer administrativen PowerShell. Das Skript bootstrapped Chocolatey bei Bedarf, lädt die rtl-sdr-Hilfsprogramme und die osmocom-tetra-Binärdateien nach `%ProgramData%\tetra-decode`, ergänzt den `PATH` und installiert anschließend die Python-Pakete. Wenn Download-Quellen vorübergehend nicht erreichbar sind, weist dich das Skript darauf hin, damit du die Dateien manuell bereitstellen kannst:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\setup.ps1
```

Für Nachinstallationen gibt es zusätzlich `install.ps1`. Das Hilfsskript erkennt fehlende Werkzeuge oder Python-Module und lädt sie automatisch nach (inklusive Chocolatey-Bootstrap, falls nötig):

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\install.ps1
```

## Funktionen

- **Frequenzscan** – nutzt `rtl_power`, um einen wählbaren Bereich abzusuchen. Das stärkste Signal wird automatisch für die weitere Verarbeitung ausgewählt.
- **Echtzeit-Spektrum** – das Spektrum wird während des Scans kontinuierlich dargestellt.
- **Audio-Demodulation** – `rtl_fm` demoduliert die gewählte Frequenz, PyAudio spielt das Audio ab. Eine anpassbare AGC hält die Lautstärke stabil.
- **TETRA-Dekodierung** – integriert `receiver1`, `demod_float` und `tetra-rx`, um unverschlüsselte Kontrollkanäle zu dekodieren. Die Ausgabe erscheint in einem eigenen Tab und kann per Regex gefiltert werden.
- **Aktivitätserkennung** – Audio-Pegelüberwachung zeigt Aktivität an und kann optional Telegram-Benachrichtigungen senden. Erkannte Aktivität wird als WAV aufgezeichnet.
- **Zellinformationen** – dekodierte Cell-IDs, LAC, MCC/MNC und die genutzte Frequenz werden in einer Tabelle gespeichert und können als CSV exportiert werden.
- **Paketstatistiken** – zeigt ein Balkendiagramm der empfangenen TETRA-Pakettypen.
- **Scheduler** – automatische Scan- und Dekodierzyklen laufen periodisch mit konfigurierbarem Intervall.
- **Spektrum-Snapshots** – speichert das aktuell angezeigte Spektrum als PNG-Datei.
- **Designauswahl** – Wechsel zwischen hellem und dunklem Modus.
- **Konfiguration und Gerätauswahl** – erkannte SDR-Geräte und die meisten Einstellungen werden in `~/.tetra_gui_config.json` gespeichert.
- **Setup-Assistent** – prüft benötigte Tools und Python-Module und installiert sie bei Bedarf.
- **PPM-Korrektur** – einstellbarer RTL-SDR-PPM-Wert, der an alle SDR-Befehle übergeben wird.

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
