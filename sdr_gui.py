import os
import sys
import subprocess
import threading
import shutil
import argparse
from collections import deque
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import importlib
import re
import json
import wave
import time
import tempfile
import pkgutil
import ctypes.util
import shlex
try:
    import qdarkstyle
except Exception:
    qdarkstyle = None

try:
    import requests
except Exception:
    requests = None

try:
    import numpy as np
except Exception:
    pip_verfuegbar = pkgutil.find_loader("pip") is not None
    if pip_verfuegbar:
        hinweis = (
            "Fehlendes Python-Modul 'numpy'. Bitte installiere es, z. B. mit "
            "'python3 -m pip install numpy'."
        )
    else:
        hinweis = (
            "Fehlendes Python-Modul 'numpy' und 'pip' ist nicht verfügbar. "
            "Installiere zuerst pip (z. B. 'python3 -m ensurepip --upgrade' "
            "oder 'sudo apt-get install python3-pip') und danach "
            "'python3 -m pip install numpy'."
        )
    print(hinweis, file=sys.stderr)
    raise SystemExit(1)
if sys.platform.startswith("linux"):
    libgl = ctypes.util.find_library("GL")
    if libgl is None:
        print(
            "Fehlende Systembibliothek 'libGL.so.1'. Bitte installiere "
            "'libgl1' (z. B. 'sudo apt-get install libgl1') und starte "
            "das Programm erneut.",
            file=sys.stderr,
        )
        raise SystemExit(1)

from PyQt5 import QtWidgets, QtCore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pyaudio


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.expanduser("~")
CONFIG_FILE = os.path.expanduser("~/.tetra_gui_config.json")
logger = logging.getLogger("tetra")
handler = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "tetra.log"), when="midnight", backupCount=7, encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logger.setLevel(logging.INFO)
logger.addHandler(handler)


def list_sdr_devices():
    """Gibt eine Liste erkannter RTL-SDR-Geräte zurück."""
    devices = []
    try:
        out = subprocess.check_output(
            ["rtl_test", "-t"], text=True, stderr=subprocess.STDOUT, timeout=5
        )
        for line in out.splitlines():
            match = re.match(r"^\s*(\d+):\s*(.+)$", line)
            if match:
                index = int(match.group(1))
                name = match.group(2).strip()
                devices.append((name, index))
    except Exception:
        pass
    if not devices:
        try:
            out = subprocess.check_output(["lsusb"], text=True, timeout=5)
            for line in out.splitlines():
                if "RTL" in line or "Realtek" in line:
                    label = line.strip()
                    match = re.match(r"^Bus\s+\d+\s+Device\s+\d+:\s*(.+)$", label)
                    if match:
                        label = match.group(1).strip()
                    devices.append((label, None))
        except Exception:
            pass
    return devices or [("RTL-SDR", 0)]


def extract_talkgroup_ids(line: str):
    muster = re.compile(
        r"\b(?:TGID|TG|talkgroup|group)\s*[:=]?\s*(0x[0-9A-Fa-f]+|\d+)\b",
        re.IGNORECASE,
    )
    ids = []
    for match in muster.finditer(line):
        raw = match.group(1)
        try:
            value = int(raw, 0)
            ids.append(str(value))
        except ValueError:
            ids.append(raw)
    return ids


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


_MAX_GAIN_CACHE = None


def _normalize_gain_setting(value):
    if value is None:
        return "max"
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in ("max", "maximum"):
        return "max"
    try:
        return float(text)
    except ValueError:
        return "max"


