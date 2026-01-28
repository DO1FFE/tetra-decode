import os
import sys
import subprocess
import threading
import shutil
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
try:
    import qdarkstyle
except Exception:
    qdarkstyle = None

try:
    import requests
except Exception:
    requests = None

import numpy as np
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
    """Return a list of detected RTL-SDR devices."""
    devices = []
    try:
        out = subprocess.check_output(["rtl_test", "-t"], text=True,
                                      stderr=subprocess.STDOUT, timeout=5)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("0:") or line.startswith("1:"):
                devices.append(line)
    except Exception:
        pass
    if not devices:
        try:
            out = subprocess.check_output(["lsusb"], text=True, timeout=5)
            for line in out.splitlines():
                if "RTL" in line or "Realtek" in line:
                    devices.append(line.strip())
        except Exception:
            pass
    return devices or ["RTL-SDR"]


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


class SetupWorker(QtCore.QThread):
    """Check for external tools and python modules and install them."""

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
        """Return a tuple with missing commands, modules and optional tools."""
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
                self.log.emit(f"Installing {cmd} via apt ({pkg})")
                self._run_cmd(["sudo", "apt-get", "install", "-y", pkg])
            elif sys.platform.startswith("win"):
                if pkg in ("rtl-sdr", "osmocom-tetra"):
                    if self._run_install_script() and shutil.which(cmd):
                        continue
                    self.log.emit(f"{cmd} missing - please install {pkg} manually")
                elif shutil.which("choco"):
                    self.log.emit(f"Installing {cmd} via choco ({pkg})")
                    self._run_cmd(["choco", "install", "-y", pkg])
                else:
                    self.log.emit(f"{cmd} missing - please install {pkg} manually")
            else:
                self.log.emit(f"{cmd} missing - please install {pkg} manually")

        for mod in self.PY_MODULES:
            if self._has_module(mod):
                continue
            if self._run_install_script() and self._has_module(mod):
                continue
            self.log.emit(f"Installing python module {mod}")
            self._run_cmd([sys.executable, "-m", "pip", "install", mod])

        if sys.platform.startswith("win") and shutil.which("choco") and not shutil.which("zadig"):
            if self._run_install_script() and shutil.which("zadig"):
                pass
            else:
                self.log.emit("Installing Zadig via choco")
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
            self.log.emit(f"Failed to run {' '.join(cmd)}: {exc}")

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
    """Scan a frequency range using rtl_power and emit spectrum data."""

    spectrum_ready = QtCore.pyqtSignal(np.ndarray, np.ndarray)
    frequency_selected = QtCore.pyqtSignal(float)

    def __init__(self, device: str, ppm: int = 0, parent=None):
        super().__init__(parent)
        self.device = device
        self.ppm = ppm
        self._thread = None
        self._running = threading.Event()
        self._process = None

    def start(self, f_start=380e6, f_end=430e6, bin_size=10e3):
        """Start scanning using rtl_power."""
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
        cmd = [
            "rtl_power",
            "-p", str(self.ppm),
            f"-f{f_start/1e6:.0f}M:{f_end/1e6:.0f}M:{int(bin_size)}",
            "-i", "1", "-"
        ]
        try:
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL,
                                             text=True)
        except FileNotFoundError:
            # rtl_power not found, simulate data
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
                # rtl_power prints freq start, bin size, <power values>
                f0 = float(parts[2])
                bin_hz = float(parts[3])
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
    """Receive audio from rtl_fm and play it via PyAudio."""

    def __init__(self, device: str, ppm: int = 0, parent=None):
        super().__init__(parent)
        self.device = device
        self.ppm = ppm
        self._process = None
        self._stream = None
        self._pa = pyaudio.PyAudio()
        self.agc_level = 10000
        self.activity_threshold = 1000
        self.activity = QtCore.pyqtSignal()
        self.record_file = None
        self.record_last = 0

    def start(self, frequency):
        self.stop()
        cmd = [
            "rtl_fm",
            "-p", str(self.ppm),
            "-f", str(int(frequency)),
            "-s", "48000",
            "-"
        ]
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
            # apply AGC
            audio = np.frombuffer(data, dtype=np.int16)
            level = np.max(np.abs(audio))
            if level > 0:
                gain = self.agc_level / level
                audio = (audio * gain).astype(np.int16)
            if np.max(np.abs(audio)) > self.activity_threshold:
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
            else:
                self.record_last = time.time()


