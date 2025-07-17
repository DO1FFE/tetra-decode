import os
import sys
import subprocess
import threading
import shutil
from collections import deque
import numpy as np
from PyQt5 import QtWidgets, QtCore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pyaudio


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


class SDRScanner(QtCore.QObject):
    """Scan a frequency range using rtl_power and emit spectrum data."""

    spectrum_ready = QtCore.pyqtSignal(np.ndarray, np.ndarray)
    frequency_selected = QtCore.pyqtSignal(float)

    def __init__(self, device: str, parent=None):
        super().__init__(parent)
        self.device = device
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

    def __init__(self, device: str, parent=None):
        super().__init__(parent)
        self.device = device
        self._process = None
        self._stream = None
        self._pa = pyaudio.PyAudio()
        self.agc_level = 10000
        self.activity_threshold = 1000
        self.activity = QtCore.pyqtSignal()

    def start(self, frequency):
        self.stop()
        cmd = [
            "rtl_fm",
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
                QtCore.QMetaObject.invokeMethod(self.parent(), "notify_activity",
                                                QtCore.Qt.QueuedConnection)
            self._stream.write(audio.tobytes())

        self.stop()


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


class TetraDecoder(QtCore.QObject):
    """Run osmocom-tetra tools and emit decoded output."""

    output = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._running = threading.Event()
        self._procs = []

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
        for p in self._procs:
            if p and p.poll() is None:
                p.terminate()
        self._procs = []
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def _run(self, frequency: float):
        cmds = [
            ["receiver1", "-f", str(int(frequency))],
            ["demod_float"],
            ["tetra-rx"],
        ]

        # Check all commands exist before starting
        for cmd in cmds:
            if not shutil.which(cmd[0]):
                self.output.emit(f"{cmd[0]} not found in PATH")
                self.finished.emit()
                return

        try:
            p1 = subprocess.Popen(cmds[0], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p2 = subprocess.Popen(cmds[1], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
            self._procs = [p1, p2, p3]
        except Exception as exc:
            self.output.emit(f"Failed to start decoder: {exc}")
            self.finished.emit()
            return

        for line in p3.stdout:
            if not self._running.is_set():
                break
            self.output.emit(line.rstrip())

        self.stop()
        self.finished.emit()


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
        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
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

        self.tabs = QtWidgets.QTabWidget()
        self._build_tabs()

        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)
        lay.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.scanner = SDRScanner(device=self.device_box.currentText(), parent=self)
        self.player = AudioPlayer(device=self.device_box.currentText(), parent=self)
        self.decoder = TetraDecoder(parent=self)

        self.agc_slider.valueChanged.connect(self._update_agc)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.scanner.spectrum_ready.connect(self.canvas.update_spectrum)
        self.scanner.frequency_selected.connect(self.update_frequency)

        self.decoder.output.connect(self._append_tetra)
        self.decoder.finished.connect(self._decoder_finished)

        self.tetra_start_btn.clicked.connect(self.start_decoding)
        self.tetra_stop_btn.clicked.connect(self.stop_decoding)

        self.freq_history = deque(maxlen=10)
        self.current_frequency = None

    def _build_tabs(self):
        """Create the main tabs, including TETRA decoding."""
        # Tab 1: Spectrum & Control
        tab1 = QtWidgets.QWidget()
        ctl_layout = QtWidgets.QHBoxLayout()
        ctl_layout.addWidget(self.start_btn)
        ctl_layout.addWidget(self.stop_btn)
        ctl_layout.addWidget(self.freq_label)

        v1 = QtWidgets.QVBoxLayout(tab1)
        v1.addLayout(ctl_layout)
        v1.addWidget(self.canvas)
        v1.addWidget(self.log)
        v1.addWidget(QtWidgets.QLabel("Letzte Frequenzen:"))
        v1.addWidget(self.freq_list)

        # Tab 2: Audio & Activity
        tab2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(tab2)
        h_led = QtWidgets.QHBoxLayout()
        h_led.addWidget(QtWidgets.QLabel("Aktivit\u00e4t:"))
        h_led.addWidget(self.activity_led)
        h_led.addStretch()
        v2.addLayout(h_led)

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
        agc_layout = QtWidgets.QHBoxLayout()
        agc_layout.addWidget(self.agc_slider)
        agc_layout.addWidget(self.agc_value)
        f3.addRow("AGC-Level:", agc_layout)

        # Tab 4: TETRA decoding
        tab4 = QtWidgets.QWidget()
        v4 = QtWidgets.QVBoxLayout(tab4)
        ctl4 = QtWidgets.QHBoxLayout()
        self.tetra_start_btn = QtWidgets.QPushButton("Dekodierung starten")
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn = QtWidgets.QPushButton("Stop")
        self.tetra_stop_btn.setEnabled(False)
        self.tetra_auto_cb = QtWidgets.QCheckBox("Automatisch nach Scan")
        ctl4.addWidget(self.tetra_start_btn)
        ctl4.addWidget(self.tetra_stop_btn)
        ctl4.addWidget(self.tetra_auto_cb)
        ctl4.addStretch()
        v4.addLayout(ctl4)
        self.tetra_output = QtWidgets.QPlainTextEdit()
        self.tetra_output.setReadOnly(True)
        v4.addWidget(self.tetra_output)

        self.tabs.addTab(tab1, "Spektrum & Steuerung")
        self.tabs.addTab(tab2, "Audio & Aktivit\u00e4t")
        self.tabs.addTab(tab3, "Einstellungen")
        self.tabs.addTab(tab4, "TETRA-Dekodierung")

    def refresh_devices(self):
        """Populate device box with detected SDR devices."""
        self.device_box.clear()
        for dev in list_sdr_devices():
            self.device_box.addItem(dev)

    def _update_agc(self, value):
        """Update AGC level from slider."""
        self.agc_value.setText(str(value))
        self.player.agc_level = value

    @QtCore.pyqtSlot(float)
    def update_frequency(self, freq):
        """Handle new frequency selection."""
        self.freq_label.setText(f"Freq: {freq/1e6:.3f} MHz")
        self.log.appendPlainText(f"Selected frequency: {freq/1e6:.3f} MHz")
        self.freq_history.appendleft(freq/1e6)
        self.freq_list.clear()
        for f in self.freq_history:
            self.freq_list.addItem(f"{f:.3f} MHz")
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
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn.setEnabled(True)
        self.tetra_output.clear()
        self.decoder.start(self.current_frequency)

    def stop_decoding(self):
        """Stop TETRA decoding."""
        self.decoder.stop()

    def _append_tetra(self, line: str):
        self.tetra_output.appendPlainText(line)

    def _decoder_finished(self):
        self.tetra_start_btn.setEnabled(True)
        self.tetra_stop_btn.setEnabled(False)

    def start(self):
        device = self.device_box.currentText()
        self.scanner.device = device
        self.player.device = device
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


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