def _parse_gain_argument(parser: argparse.ArgumentParser, value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        parser.error("Der Gain-Wert darf nicht leer sein.")
    lowered = text.lower()
    if lowered in ("max", "maximum"):
        return "max"
    try:
        return float(text)
    except ValueError:
        parser.error("Der Gain-Wert muss eine Zahl in dB oder 'max' sein.")


def _parse_gain_values_from_rtl_test(output: str):
    gains = []
    in_section = False
    for line in output.splitlines():
        if re.search(r"gain values", line, re.IGNORECASE):
            in_section = True
        if in_section:
            gains.extend(
                float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", line)
            )
            if not line.strip():
                in_section = False
        if in_section and re.search(r"sampling", line, re.IGNORECASE):
            in_section = False
    return max(gains) if gains else None


def _ermittle_max_gain():
    global _MAX_GAIN_CACHE
    if _MAX_GAIN_CACHE is not None:
        return _MAX_GAIN_CACHE
    fallback_gain = 49.6
    try:
        out = subprocess.check_output(
            ["rtl_test", "-t"], text=True, stderr=subprocess.STDOUT, timeout=5
        )
    except Exception:
        _MAX_GAIN_CACHE = fallback_gain
        return _MAX_GAIN_CACHE
    parsed_gain = _parse_gain_values_from_rtl_test(out)
    _MAX_GAIN_CACHE = parsed_gain if parsed_gain is not None else fallback_gain
    return _MAX_GAIN_CACHE


def _resolve_gain_value(setting):
    normalized = _normalize_gain_setting(setting)
    if normalized == "max":
        return _ermittle_max_gain()
    return float(normalized)


def _qt_xcb_verfuegbar() -> bool:
    if not sys.platform.startswith("linux"):
        return True

    qt_platform = os.environ.get("QT_QPA_PLATFORM", "").strip()
    if qt_platform and qt_platform != "xcb":
        return True

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False

    fehlende_libs = [
        lib for lib in ("xcb", "xkbcommon-x11") if ctypes.util.find_library(lib) is None
    ]
    if fehlende_libs:
        return False

    plugin_pfade = []
    env_pfade = [pfad for pfad in os.environ.get("QT_PLUGIN_PATH", "").split(os.pathsep) if pfad]
    plugin_pfade.extend(env_pfade)
    plugin_pfade.append(QtCore.QLibraryInfo.location(QtCore.QLibraryInfo.PluginsPath))

    for basis in filter(None, plugin_pfade):
        plattform_dir = os.path.join(basis, "platforms")
        if not os.path.isdir(plattform_dir):
            continue
        try:
            for datei in os.listdir(plattform_dir):
                if datei.startswith("libqxcb.so"):
                    return True
        except OSError:
            continue
    return False


def _parse_frequenzbereich(parser: argparse.ArgumentParser, werte):
    if werte is None:
        return None
    start_mhz, end_mhz = werte
    if start_mhz <= 0 or end_mhz <= 0 or end_mhz <= start_mhz:
        parser.error("Der Frequenzbereich muss zwei positive Werte in MHz (Start < Ende) enthalten.")
    return start_mhz, end_mhz


def _resolve_device(geraete, name, index):
    if index is not None:
        for label, device_id in geraete:
            if device_id == index:
                return label, index
    if name:
        for label, device_id in geraete:
            if label == name:
                return label, device_id
    if geraete:
        return geraete[0]
    return "RTL-SDR", None


def _starte_cli_modus(fehlermeldung: str) -> None:
    print(fehlermeldung, file=sys.stderr)
    print("Starte das Programm im Kommandozeilenmodus.", file=sys.stderr)
    print("\n=== TETRA-Decoder (CLI-Modus) ===")
    print("Hinweis: Für die grafische Oberfläche müssen X11/Qt-xcb verfügbar sein.")
    print("\nGefundene SDR-Geräte:")
    geraete = list_sdr_devices()
    for name, index in geraete:
        if index is None:
            print(f"- {name}")
        else:
            print(f"- {name} (Index {index})")
    print("\nBeende den CLI-Modus mit Strg+C.")

    config = load_config()
    parser = argparse.ArgumentParser(
        prog="tetra-decode",
        description="TETRA-Decoder im CLI-Modus",
    )
    parser.add_argument(
        "--geraet-name",
        help="Name des SDR-Geräts (wie in der Geräte-Liste angezeigt).",
    )
    parser.add_argument(
        "--geraet-index",
        type=int,
        help="Index des SDR-Geräts (z. B. 0).",
    )
    parser.add_argument(
        "--ppm",
        type=int,
        help="PPM-Korrektur für den SDR-Empfänger.",
    )
    parser.add_argument(
        "--gain",
        help="Gain in dB oder 'max' für den höchsten verfügbaren Gain-Wert.",
    )
    parser.add_argument(
        "--frequenzbereich",
        nargs=2,
        type=float,
        metavar=("START_MHZ", "ENDE_MHZ"),
        help="Frequenzbereich in MHz (z. B. 380 430).",
    )
    parser.add_argument(
        "--filter-regex",
        help="Regex-Filter f\u00fcr die Ausgabe im CLI-Modus.",
    )
    parser.add_argument(
        "--talkgroup",
        action="append",
        help="Sprechgruppen-ID f\u00fcr die Anzeige (mehrfach nutzbar).",
    )
    parser.add_argument(
        "--talkgroups-file",
        help="Datei mit Sprechgruppen-IDs (eine pro Zeile oder kommagetrennt).",
    )
    parser.add_argument(
        "--export-csv",
        metavar="PFAD",
        help="CSV-Export der erkannten Zellen in die angegebene Datei.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Gibt beim Beenden eine kurze Statistik aus.",
    )
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument(
        "--auto-dekodierung",
        dest="auto_dekodierung",
        action="store_true",
        help="Automatische Dekodierung nach der Frequenzauswahl aktivieren.",
    )
    auto_group.add_argument(
        "--kein-auto-dekodierung",
        dest="auto_dekodierung",
        action="store_false",
        help="Automatische Dekodierung deaktivieren.",
    )
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument(
        "--audio-wiedergabe",
        dest="audio_wiedergabe",
        action="store_true",
        help="Dekodiertes Audio wiedergeben.",
    )
    audio_group.add_argument(
        "--kein-audio-wiedergabe",
        dest="audio_wiedergabe",
        action="store_false",
        help="Audio-Wiedergabe deaktivieren.",
    )
    record_group = parser.add_mutually_exclusive_group()
    record_group.add_argument(
        "--audio-record",
        dest="audio_record",
        action="store_true",
        help="Dekodiertes Audio als WAV speichern (setzt Audio-Wiedergabe voraus).",
    )
    record_group.add_argument(
        "--kein-audio-record",
        dest="audio_record",
        action="store_false",
        help="Audio-Aufnahme deaktivieren.",
    )
    parser.set_defaults(auto_dekodierung=None, audio_wiedergabe=None, audio_record=None)

    args = parser.parse_args()
    override_config = False

    ppm = config.get("ppm", 0)
    if args.ppm is not None:
        ppm = args.ppm
        config["ppm"] = ppm
        override_config = True

    gain_setting = _normalize_gain_setting(config.get("gain", "max"))
    if args.gain is not None:
        gain_setting = _parse_gain_argument(parser, args.gain)
        config["gain"] = gain_setting
        override_config = True

    frequenzbereich = _parse_frequenzbereich(parser, args.frequenzbereich)
    if frequenzbereich is None:
        start_mhz = config.get("cli_freq_start_mhz")
        end_mhz = config.get("cli_freq_end_mhz")
        if start_mhz is not None and end_mhz is not None:
            frequenzbereich = (float(start_mhz), float(end_mhz))
        else:
            frequenzbereich = (380.0, 430.0)
    else:
        config["cli_freq_start_mhz"] = frequenzbereich[0]
        config["cli_freq_end_mhz"] = frequenzbereich[1]
        override_config = True

    auto_dekodierung = config.get("cli_auto_decode", True)
    if args.auto_dekodierung is not None:
        auto_dekodierung = args.auto_dekodierung
        config["cli_auto_decode"] = auto_dekodierung
        override_config = True

    audio_wiedergabe = config.get("cli_play_audio", False)
    if args.audio_wiedergabe is not None:
        audio_wiedergabe = args.audio_wiedergabe
        config["cli_play_audio"] = audio_wiedergabe
        override_config = True

    audio_record = config.get("cli_record_audio", False)
    if args.audio_record is not None:
        audio_record = args.audio_record
        config["cli_record_audio"] = audio_record
        override_config = True

    filter_regex = config.get("cli_filter_regex", "")
    if args.filter_regex is not None:
        filter_regex = args.filter_regex
        config["cli_filter_regex"] = filter_regex
        override_config = True

    selected_talkgroups = set()
    gespeicherte_talkgroups = config.get("selected_talkgroups", [])
    if isinstance(gespeicherte_talkgroups, list):
        selected_talkgroups.update(str(tg_id) for tg_id in gespeicherte_talkgroups)

    def _parse_talkgroup_tokens(tokens):
        ids = set()
        for token in filter(None, tokens):
            token = str(token).strip()
            if not token:
                continue
            found = extract_talkgroup_ids(token)
            if found:
                ids.update(found)
            else:
                for part in re.split(r"[,\s]+", token):
                    part = part.strip()
                    if part:
                        ids.add(part)
        return ids

    if args.talkgroup:
        selected_talkgroups = _parse_talkgroup_tokens(args.talkgroup)
        config["selected_talkgroups"] = sorted(selected_talkgroups)
        override_config = True

    if args.talkgroups_file:
        file_ids = set()
        try:
            with open(args.talkgroups_file, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    file_ids.update(_parse_talkgroup_tokens([line]))
        except OSError as exc:
            print(f"Warnung: Konnte Sprechgruppen-Datei nicht lesen: {exc}", file=sys.stderr)
        else:
            selected_talkgroups = file_ids
            config["selected_talkgroups"] = sorted(selected_talkgroups)
            override_config = True

    device_name = args.geraet_name if args.geraet_name is not None else config.get("cli_device_name")
    device_id = args.geraet_index if args.geraet_index is not None else config.get("cli_device_id")
    if isinstance(device_id, str) and device_id.strip().isdigit():
        device_id = int(device_id)
    if args.geraet_name is not None:
        config["cli_device_name"] = device_name
        override_config = True
    if args.geraet_index is not None:
        config["cli_device_id"] = device_id
        override_config = True

    device_name, device_id = _resolve_device(geraete, device_name, device_id)

    if override_config:
        save_config(config)

    app = QtCore.QCoreApplication([])

    class CLIRunner(QtCore.QObject):
        def __init__(
            self,
            device_name: str,
            device_id: int | None,
            ppm: int,
            gain_setting,
            freq_range_mhz: tuple[float, float],
            auto_decode: bool,
            play_audio: bool,
            record_audio: bool,
            filter_regex: str,
            selected_talkgroups: set[str],
            export_csv_path: str | None,
            stats_enabled: bool,
        ):
            super().__init__()
            self._device_name = device_name
            self._device_id = device_id
            self._scanner = SDRScanner(
                device=device_name,
                ppm=ppm,
                gain=gain_setting,
                parent=self,
            )
            self._decoder = TetraDecoder(ppm=ppm, parent=self)
            self._decoder.device_id = device_id
            self._scanner.device_id = device_id
            self._current_frequency = None
            self._last_peak = None
            self._last_spectrum = None
            self._freq_range_mhz = freq_range_mhz
            self._auto_decode = auto_decode
            self._play_audio = play_audio
            self._record_audio = record_audio
            self._filter_regex = filter_regex
            self.selected_talkgroups = selected_talkgroups
            self._export_csv_path = export_csv_path
            self._stats_enabled = stats_enabled
            self.cells = {}
            self.packet_counts = {}
            self.talkgroups = {}
            self._manual_lock = False
            self._stdin_thread = None
            self._dec_audio_player = None
            if self._play_audio:
                self._dec_audio_player = DecodedAudioPlayer(parent=self)
                self._decoder.audio.connect(self._dec_audio_player.process)

            self._scanner.spectrum_ready.connect(self._handle_spectrum)
            self._scanner.frequency_selected.connect(self._handle_frequency)
            self._decoder.output.connect(self._handle_decoder_output)
            self._decoder.finished.connect(self._decoder_finished)

        def start(self):
            start_hz = self._freq_range_mhz[0] * 1e6
            end_hz = self._freq_range_mhz[1] * 1e6
            self._scanner.start(start_hz, end_hz)
            self._start_cli_input_thread()

        def stop(self):
            self._scanner.stop()
            self._decoder.stop()
            if self._dec_audio_player:
                self._dec_audio_player.stop()

        def finalize(self):
            if self._export_csv_path:
                self.export_cells_csv(self._export_csv_path)
            if self._stats_enabled:
                self.print_stats()

        @QtCore.pyqtSlot(np.ndarray, np.ndarray)
        def _handle_spectrum(self, freqs, powers):
            if freqs is None or powers is None or len(freqs) == 0 or len(powers) == 0:
                return
            self._last_spectrum = (np.array(freqs, copy=True), np.array(powers, copy=True))
            max_idx = int(np.argmax(powers))
            freq = float(freqs[max_idx])
            power = float(powers[max_idx])
            self._last_peak = (freq, power)
            print(
                f"Frequenz {freq/1e6:.3f} MHz, Leistung {power:.1f} dB",
                flush=True,
            )

        @QtCore.pyqtSlot(float)
        def _handle_frequency(self, freq):
            if self._manual_lock:
                print(
                    f"Automatische Frequenz ignoriert (Manuell aktiv): {freq/1e6:.3f} MHz",
                    flush=True,
                )
                return
            if self._current_frequency and abs(freq - self._current_frequency) < 1:
                return
            self._set_frequency_and_process(freq, source="scan")

        def _set_frequency_and_process(self, freq: float, source: str = "manual"):
            self._current_frequency = freq
            if source == "manual":
                print(f"Manuell ausgewählt: {freq/1e6:.3f} MHz", flush=True)
            else:
                print(f"Gewählte Frequenz: {freq/1e6:.3f} MHz", flush=True)
            if not self._auto_decode:
                print(
                    f"Frequenz {freq/1e6:.3f} MHz erkannt (Auto-Dekodierung aus).",
                    flush=True,
                )
                return
            print(f"Starte Dekoder auf {freq/1e6:.3f} MHz", flush=True)
            self._decoder.stop()
            if self._dec_audio_player:
                self._dec_audio_player.start(record=self._record_audio)
            self._decoder.start(freq)

        @QtCore.pyqtSlot(str)
        def _handle_decoder_output(self, line: str):
            if not self._line_matches_selected_talkgroup(line):
                return
            if self._filter_regex:
                try:
                    if not re.search(self._filter_regex, line):
                        return
                except re.error:
                    pass
            print(line, flush=True)
            self.parse_cell_info(line)
            self.parse_packet_type(line)
            self.parse_talkgroups(line)
            for tg_id in extract_talkgroup_ids(line):
                print(f"Talkgroup {tg_id} empfangen", flush=True)

        def _line_matches_selected_talkgroup(self, line: str) -> bool:
            if not self.selected_talkgroups:
                return True
            ids = extract_talkgroup_ids(line)
            if not ids:
                return False
            return any(tg_id in self.selected_talkgroups for tg_id in ids)

        @QtCore.pyqtSlot()
        def _decoder_finished(self):
            print("Dekoder gestoppt.", flush=True)
            if self._dec_audio_player:
                self._dec_audio_player.stop()

        def _set_manual_lock(self, enabled: bool):
            self._manual_lock = enabled
            status = "Manuell" if enabled else "Automatisch"
            print(f"Modus gewechselt: {status}", flush=True)

        def _start_cli_input_thread(self):
            if self._stdin_thread and self._stdin_thread.is_alive():
                return
            self._stdin_thread = threading.Thread(
                target=self._cli_input_loop,
                daemon=True,
            )
            self._stdin_thread.start()

        def _cli_input_loop(self):
            while True:
                try:
                    line = sys.stdin.readline()
                except Exception:
                    break
                if not line:
                    break
                cmd = line.strip()
                if not cmd:
                    continue
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_handle_cli_command",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, cmd),
                )

        @QtCore.pyqtSlot(str)
        def _handle_cli_command(self, command: str):
            try:
                parts = shlex.split(command)
            except ValueError as exc:
                print(f"Ungültige Eingabe: {exc}", flush=True)
                return
            if not parts:
                return
            cmd = parts[0].lower()
            if cmd == "lock":
                self._set_manual_lock(True)
                return
            if cmd == "unlock":
                self._set_manual_lock(False)
                return
            if cmd == "freq":
                if len(parts) < 2:
                    print("Bitte eine Frequenz in MHz angeben: freq <MHz>", flush=True)
                    return
                try:
                    mhz = float(parts[1])
                except ValueError:
                    print("Ungültige Frequenz. Beispiel: freq 395.625", flush=True)
                    return
                self._set_manual_lock(True)
                self._set_frequency_and_process(mhz * 1e6, source="manual")
                return
            if cmd == "save-png":
                png_dir = None
                rest = parts[1:]
                for idx, arg in enumerate(rest):
                    if arg.startswith("--png-dir="):
                        png_dir = arg.split("=", 1)[1] or None
                        continue
                    if arg == "--png-dir":
                        if idx + 1 >= len(rest):
                            print("Bitte Verzeichnis nach --png-dir angeben.", flush=True)
                            return
                        png_dir = rest[idx + 1]
                self.save_spectrum_png(png_dir)
                return
            print(
                "Unbekannter Befehl. Verfügbar: lock, unlock, freq <MHz>, save-png [--png-dir <Pfad>]",
                flush=True,
            )

        def save_spectrum_png(self, png_dir: str | None = None):
            if not self._last_spectrum:
                print("Kein Spektrum zum Speichern vorhanden.", flush=True)
                return
            freqs, powers = self._last_spectrum
            ziel = png_dir or os.path.expanduser("~/TetraScans")
            os.makedirs(ziel, exist_ok=True)
            fname = datetime.now().strftime("scan_%Y%m%d_%H%M%S.png")
            fig = Figure(figsize=(8, 4))
            ax = fig.add_subplot(1, 1, 1)
            ax.plot(freqs / 1e6, powers, linewidth=1.0)
            ax.set_xlabel("Frequenz (MHz)")
            ax.set_ylabel("Leistung (dB)")
            ax.set_title("Spektrum")
            ax.grid(True, linestyle="--", alpha=0.4)
            fig.tight_layout()
            fig.savefig(os.path.join(ziel, fname))
            print(f"Spektrum gespeichert: {os.path.join(ziel, fname)}", flush=True)

        def export_cells_csv(self, path: str):
            try:
                with open(path, "w") as fh:
                    fh.write("Zelle,LAC,MCC,MNC,Frequenz\n")
                    for cell in self.cells.values():
                        fh.write(
                            f"{cell.get('cell','')},{cell.get('lac','')},"
                            f"{cell.get('mcc','')},{cell.get('mnc','')},{cell.get('freq','')}\n"
                        )
            except OSError as exc:
                print(f"Konnte CSV nicht schreiben: {exc}", file=sys.stderr, flush=True)
            else:
                print(f"CSV-Export abgeschlossen: {path}", flush=True)

        def print_stats(self):
            print("\nStatistik (CLI):", flush=True)
            print(f"- Zellen erkannt: {len(self.cells)}", flush=True)
            if self.packet_counts:
                paket_teile = ", ".join(
                    f"{typ}: {anzahl}"
                    for typ, anzahl in sorted(self.packet_counts.items())
                )
                print(f"- Pakettypen: {paket_teile}", flush=True)
            else:
                print("- Pakettypen: keine", flush=True)
            if self.talkgroups:
                print(f"- Sprechgruppen: {len(self.talkgroups)}", flush=True)
                haeufig = sorted(
                    self.talkgroups.items(),
                    key=lambda item: item[1].get("count", 0),
                    reverse=True,
                )[:5]
                if haeufig:
                    info = ", ".join(
                        f"{tg_id} ({werte.get('count', 0)})"
                        for tg_id, werte in haeufig
                    )
                    print(f"  Top 5: {info}", flush=True)
            else:
                print("- Sprechgruppen: keine", flush=True)

        def parse_cell_info(self, line: str):
            m = re.search(
                r"Cell\s*ID[:=]\s*(\w+).*LAC[:=]\s*(\w+).*MCC[:=]\s*(\d+).*MNC[:=]\s*(\d+)",
                line,
                re.I,
            )
            if not m:
                return
            freq_text = ""
            if self._current_frequency is not None:
                freq_text = f"{self._current_frequency/1e6:.3f}"
            cell = {
                "cell": m.group(1),
                "lac": m.group(2),
                "mcc": m.group(3),
                "mnc": m.group(4),
                "freq": freq_text,
            }
            self.cells[cell["cell"]] = cell

        def parse_packet_type(self, line: str):
            types = ["SDS", "MM", "CM"]
            for t in types:
                if t in line:
                    self.packet_counts[t] = self.packet_counts.get(t, 0) + 1
                    break

        def parse_talkgroups(self, line: str):
            ids = extract_talkgroup_ids(line)
            if not ids:
                return
            now = datetime.now()
            for tg_id in ids:
                info = self.talkgroups.get(tg_id, {"count": 0, "last_seen": now})
                info["count"] = info.get("count", 0) + 1
                info["last_seen"] = now
                self.talkgroups[tg_id] = info

    if device_id is None:
        device_text = "ohne Index"
    else:
        device_text = f"Index {device_id}"
    print(
        "CLI-Start mit Gerät "
        f"{device_text} ({device_name}), "
        f"PPM {ppm}, "
        f"Frequenzbereich {frequenzbereich[0]:.1f}-{frequenzbereich[1]:.1f} MHz, "
        f"Gain {_resolve_gain_value(gain_setting):.1f} dB, "
        f"Auto-Dekodierung {'an' if auto_dekodierung else 'aus'}, "
        f"Audio {'an' if audio_wiedergabe else 'aus'}"
        + (", Aufnahme an" if audio_record else ""),
        flush=True,
    )

    runner = CLIRunner(
        device_name,
        device_id,
        ppm,
        gain_setting,
        frequenzbereich,
        auto_dekodierung,
        audio_wiedergabe,
        audio_record,
        filter_regex,
        selected_talkgroups,
        args.export_csv,
        args.stats,
    )
    runner.start()
    try:
        while True:
            app.processEvents()
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nCLI-Modus beendet.")
        runner.stop()
        runner.finalize()


class SetupWorker(QtCore.QThread):
    """Prüft externe Werkzeuge und Python-Module und installiert sie."""

    log = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    REQUIRED_CMDS = {
        "receiver1": "osmocom-tetra",
        "demod_float": "osmocom-tetra",
        "tetra-rx": "osmocom-tetra",
        "rtl_power": "rtl-sdr",
        "rtl_fm": "rtl-sdr",
        "rtl_test": "rtl-sdr",
    }

    PY_MODULES = ["pyaudio", "numpy", "matplotlib", "PyQt5", "requests", "qdarkstyle"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._install_script_ran = False

    @classmethod
    def detect_missing_requirements(cls):
        """Gibt ein Tupel mit fehlenden Befehlen, Modulen und optionalen Werkzeugen zurück."""
        missing_cmds = [cmd for cmd in cls.REQUIRED_CMDS if not shutil.which(cmd)]
        missing_mods = [mod for mod in cls.PY_MODULES if not cls._has_module(mod)]
        missing_optional = []

        if sys.platform.startswith("win") and shutil.which("choco") and not shutil.which("zadig"):
            missing_optional.append("zadig")

        return missing_cmds, missing_mods, missing_optional

    @staticmethod
    def _has_module(name: str) -> bool:
        try:
            importlib.import_module(name)
            return True
        except Exception:
            return False

    def run(self):
        for cmd, pkg in self.REQUIRED_CMDS.items():
            if shutil.which(cmd):
                continue
            if self._run_install_script() and shutil.which(cmd):
                continue
            if sys.platform.startswith("linux"):
                self.log.emit(f"Installiere {cmd} über apt ({pkg})")
                self._run_cmd(["sudo", "apt-get", "install", "-y", pkg])
            elif sys.platform.startswith("win"):
                if pkg in ("rtl-sdr", "osmocom-tetra"):
                    if self._run_install_script() and shutil.which(cmd):
                        continue
                    self.log.emit(f"{cmd} fehlt - bitte {pkg} manuell installieren")
                elif shutil.which("choco"):
                    self.log.emit(f"Installiere {cmd} über choco ({pkg})")
                    self._run_cmd(["choco", "install", "-y", pkg])
                else:
                    self.log.emit(f"{cmd} fehlt - bitte {pkg} manuell installieren")
            else:
                self.log.emit(f"{cmd} fehlt - bitte {pkg} manuell installieren")

        for mod in self.PY_MODULES:
            if self._has_module(mod):
                continue
            if self._run_install_script() and self._has_module(mod):
                continue
            self.log.emit(f"Installiere Python-Modul {mod}")
            self._run_cmd([sys.executable, "-m", "pip", "install", mod])

        if sys.platform.startswith("win") and shutil.which("choco") and not shutil.which("zadig"):
            if self._run_install_script() and shutil.which("zadig"):
                pass
            else:
                self.log.emit("Installiere Zadig über choco")
                self._run_cmd(["choco", "install", "-y", "zadig"])

        setup_file = os.path.expanduser("~/.tetra_setup_done")
        try:
            with open(setup_file, "w"):
                pass
        except Exception:
            pass
        self.finished.emit()

    def _run_cmd(self, cmd):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                self.log.emit(line.rstrip())
            proc.wait()
        except Exception as exc:
            self.log.emit(f"Konnte {' '.join(cmd)} nicht ausführen: {exc}")

    def _run_install_script(self) -> bool:
        if self._install_script_ran:
            return False

        if sys.platform.startswith("linux"):
            script = os.path.join(PROJECT_ROOT, "install.sh")
            if not os.path.exists(script):
                return False
            self._install_script_ran = True
            self.log.emit("Starte install.sh, um fehlende Abhängigkeiten zu installieren...")
            self._run_cmd([script])
            return True

        if sys.platform.startswith("win"):
            script = os.path.join(PROJECT_ROOT, "install.ps1")
            if not os.path.exists(script):
                return False
            self._install_script_ran = True
            self.log.emit("Starte install.ps1, um fehlende Abhängigkeiten zu installieren...")
            self._run_cmd([
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script,
            ])
            return True

        return False



class SDRScanner(QtCore.QObject):
    """Scannt einen Frequenzbereich mit rtl_power und sendet Spektrumsdaten."""

    spectrum_ready = QtCore.pyqtSignal(np.ndarray, np.ndarray)
    frequency_selected = QtCore.pyqtSignal(float)

    def __init__(self, device: str, ppm: int = 0, gain=None, parent=None):
        super().__init__(parent)
        self.device = device
        self.device_id = None
        self.ppm = ppm
        self.gain = gain
        self._thread = None
        self._running = threading.Event()
        self._process = None

    def start(self, f_start=380e6, f_end=430e6, bin_size=10e3):
        """Startet den Scan mit rtl_power."""
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._scan,
                                         args=(f_start, f_end, bin_size),
                                         daemon=True)
        self._thread.start()

    def stop(self):
        self._running.clear()
        if self._process:
            self._process.terminate()
            self._process = None
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def _scan(self, f_start, f_end, bin_size):
        gain_value = _resolve_gain_value(self.gain)
        cmd = [
            "rtl_power",
            "-p", str(self.ppm),
            "-g", str(gain_value),
            f"-f{f_start/1e6:.0f}M:{f_end/1e6:.0f}M:{int(bin_size)}",
            "-i", "1", "-"
        ]
        if self.device_id is not None:
            cmd.extend(["-d", str(self.device_id)])
        try:
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL,
                                             text=True)
        except FileNotFoundError:
            # rtl_power nicht gefunden, Daten simulieren
            self._simulate_scan(f_start, f_end, bin_size)
            return

        while self._running.is_set():
            line = self._process.stdout.readline()
            if not line:
                break
            parts = line.strip().split(',')
            if len(parts) < 6:
                continue
            try:
                # rtl_power gibt Startfrequenz (parts[2]), Schrittweite (parts[4]) und Leistungswerte aus
                f0 = float(parts[2])
                bin_hz = float(parts[4])
                powers = np.array(list(map(float, parts[6:])))
            except ValueError:
                continue
            freqs = f0 + bin_hz * np.arange(len(powers))
            self.spectrum_ready.emit(freqs, powers)
            max_idx = np.argmax(powers)
            self.frequency_selected.emit(freqs[max_idx])

        if self._process:
            self._process.terminate()
            self._process = None

    def _simulate_scan(self, f_start, f_end, bin_size):
        freqs = np.arange(f_start, f_end, bin_size)
        while self._running.is_set():
            noise = np.random.normal(-80, 5, size=len(freqs))
            peak_idx = np.random.randint(0, len(freqs))
            noise[peak_idx] += 20
            self.spectrum_ready.emit(freqs, noise)
            self.frequency_selected.emit(freqs[peak_idx])
            QtCore.QThread.sleep(1)