class LEDIndicator(QtWidgets.QFrame):
    """Simple colored LED indicator widget."""

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
    """Play decoded TETRA audio frames via PyAudio."""

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
    """Run osmocom-tetra tools and emit decoded output."""

    output = QtCore.pyqtSignal(str)
    audio = QtCore.pyqtSignal(bytes)
    encrypted = QtCore.pyqtSignal()
    finished = QtCore.pyqtSignal()

    def __init__(self, ppm: int = 0, parent=None):
        super().__init__(parent)
        self.ppm = ppm
        self._thread = None
        self._running = threading.Event()
        self._procs = []
        self._audio_thread = None
        self._fifo = os.path.join(tempfile.gettempdir(), "tetra_audio_fifo")
        if os.name == "nt":
            self._fifo += f"_{os.getpid()}.raw"

    def start(self, frequency: float):
        """Start decoding pipeline for the given frequency."""
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, args=(frequency,), daemon=True)
        self._thread.start()

    def stop(self):
        """Stop decoding and terminate child processes."""
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
        cmds = [
            ["receiver1", "-f", str(int(frequency)), "-p", str(self.ppm)],
            ["demod_float"],
            ["tetra-rx", "-a", self._fifo],
        ]

        # Check all commands exist before starting
        for cmd in cmds:
            if not shutil.which(cmd[0]):
                self.output.emit(f"{cmd[0]} not found in PATH")
                self._running.clear()
                self.finished.emit()
                return

        self._procs = []
        self._audio_thread = None
        p3 = None
        try:
            if os.path.exists(self._fifo):
                os.remove(self._fifo)
            if hasattr(os, "mkfifo"):
                os.mkfifo(self._fifo)
            else:
                open(self._fifo, "wb").close()
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
            self.output.emit(f"Failed to start decoder: {exc}")
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
            self.finished.emit()

    def _read_audio(self):
        try:
            with open(self._fifo, "rb") as fh:
                while self._running.is_set():
                    data = fh.read(320)
                    if not data:
                        time.sleep(0.05)
                        continue
                    self.audio.emit(data)
        except Exception:
            pass
        finally:
            if os.path.exists(self._fifo):
                os.remove(self._fifo)


class SpectrumCanvas(FigureCanvas):
    """Matplotlib canvas for spectrum display."""

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Frequency [Hz]")
        self.ax.set_ylabel("Power [dB]")
        self.line, = self.ax.plot([], [])

    def update_spectrum(self, freqs, powers):
        self.line.set_data(freqs, powers)
        self.ax.relim()
        self.ax.autoscale_view()
        self.draw()