class AudioPlayer(QtCore.QObject):
    """Empfängt Audio von rtl_fm und spielt es über PyAudio ab."""

    def __init__(self, device: str, ppm: int = 0, gain=None, parent=None):
        super().__init__(parent)
        self.device = device
        self.device_id = None
        self.ppm = ppm
        self.gain = gain
        self._process = None
        self._stream = None
        self._pa = pyaudio.PyAudio()
        self.agc_level = 10000
        self.activity_threshold = 1000
        self.record_file = None
        self.record_last = 0

    def start(self, frequency):
        self.stop()
        gain_value = _resolve_gain_value(self.gain)
        cmd = [
            "rtl_fm",
            "-p", str(self.ppm),
            "-g", str(gain_value),
            "-f", str(int(frequency)),
            "-s", "48000",
            "-"
        ]
        if self.device_id is not None:
            cmd.extend(["-d", str(self.device_id)])
        try:
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return

        self._stream = self._pa.open(format=pyaudio.paInt16,
                                     channels=1,
                                     rate=48000,
                                     output=True,
                                     frames_per_buffer=1024)

        threading.Thread(target=self._play, daemon=True).start()

    def stop(self):
        if self._process:
            self._process.terminate()
            self._process = None
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self.record_file:
            self.record_file.close()
            self.record_file = None

    def _play(self):
        if not self._process:
            return
        while True:
            data = self._process.stdout.read(2048)
            if not data:
                break
            # AGC anwenden
            audio = np.frombuffer(data, dtype=np.int16)
            level = np.max(np.abs(audio))
            if level > 0:
                gain = self.agc_level / level
                audio = (audio * gain).astype(np.int16)
            hat_aktivitaet = np.max(np.abs(audio)) > self.activity_threshold
            if hat_aktivitaet:
                QtCore.QMetaObject.invokeMethod(
                    self.parent(), "notify_activity", QtCore.Qt.QueuedConnection
                )
                self._start_recording()
            self._write_recording(audio)
            self._stream.write(audio.tobytes())

        self.stop()

    def _start_recording(self):
        if self.record_file:
            self.record_last = time.time()
            return
        path = os.path.expanduser("~/TetraRecordings")
        os.makedirs(path, exist_ok=True)
        fname = datetime.now().strftime("rec_%Y%m%d_%H%M%S.wav")
        self.record_file = wave.open(os.path.join(path, fname), "wb")
        self.record_file.setnchannels(1)
        self.record_file.setsampwidth(2)
        self.record_file.setframerate(48000)
        self.record_last = time.time()

    def _write_recording(self, audio):
        if self.record_file:
            self.record_file.writeframes(audio.tobytes())
            if time.time() - self.record_last > 2:
                self.record_file.close()
                self.record_file = None