class MainWindow(QtWidgets.QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SDR Scanner")
        self.resize(900, 700)

        # Widgets common to multiple tabs
        self.start_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay),
            "Start",
        )
        self.stop_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaStop),
            "Stop",
        )
        self.freq_label = QtWidgets.QLabel("Freq: N/A")

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

        # configuration needs to be available during tab creation
        self.config = {
            "theme": "light",
            "telegram_token": "",
            "telegram_chat": "",
            "scheduler_interval": 15,
            "scheduler_enabled": False,
            "ppm": 0,
            "talkgroups": {},
            "selected_talkgroups": [],
        }
        self.config.update(load_config())

        self.tabs = QtWidgets.QTabWidget()
        self._build_tabs()

        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)
        lay.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.scanner = SDRScanner(device=self.device_box.currentText(), ppm=self.config.get("ppm", 0), parent=self)
        self.player = AudioPlayer(device=self.device_box.currentText(), ppm=self.config.get("ppm", 0), parent=self)
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

        self.theme_combo.currentTextChanged.connect(self.apply_theme)
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
        """Create the main tabs, including TETRA decoding."""
        # Tab 1: Spectrum & Control
        tab1 = QtWidgets.QWidget()
        ctl_layout = QtWidgets.QHBoxLayout()
        ctl_layout.addWidget(self.start_btn)
        ctl_layout.addWidget(self.stop_btn)
        ctl_layout.addWidget(self.freq_label)
        self.save_png_btn = QtWidgets.QPushButton("Spektrum als PNG speichern")
        ctl_layout.addWidget(self.save_png_btn)

        v1 = QtWidgets.QVBoxLayout(tab1)
        v1.addLayout(ctl_layout)
        v1.addWidget(self.canvas)
        v1.addWidget(self.log)
        v1.addWidget(QtWidgets.QLabel("Letzte Frequenzen:"))
        v1.addWidget(self.freq_list)
        self.save_png_btn.clicked.connect(self.save_spectrum_png)

        # Tab 2: Audio & Activity
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

        # Tab 3: Settings
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
        self.theme_combo.addItems(["light", "dark"])
        self.theme_combo.setCurrentText(self.config.get("theme", "light"))
        f3.addRow("Theme:", self.theme_combo)

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

        # Tab 4: TETRA decoding
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
            "Stop",
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

        # Tab 5: Cells
        tab5 = QtWidgets.QWidget()
        v5 = QtWidgets.QVBoxLayout(tab5)
        self.cell_table = QtWidgets.QTableWidget(0, 5)
        self.cell_table.setHorizontalHeaderLabels(["Cell ID", "LAC", "MCC", "MNC", "Freq"])
        v5.addWidget(self.cell_table)
        self.export_cells_btn = QtWidgets.QPushButton("CSV Export")
        v5.addWidget(self.export_cells_btn)

        # Tab 6: Packet stats
        tab6 = QtWidgets.QWidget()
        v6 = QtWidgets.QVBoxLayout(tab6)
        self.stats_canvas = FigureCanvas(Figure(figsize=(4,3)))
        self.stats_ax = self.stats_canvas.figure.add_subplot(111)
        v6.addWidget(self.stats_canvas)

        # Tab 7: Talkgroups
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
        self.tabs.addTab(tab7, "Talkgroups")

    def refresh_devices(self):
        """Populate device box with detected SDR devices."""
        self.device_box.clear()
        for dev in list_sdr_devices():
            self.device_box.addItem(dev)

    def _update_agc(self, value):
        """Update AGC level from slider."""
        self.agc_value.setText(str(value))
        self.player.agc_level = value

    def _update_ppm(self, value: int):
        """Update PPM correction for all SDR commands."""
        self.config["ppm"] = value
        self.scanner.ppm = value
        self.player.ppm = value
        self.decoder.ppm = value

    @QtCore.pyqtSlot(np.ndarray, np.ndarray)
    def _update_scan_results(self, freqs, powers):
        """Aggregiere Scan-Peaks und aktualisiere die Frequenzliste."""
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
        self.freq_label.setText(f"Freq: {freq/1e6:.3f} MHz")
        self.log.appendPlainText(f"Gew\u00e4hlte Frequenz: {freq/1e6:.3f} MHz")
        self.freq_history.appendleft(freq/1e6)
        self.current_frequency = freq
        self.player.start(freq)
        self.tetra_start_btn.setEnabled(True)
        if self.tetra_auto_cb.isChecked():
            self.start_decoding()

    @QtCore.pyqtSlot()
    def notify_activity(self):
        """Visual indicator when activity is detected."""
        self.activity_led.set_color("red")
        QtCore.QTimer.singleShot(500, lambda: self.activity_led.set_color("green"))

    def start_decoding(self):
        """Start TETRA decoding pipeline."""
        if self.current_frequency is None:
            return
        self._update_ppm(self.ppm_spin.value())
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn.setEnabled(True)
        self.tetra_output.clear()
        rec = self.record_audio_cb.isChecked()
        if self.play_audio_cb.isChecked():
            self.dec_audio_player.start(record=rec)
        self.decoder.start(self.current_frequency)

    def stop_decoding(self):
        """Stop TETRA decoding."""
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
        device = self.device_box.currentText()
        self.scanner.device = device
        self.player.device = device
        self._update_ppm(self.ppm_spin.value())
        rng = self.freq_range_box.currentData()
        f_start, f_end = rng if rng else (380e6, 430e6)
        self.log.appendPlainText(
            f"Starting scan with {device} ({f_start/1e6:.0f}-{f_end/1e6:.0f} MHz)"
        )
        self.scanner.start(f_start, f_end)

    def stop(self):
        self.log.appendPlainText("Stopping")
        self.scanner.stop()
        self.player.stop()
        self.stop_decoding()

    def closeEvent(self, event):
        self._persist_talkgroups_to_config()
        self._persist_selected_talkgroups_to_config()
        save_config(self.config)
        super().closeEvent(event)

    # ----- Utility methods -----
    def apply_theme(self, theme: str):
        if theme == "dark" and qdarkstyle:
            self.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        else:
            self.setStyleSheet("")
        self.config["theme"] = theme

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
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "CSV speichern", "cells.csv", "CSV Files (*.csv)")
        if not path:
            return
        with open(path, "w") as fh:
            fh.write("Cell,LAC,MCC,MNC,Freq\n")
            for c in self.cells.values():
                fh.write(f"{c.get('cell','')},{c.get('lac','')},{c.get('mcc','')},{c.get('mnc','')},{c.get('freq','')}\n")

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
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