class LEDIndicator(QtWidgets.QFrame):
    """Einfaches LED-Anzeige-Widget mit Farbe."""

    def __init__(self, size=20, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.set_color("green")

    def set_color(self, color: str):
        self.setStyleSheet(
            f"background-color: {color}; border-radius: {self._size // 2}px;"
        )


class DecodedAudioPlayer(QtCore.QObject):
    """Spielt dekodierte TETRA-Audioframes über PyAudio ab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self.record = False
        self._wav = None

    def start(self, record: bool = False):
        self.stop()
        self.record = record
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=8000,
            output=True,
            frames_per_buffer=1024,
        )
        if record:
            path = os.path.expanduser("~/TetraVoice")
            os.makedirs(path, exist_ok=True)
            name = datetime.now().strftime("voice_%Y%m%d_%H%M%S.wav")
            self._wav = wave.open(os.path.join(path, name), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(8000)

    def stop(self):
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._wav:
            self._wav.close()
            self._wav = None

    def process(self, data: bytes):
        if not self._stream:
            return
        self._stream.write(data)
        if self._wav:
            self._wav.writeframes(data)


class TetraDecoder(QtCore.QObject):
    """Startet osmocom-tetra-Werkzeuge und liefert dekodierte Ausgabe."""

    output = QtCore.pyqtSignal(str)
    audio = QtCore.pyqtSignal(bytes)
    encrypted = QtCore.pyqtSignal()
    finished = QtCore.pyqtSignal()

    def __init__(self, ppm: int = 0, parent=None):
        super().__init__(parent)
        self.ppm = ppm
        self.device_id = None
        self._thread = None
        self._running = threading.Event()
        self._procs = []
        self._audio_thread = None
        self._audio_path = None
        self._audio_mode = None

    def start(self, frequency: float):
        """Startet die Dekodierkette für die angegebene Frequenz."""
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, args=(frequency,), daemon=True)
        self._thread.start()

    def stop(self):
        """Stoppt die Dekodierung und beendet Kindprozesse."""
        self._running.clear()
        self._terminate_processes()
        if (
            self._audio_thread
            and self._audio_thread.is_alive()
            and threading.current_thread() is not self._audio_thread
        ):
            self._audio_thread.join(timeout=1)
        if (
            self._thread
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=1)
        self._thread = None
        self._audio_thread = None
        self._cleanup_audio_file()

    def _cleanup_audio_file(self):
        if self._audio_path:
            try:
                os.remove(self._audio_path)
            except OSError:
                pass
            self._audio_path = None
            self._audio_mode = None

    def _terminate_processes(self):
        for proc in self._procs:
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in self._procs:
            if not proc:
                continue
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
        self._procs = []

    def _run(self, frequency: float):
        receiver_cmd = ["receiver1", "-f", str(int(frequency)), "-p", str(self.ppm)]
        if self.device_id is not None:
            receiver_cmd.extend(["-d", str(self.device_id)])
        audio_enabled = True

        self._procs = []
        self._audio_thread = None
        p3 = None
        try:
            if audio_enabled:
                if not sys.platform.startswith("win") and hasattr(os, "mkfifo"):
                    self._audio_path = os.path.join(
                        tempfile.gettempdir(), f"tetra_audio_fifo_{os.getpid()}"
                    )
                    if os.path.exists(self._audio_path):
                        os.remove(self._audio_path)
                    os.mkfifo(self._audio_path)
                    self._audio_mode = "fifo"
                else:
                    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".raw")
                    self._audio_path = tmp_file.name
                    tmp_file.close()
                    self._audio_mode = "file"
                self.output.emit(
                    f"Audioausgabe aktiviert ({self._audio_mode}), Pfad: {self._audio_path}"
                )

            cmds = [
                receiver_cmd,
                ["demod_float"],
                ["tetra-rx"] + (["-a", self._audio_path] if audio_enabled else []),
            ]

            # Prüfen, ob alle Befehle vor dem Start vorhanden sind
            for cmd in cmds:
                if not shutil.which(cmd[0]):
                    self.output.emit(f"{cmd[0]} nicht im PATH gefunden")
                    self._running.clear()
                    self.finished.emit()
                    return
            p1 = subprocess.Popen(
                cmds[0],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._procs.append(p1)
            p2 = subprocess.Popen(
                cmds[1],
                stdin=p1.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._procs.append(p2)
            p1.stdout.close()
            p3 = subprocess.Popen(
                cmds[2],
                stdin=p2.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            p2.stdout.close()
            self._procs.append(p3)
            if audio_enabled:
                self._audio_thread = threading.Thread(target=self._read_audio, daemon=True)
                self._audio_thread.start()

            if p3 and p3.stdout:
                for line in p3.stdout:
                    if not self._running.is_set():
                        break
                    txt = line.rstrip()
                    self.output.emit(txt)
                    if "CACH" in txt or "LIP" in txt:
                        self.encrypted.emit()
        except Exception as exc:
            self.output.emit(f"Decoder konnte nicht gestartet werden: {exc}")
        finally:
            self._running.clear()
            self._terminate_processes()
            if (
                self._audio_thread
                and self._audio_thread.is_alive()
                and threading.current_thread() is not self._audio_thread
            ):
                self._audio_thread.join(timeout=1)
            self._audio_thread = None
            self._cleanup_audio_file()
            self.finished.emit()

    def _read_audio(self):
        try:
            while self._running.is_set():
                try:
                    if self._audio_mode == "fifo":
                        with open(self._audio_path, "rb", buffering=0) as fh:
                            while self._running.is_set():
                                data = fh.read(320)
                                if not data:
                                    time.sleep(0.05)
                                    break
                                self.audio.emit(data)
                    elif self._audio_mode == "file":
                        with open(self._audio_path, "rb", buffering=0) as fh:
                            pos = 0
                            while self._running.is_set():
                                try:
                                    size = os.path.getsize(self._audio_path)
                                except OSError:
                                    time.sleep(0.05)
                                    continue
                                if size - pos < 320:
                                    time.sleep(0.05)
                                    continue
                                fh.seek(pos)
                                data = fh.read(320)
                                pos = fh.tell()
                                if data:
                                    self.audio.emit(data)
                                else:
                                    time.sleep(0.05)
                    else:
                        time.sleep(0.05)
                except Exception:
                    time.sleep(0.05)
        finally:
            self._cleanup_audio_file()


class SpectrumCanvas(FigureCanvas):
    """Matplotlib-Canvas für die Spektrumsanzeige."""

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Frequenz [Hz]")
        self.ax.set_ylabel("Leistung [dB]")
        self.line, = self.ax.plot([], [])

    def update_spectrum(self, freqs, powers):
        self.line.set_data(freqs, powers)
        self.ax.relim()
        self.ax.autoscale_view()
        self.draw()


class MainWindow(QtWidgets.QMainWindow):
    """Hauptfenster der Anwendung."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SDR-Scanner")
        self.resize(900, 700)

        # Widgets, die in mehreren Tabs verwendet werden
        self.start_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay),
            "Starten",
        )
        self.stop_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaStop),
            "Stopp",
        )
        self.freq_label = QtWidgets.QLabel("Frequenz: k. A.")

        self.canvas = SpectrumCanvas()
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.freq_list = QtWidgets.QListWidget()

        self.activity_led = LEDIndicator()

        self.device_box = QtWidgets.QComboBox()
        self.refresh_devices()

        self.freq_range_box = QtWidgets.QComboBox()
        self.freq_range_box.addItem("380-385 MHz", (380e6, 385e6))
        self.freq_range_box.addItem("410-420 MHz", (410e6, 420e6))
        self.freq_range_box.addItem("420-430 MHz", (420e6, 430e6))

        self.agc_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.agc_slider.setRange(5000, 20000)
        self.agc_slider.setValue(10000)
        self.agc_value = QtWidgets.QLabel(str(self.agc_slider.value()))

        # Konfiguration muss während der Tab-Erstellung verfügbar sein
        self.config = {
            "theme": "light",
            "telegram_token": "",
            "telegram_chat": "",
            "scheduler_interval": 15,
            "scheduler_enabled": False,
            "ppm": 0,
            "gain": "max",
            "talkgroups": {},
            "selected_talkgroups": [],
        }
        self.config.update(load_config())
        self.config["gain"] = _normalize_gain_setting(self.config.get("gain", "max"))

        self.manual_lock = False

        self.tabs = QtWidgets.QTabWidget()
        self._build_tabs()

        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)
        lay.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.scanner = SDRScanner(
            device=self.device_box.currentText(),
            ppm=self.config.get("ppm", 0),
            gain=self.config.get("gain", "max"),
            parent=self,
        )
        self.player = AudioPlayer(
            device=self.device_box.currentText(),
            ppm=self.config.get("ppm", 0),
            gain=self.config.get("gain", "max"),
            parent=self,
        )
        self.decoder = TetraDecoder(ppm=self.config.get("ppm", 0), parent=self)
        self.dec_audio_player = DecodedAudioPlayer(parent=self)

        self.scheduler_timer = QtCore.QTimer(self)
        self.scheduler_timer.timeout.connect(self.run_scheduled_cycle)

        if self.config.get("theme") == "dark":
            self.apply_theme("dark")

        self.update_scheduler()

        self.agc_slider.valueChanged.connect(self._update_agc)
        self.ppm_spin.valueChanged.connect(self._update_ppm)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.freq_list.itemDoubleClicked.connect(self._select_frequency_from_list)
        self.scanner.spectrum_ready.connect(self.canvas.update_spectrum)
        self.scanner.spectrum_ready.connect(self._update_scan_results)
        self.scanner.frequency_selected.connect(self.update_frequency)

        self.decoder.output.connect(self._append_tetra)
        self.decoder.finished.connect(self._decoder_finished)
        self.decoder.audio.connect(self.dec_audio_player.process)
        self.decoder.encrypted.connect(self._encrypted_signal)

        self.tetra_start_btn.clicked.connect(self.start_decoding)
        self.tetra_stop_btn.clicked.connect(self.stop_decoding)
        self.play_audio_cb.toggled.connect(self._toggle_dec_audio)

        self.theme_combo.currentIndexChanged.connect(self._on_theme_change)
        self.scheduler_enable_cb.toggled.connect(self.update_scheduler)
        self.scheduler_interval_spin.valueChanged.connect(self.update_scheduler)
        self.export_cells_btn.clicked.connect(self.export_cells_csv)
        self.token_edit.textChanged.connect(lambda t: self.config.__setitem__("telegram_token", t))
        self.chat_edit.textChanged.connect(lambda t: self.config.__setitem__("telegram_chat", t))
        self.talkgroup_select_all_btn.clicked.connect(
            lambda: self._set_all_talkgroup_selection(True)
        )
        self.talkgroup_select_none_btn.clicked.connect(
            lambda: self._set_all_talkgroup_selection(False)
        )

        self._update_ppm(self.ppm_spin.value())

        self.freq_history = deque(maxlen=10)
        self.scan_results = {}
        self.current_frequency = None
        self.cells = {}
        self.packet_counts = {}
        self.talkgroups = {}
        self.selected_talkgroups = set()
        self._load_talkgroups_from_config()
        self._load_selected_talkgroups_from_config()
        self._update_talkgroups_table()

        self.talkgroup_table.itemChanged.connect(self._handle_talkgroup_selection_change)

        self.setup_worker = None
        missing_cmds, missing_mods, missing_optional = SetupWorker.detect_missing_requirements()
        if missing_cmds or missing_mods or missing_optional:
            self.log.appendPlainText("Starte automatische Pr\u00fcfung der Zusatzprogramme...")
            if missing_cmds:
                self.log.appendPlainText(
                    "Fehlende Programme: " + ", ".join(sorted(missing_cmds))
                )
            if missing_mods:
                self.log.appendPlainText(
                    "Fehlende Python-Module: " + ", ".join(sorted(missing_mods))
                )
            if missing_optional:
                self.log.appendPlainText(
                    "Fehlende Zusatzwerkzeuge: " + ", ".join(sorted(missing_optional))
                )

            self.setup_worker = SetupWorker()
            self.setup_worker.log.connect(self.log.appendPlainText)
            self.setup_worker.log.connect(logger.info)
            self.setup_worker.finished.connect(
                lambda: self.log.appendPlainText("Setup abgeschlossen")
            )
            self.setup_worker.start()
        else:
            self.log.appendPlainText(
                "Alle ben\u00f6tigten Zusatzprogramme wurden bereits gefunden."
            )

    def _build_tabs(self):
        """Erstellt die Haupt-Tabs inklusive TETRA-Dekodierung."""
        # Tab 1: Spektrum & Steuerung
        tab1 = QtWidgets.QWidget()
        ctl_layout = QtWidgets.QHBoxLayout()
        ctl_layout.addWidget(self.start_btn)
        ctl_layout.addWidget(self.stop_btn)
        ctl_layout.addWidget(self.freq_label)
        self.save_png_btn = QtWidgets.QPushButton("Spektrum als PNG speichern")
        ctl_layout.addWidget(self.save_png_btn)
        self.manual_lock_btn = QtWidgets.QPushButton("Modus: Automatisch")
        self.manual_lock_btn.setCheckable(True)
        ctl_layout.addWidget(self.manual_lock_btn)

        v1 = QtWidgets.QVBoxLayout(tab1)
        v1.addLayout(ctl_layout)
        v1.addWidget(self.canvas)
        v1.addWidget(self.log)
        v1.addWidget(QtWidgets.QLabel("Letzte Frequenzen:"))
        v1.addWidget(self.freq_list)
        self.save_png_btn.clicked.connect(self.save_spectrum_png)
        self.manual_lock_btn.toggled.connect(self._toggle_manual_lock)

        # Tab 2: Audio & Aktivität
        tab2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(tab2)
        h_led = QtWidgets.QHBoxLayout()
        h_led.addWidget(QtWidgets.QLabel("Aktivit\u00e4t:"))
        h_led.addWidget(self.activity_led)
        h_led.addStretch()
        v2.addLayout(h_led)
        self.play_audio_cb = QtWidgets.QCheckBox("Dekodiertes Audio wiedergeben")
        self.record_audio_cb = QtWidgets.QCheckBox("als WAV speichern")
        v2.addWidget(self.play_audio_cb)
        v2.addWidget(self.record_audio_cb)

        # Tab 3: Einstellungen
        tab3 = QtWidgets.QWidget()
        f3 = QtWidgets.QFormLayout(tab3)
        dev_layout = QtWidgets.QHBoxLayout()
        dev_layout.addWidget(self.device_box)
        refresh = QtWidgets.QPushButton("Neu suchen")
        refresh.clicked.connect(self.refresh_devices)
        dev_layout.addWidget(refresh)
        f3.addRow("Ger\u00e4t:", dev_layout)
        f3.addRow("Frequenzbereich:", self.freq_range_box)
        self.ppm_spin = QtWidgets.QSpinBox()
        self.ppm_spin.setRange(-100, 100)
        self.ppm_spin.setValue(self.config.get("ppm", 0))
        f3.addRow("PPM:", self.ppm_spin)
        agc_layout = QtWidgets.QHBoxLayout()
        agc_layout.addWidget(self.agc_slider)
        agc_layout.addWidget(self.agc_value)
        f3.addRow("AGC-Level:", agc_layout)

        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("Hell", "light")
        self.theme_combo.addItem("Dunkel", "dark")
        theme_value = self.config.get("theme", "light")
        theme_index = 0 if theme_value == "light" else 1
        self.theme_combo.setCurrentIndex(theme_index)
        f3.addRow("Design:", self.theme_combo)

        self.scheduler_enable_cb = QtWidgets.QCheckBox("Scheduler aktiv")
        self.scheduler_enable_cb.setChecked(self.config.get("scheduler_enabled", False))
        self.scheduler_interval_spin = QtWidgets.QSpinBox()
        self.scheduler_interval_spin.setRange(1, 1440)
        self.scheduler_interval_spin.setValue(self.config.get("scheduler_interval", 15))
        sch_lay = QtWidgets.QHBoxLayout()
        sch_lay.addWidget(self.scheduler_enable_cb)
        sch_lay.addWidget(QtWidgets.QLabel("Intervall (min):"))
        sch_lay.addWidget(self.scheduler_interval_spin)
        f3.addRow("Scheduler:", sch_lay)

        self.token_edit = QtWidgets.QLineEdit(self.config.get("telegram_token", ""))
        self.chat_edit = QtWidgets.QLineEdit(self.config.get("telegram_chat", ""))
        f3.addRow("Telegram Token:", self.token_edit)
        f3.addRow("Chat-ID:", self.chat_edit)

        # Tab 4: TETRA-Dekodierung
        tab4 = QtWidgets.QWidget()
        v4 = QtWidgets.QVBoxLayout(tab4)
        ctl4 = QtWidgets.QHBoxLayout()
        self.tetra_start_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay),
            "Dekodierung starten",
        )
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaStop),
            "Stopp",
        )
        self.tetra_stop_btn.setEnabled(False)
        self.tetra_auto_cb = QtWidgets.QCheckBox("Automatisch nach Scan")
        ctl4.addWidget(self.tetra_start_btn)
        ctl4.addWidget(self.tetra_stop_btn)
        ctl4.addWidget(self.tetra_auto_cb)
        ctl4.addStretch()
        v4.addLayout(ctl4)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Regex-Filter")
        v4.addWidget(self.filter_edit)
        self.tetra_output = QtWidgets.QPlainTextEdit()
        self.tetra_output.setReadOnly(True)
        v4.addWidget(self.tetra_output)

        # Tab 5: Zellen
        tab5 = QtWidgets.QWidget()
        v5 = QtWidgets.QVBoxLayout(tab5)
        self.cell_table = QtWidgets.QTableWidget(0, 5)
        self.cell_table.setHorizontalHeaderLabels(
            ["Zell-ID", "LAC", "MCC", "MNC", "Frequenz"]
        )
        v5.addWidget(self.cell_table)
        self.export_cells_btn = QtWidgets.QPushButton("CSV-Export")
        v5.addWidget(self.export_cells_btn)

        # Tab 6: Paketstatistik
        tab6 = QtWidgets.QWidget()
        v6 = QtWidgets.QVBoxLayout(tab6)
        self.stats_canvas = FigureCanvas(Figure(figsize=(4,3)))
        self.stats_ax = self.stats_canvas.figure.add_subplot(111)
        v6.addWidget(self.stats_canvas)

        # Tab 7: Sprechgruppen
        tab7 = QtWidgets.QWidget()
        v7 = QtWidgets.QVBoxLayout(tab7)
        self.talkgroup_table = QtWidgets.QTableWidget(0, 4)
        self.talkgroup_table.setHorizontalHeaderLabels(
            ["Auswahl", "TG-ID", "Treffer", "Letzte Aktivität"]
        )
        self.talkgroup_table.horizontalHeader().setStretchLastSection(True)
        self.talkgroup_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents
        )
        self.talkgroup_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )
        self.talkgroup_table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents
        )
        auswahl_layout = QtWidgets.QHBoxLayout()
        self.talkgroup_select_all_btn = QtWidgets.QPushButton("Alle auswählen")
        self.talkgroup_select_none_btn = QtWidgets.QPushButton("Alle abwählen")
        auswahl_layout.addWidget(self.talkgroup_select_all_btn)
        auswahl_layout.addWidget(self.talkgroup_select_none_btn)
        auswahl_layout.addStretch()
        v7.addLayout(auswahl_layout)
        v7.addWidget(self.talkgroup_table)

        self.tabs.addTab(tab1, "Spektrum & Steuerung")
        self.tabs.addTab(tab2, "Audio & Aktivit\u00e4t")
        self.tabs.addTab(tab3, "Einstellungen")
        self.tabs.addTab(tab4, "TETRA-Dekodierung")
        self.tabs.addTab(tab5, "Zellen")
        self.tabs.addTab(tab6, "Statistik")
        self.tabs.addTab(tab7, "Sprechgruppen")

    def refresh_devices(self):
        """Füllt die Geräteauswahl mit erkannten SDR-Geräten."""
        self.device_box.clear()
        for label, device_id in list_sdr_devices():
            self.device_box.addItem(label, device_id)

    def _current_device_info(self):
        name = self.device_box.currentText()
        device_id = self.device_box.currentData()
        if isinstance(device_id, str) and device_id.strip().isdigit():
            device_id = int(device_id)
        if isinstance(device_id, int):
            return name, device_id
        return name, None

    def _update_agc(self, value):
        """Aktualisiert den AGC-Pegel aus dem Schieberegler."""
        self.agc_value.setText(str(value))
        self.player.agc_level = value

    def _update_ppm(self, value: int):
        """Aktualisiert die PPM-Korrektur für alle SDR-Befehle."""
        self.config["ppm"] = value
        self.scanner.ppm = value
        self.player.ppm = value
        self.decoder.ppm = value

    @QtCore.pyqtSlot(np.ndarray, np.ndarray)
    def _update_scan_results(self, freqs, powers):
        """Aggregiert Scan-Peaks und aktualisiert die Frequenzliste."""
        if freqs is None or powers is None or len(freqs) == 0 or len(powers) == 0:
            return

        bin_hz = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0
        if bin_hz <= 0:
            return

        bin_indices = np.rint(freqs / bin_hz).astype(int)
        for idx, freq, power in zip(bin_indices, freqs, powers):
            current = self.scan_results.get(idx)
            if current is None or power > current["power"]:
                self.scan_results[idx] = {"freq": freq, "power": power}

        if len(self.scan_results) > 200:
            top_items = sorted(
                self.scan_results.items(),
                key=lambda item: item[1]["power"],
                reverse=True,
            )[:200]
            self.scan_results = dict(top_items)

        top_peaks = sorted(
            self.scan_results.values(),
            key=lambda item: item["power"],
            reverse=True,
        )[:20]

        self.freq_list.clear()
        for entry in top_peaks:
            freq_mhz = entry["freq"] / 1e6
            text = f"{freq_mhz:.3f} MHz \u2013 {entry['power']:.1f} dB"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, entry["freq"])
            self.freq_list.addItem(item)

    @QtCore.pyqtSlot(float)
    def update_frequency(self, freq):
        """Neue Frequenzauswahl verarbeiten."""
        if self.manual_lock:
            self.log.appendPlainText(
                f"Automatische Frequenz ignoriert (Manuell aktiv): {freq/1e6:.3f} MHz"
            )
            self.freq_history.appendleft(freq / 1e6)
            return
        self._set_frequency_and_process(freq, source="scan")

    @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def _select_frequency_from_list(self, item):
        """Frequenz aus der Liste ausw\u00e4hlen und manuell tunen."""
        freq = item.data(QtCore.Qt.UserRole)
        if not freq:
            return
        self._set_manual_lock(True)
        self._set_frequency_and_process(freq, source="manual")

    def _set_frequency_and_process(self, freq, source="manual"):
        """Gemeinsamer Einstieg zum Setzen der Frequenz und Starten des Players."""
        self.freq_label.setText(f"Frequenz: {freq/1e6:.3f} MHz")
        if source == "manual":
            self.log.appendPlainText(f"Manuell ausgew\u00e4hlt: {freq/1e6:.3f} MHz")
        else:
            self.log.appendPlainText(f"Gew\u00e4hlte Frequenz: {freq/1e6:.3f} MHz")
        self.freq_history.appendleft(freq / 1e6)
        self.current_frequency = freq
        self.player.start(freq)
        self.tetra_start_btn.setEnabled(True)
        if self.tetra_auto_cb.isChecked():
            self.start_decoding()

    def _set_manual_lock(self, enabled: bool):
        self.manual_lock = enabled
        if self.manual_lock_btn.isChecked() != enabled:
            self.manual_lock_btn.blockSignals(True)
            self.manual_lock_btn.setChecked(enabled)
            self.manual_lock_btn.blockSignals(False)
        status = "Manuell" if enabled else "Automatisch"
        self.manual_lock_btn.setText(f"Modus: {status}")
        self.log.appendPlainText(f"Modus gewechselt: {status}")

    def _toggle_manual_lock(self, enabled: bool):
        self._set_manual_lock(enabled)

    @QtCore.pyqtSlot()
    def notify_activity(self):
        """Visuelle Anzeige, wenn Aktivität erkannt wird."""
        self.activity_led.set_color("red")
        QtCore.QTimer.singleShot(500, lambda: self.activity_led.set_color("green"))

    def start_decoding(self):
        """Startet die TETRA-Dekodierkette."""
        if self.current_frequency is None:
            return
        name, device_id = self._current_device_info()
        self._update_ppm(self.ppm_spin.value())
        self.decoder.device_id = device_id
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn.setEnabled(True)
        self.tetra_output.clear()
        rec = self.record_audio_cb.isChecked()
        if self.play_audio_cb.isChecked():
            self.dec_audio_player.start(record=rec)
        if device_id is None:
            device_text = "ohne Index"
        else:
            device_text = f"Index {device_id}"
        self.log.appendPlainText(
            f"Dekodierung gestartet mit Gerät {device_text} ({name}) "
            f"bei {self.current_frequency/1e6:.3f} MHz"
        )
        self.decoder.start(self.current_frequency)

    def stop_decoding(self):
        """Stoppt die TETRA-Dekodierung."""
        self.decoder.stop()
        self.dec_audio_player.stop()

    def _toggle_dec_audio(self, enabled: bool):
        if enabled and self.decoder._running.is_set():
            self.dec_audio_player.start(record=self.record_audio_cb.isChecked())
        else:
            self.dec_audio_player.stop()

    def _encrypted_signal(self):
        self.dec_audio_player.stop()
        QtWidgets.QMessageBox.information(self, "Info", "Verschl\u00fcsseltes Signal erkannt")

    def _append_tetra(self, line: str):
        if not self._line_matches_selected_talkgroup(line):
            return
        flt = self.filter_edit.text()
        if flt:
            try:
                if not re.search(flt, line):
                    return
            except re.error:
                pass
        self.tetra_output.appendPlainText(line)
        logger.info(line)
        self.parse_cell_info(line)
        self.parse_packet_type(line)
        self.parse_talkgroups(line)

    def _decoder_finished(self):
        self.tetra_start_btn.setEnabled(True)
        self.tetra_stop_btn.setEnabled(False)
        self.dec_audio_player.stop()

    def start(self):
        name, device_id = self._current_device_info()
        self.scanner.device = name
        self.player.device = name
        self.scanner.device_id = device_id
        self.player.device_id = device_id
        gain_setting = _normalize_gain_setting(self.config.get("gain", "max"))
        self.config["gain"] = gain_setting
        self.scanner.gain = gain_setting
        self.player.gain = gain_setting
        self.decoder.device_id = device_id
        self._update_ppm(self.ppm_spin.value())
        rng = self.freq_range_box.currentData()
        f_start, f_end = rng if rng else (380e6, 430e6)
        if device_id is None:
            device_text = "ohne Index"
        else:
            device_text = f"Index {device_id}"
        self.log.appendPlainText(
            f"Scan gestartet mit Gerät {device_text} ({name}) "
            f"({f_start/1e6:.0f}-{f_end/1e6:.0f} MHz)"
        )
        self.scanner.start(f_start, f_end)

    def stop(self):
        self.log.appendPlainText("Stoppe")
        self.scanner.stop()
        self.player.stop()
        self.stop_decoding()

    def closeEvent(self, event):
        self._persist_talkgroups_to_config()
        self._persist_selected_talkgroups_to_config()
        save_config(self.config)
        super().closeEvent(event)

    # ----- Hilfsmethoden -----
    def apply_theme(self, theme: str):
        if theme == "dark" and qdarkstyle:
            self.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        else:
            self.setStyleSheet("")
        self.config["theme"] = theme

    def _on_theme_change(self, index: int):
        theme_value = self.theme_combo.itemData(index) or "light"
        self.apply_theme(theme_value)

    def save_spectrum_png(self):
        path = os.path.expanduser("~/TetraScans")
        os.makedirs(path, exist_ok=True)
        fname = datetime.now().strftime("scan_%Y%m%d_%H%M%S.png")
        self.canvas.fig.savefig(os.path.join(path, fname))
        self.log.appendPlainText(f"Spektrum gespeichert: {fname}")

    def run_scheduled_cycle(self):
        self.start()
        QtCore.QTimer.singleShot(5000, self._run_decode_phase)

    def _run_decode_phase(self):
        self.scanner.stop()
        if self.current_frequency:
            self.start_decoding()
        QtCore.QTimer.singleShot(60000, self.stop)

    def send_telegram(self, text: str):
        token = self.token_edit.text().strip()
        chat = self.chat_edit.text().strip()
        if not token or not chat or not requests:
            return
        threading.Thread(
            target=requests.post,
            args=(f"https://api.telegram.org/bot{token}/sendMessage",),
            kwargs={"data": {"chat_id": chat, "text": text}},
            daemon=True,
        ).start()

    def update_cells(self, cell):
        cid = cell.get("cell")
        if not cid:
            return
        self.cells[cid] = cell
        self.cell_table.setRowCount(len(self.cells))
        for row, info in enumerate(self.cells.values()):
            self.cell_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(info.get("cell", ""))))
            self.cell_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(info.get("lac", ""))))
            self.cell_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(info.get("mcc", ""))))
            self.cell_table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(info.get("mnc", ""))))
            self.cell_table.setItem(row, 4, QtWidgets.QTableWidgetItem(str(info.get("freq", ""))))

    def update_stats(self):
        self.stats_ax.clear()
        types = list(self.packet_counts.keys())
        vals = [self.packet_counts[t] for t in types]
        self.stats_ax.bar(types, vals)
        self.stats_canvas.draw()

    def export_cells_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "CSV speichern",
            "cells.csv",
            "CSV-Dateien (*.csv)",
        )
        if not path:
            return
        with open(path, "w") as fh:
            fh.write("Zelle,LAC,MCC,MNC,Frequenz\n")
            for c in self.cells.values():
                fh.write(
                    f"{c.get('cell','')},{c.get('lac','')},"
                    f"{c.get('mcc','')},{c.get('mnc','')},{c.get('freq','')}\n"
                )

    def update_scheduler(self):
        enabled = self.scheduler_enable_cb.isChecked()
        interval = self.scheduler_interval_spin.value()
        self.config["scheduler_enabled"] = enabled
        self.config["scheduler_interval"] = interval
        if enabled:
            self.scheduler_timer.start(interval * 60 * 1000)
        else:
            self.scheduler_timer.stop()

    def parse_cell_info(self, line: str):
        m = re.search(r"Cell\s*ID[:=]\s*(\w+).*LAC[:=]\s*(\w+).*MCC[:=]\s*(\d+).*MNC[:=]\s*(\d+)", line, re.I)
        if not m:
            return
        cell = {
            "cell": m.group(1),
            "lac": m.group(2),
            "mcc": m.group(3),
            "mnc": m.group(4),
            "freq": f"{self.current_frequency/1e6:.3f}"
        }
        self.update_cells(cell)

    def parse_packet_type(self, line: str):
        types = ["SDS", "MM", "CM"]
        for t in types:
            if t in line:
                self.packet_counts[t] = self.packet_counts.get(t, 0) + 1
                self.update_stats()
                self.send_telegram(
                    f"TETRA-Aktivit\u00e4t auf {self.current_frequency/1e6:.4f} MHz: {t} empfangen"
                )
                break

    def parse_talkgroups(self, line: str):
        ids = self._extract_talkgroup_ids(line)
        if not ids:
            return
        now = datetime.now()
        for tg_id in ids:
            info = self.talkgroups.get(tg_id, {"count": 0, "last_seen": now})
            info["count"] = info.get("count", 0) + 1
            info["last_seen"] = now
            self.talkgroups[tg_id] = info
        self._update_talkgroups_table()

    def _extract_talkgroup_ids(self, line: str):
        return extract_talkgroup_ids(line)

    def _update_talkgroups_table(self):
        if not hasattr(self, "talkgroup_table"):
            return
        sortiert = sorted(
            self.talkgroups.items(),
            key=lambda item: item[1].get("last_seen") or datetime.min,
            reverse=True,
        )
        self.talkgroup_table.blockSignals(True)
        self.talkgroup_table.setRowCount(len(sortiert))
        for row, (tg_id, info) in enumerate(sortiert):
            count = info.get("count", 0)
            last_seen = info.get("last_seen")
            last_text = last_seen.strftime("%Y-%m-%d %H:%M:%S") if last_seen else ""
            auswahl_item = QtWidgets.QTableWidgetItem("")
            auswahl_item.setFlags(
                auswahl_item.flags() | QtCore.Qt.ItemIsUserCheckable
            )
            auswahl_item.setCheckState(
                QtCore.Qt.Checked
                if str(tg_id) in self.selected_talkgroups
                else QtCore.Qt.Unchecked
            )
            self.talkgroup_table.setItem(row, 0, auswahl_item)
            self.talkgroup_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(tg_id)))
            self.talkgroup_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(count)))
            self.talkgroup_table.setItem(row, 3, QtWidgets.QTableWidgetItem(last_text))
        self.talkgroup_table.blockSignals(False)

    def _handle_talkgroup_selection_change(self, item: QtWidgets.QTableWidgetItem):
        if item.column() != 0:
            return
        tg_item = self.talkgroup_table.item(item.row(), 1)
        if not tg_item:
            return
        tg_id = str(tg_item.text()).strip()
        if not tg_id:
            return
        if item.checkState() == QtCore.Qt.Checked:
            self.selected_talkgroups.add(tg_id)
        else:
            self.selected_talkgroups.discard(tg_id)
        self._persist_selected_talkgroups_to_config()

    def _set_all_talkgroup_selection(self, selected: bool):
        ids = {str(tg_id) for tg_id in self.talkgroups.keys()}
        if selected:
            self.selected_talkgroups = ids
        else:
            self.selected_talkgroups = set()
        self._persist_selected_talkgroups_to_config()
        self._update_talkgroups_table()

    def _line_matches_selected_talkgroup(self, line: str) -> bool:
        if not self.selected_talkgroups:
            return True
        ids = self._extract_talkgroup_ids(line)
        if not ids:
            return False
        return any(tg_id in self.selected_talkgroups for tg_id in ids)

    def _load_talkgroups_from_config(self):
        gespeicherte = self.config.get("talkgroups", {})
        if not isinstance(gespeicherte, dict):
            return
        for tg_id, info in gespeicherte.items():
            if not isinstance(info, dict):
                continue
            last_seen = info.get("last_seen")
            parsed_last = None
            if isinstance(last_seen, str):
                try:
                    parsed_last = datetime.fromisoformat(last_seen)
                except ValueError:
                    parsed_last = None
            self.talkgroups[str(tg_id)] = {
                "count": int(info.get("count", 0)),
                "last_seen": parsed_last,
            }

    def _load_selected_talkgroups_from_config(self):
        gespeicherte = self.config.get("selected_talkgroups", [])
        if isinstance(gespeicherte, list):
            self.selected_talkgroups = {str(tg_id) for tg_id in gespeicherte}
        else:
            self.selected_talkgroups = set()

    def _persist_talkgroups_to_config(self):
        gespeicherte = {}
        for tg_id, info in self.talkgroups.items():
            last_seen = info.get("last_seen")
            gespeicherte[str(tg_id)] = {
                "count": int(info.get("count", 0)),
                "last_seen": last_seen.isoformat() if last_seen else "",
            }
        self.config["talkgroups"] = gespeicherte

    def _persist_selected_talkgroups_to_config(self):
        self.config["selected_talkgroups"] = sorted(self.selected_talkgroups)


if __name__ == "__main__":
    if not _qt_xcb_verfuegbar():
        _starte_cli_modus(
            "Qt-Plugin 'xcb' nicht gefunden. Bitte installiere die fehlenden "
            "System-Pakete für X11/Qt-xcb (z. B. libxcb, libxkbcommon-x11) oder "
            "starte das Programm in einer Umgebung mit grafischer Oberfläche. "
            "Alternativ kannst du 'QT_QPA_PLATFORM=offscreen' setzen, wenn eine "
            "headless Ausführung gewünscht ist."
        )
        raise SystemExit(0)

    try:
        app = QtWidgets.QApplication(sys.argv)
    except Exception as exc:
        _starte_cli_modus(
            "Qt konnte nicht gestartet werden. Bitte prüfe, ob die X11/Qt-xcb "
            "System-Pakete installiert sind oder ob du dich in einer headless "
            "Umgebung befindest. Fehlerdetails: "
            f"{exc}"
        )
        raise SystemExit(0)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
