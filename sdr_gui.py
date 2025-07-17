import os
import sys
import subprocess
import threading
import queue
import numpy as np
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QMessageBox
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pyaudio


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
        self.resize(800, 600)

        self.device_box = QtWidgets.QComboBox()
        self.device_box.addItems(["RTL-SDR", "HackRF", "LimeSDR"])

        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.freq_label = QtWidgets.QLabel("Freq: N/A")
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.canvas = SpectrumCanvas()

        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(self.device_box)
        top_layout.addWidget(self.start_btn)
        top_layout.addWidget(self.stop_btn)
        top_layout.addWidget(self.freq_label)

        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.canvas)
        main_layout.addWidget(self.log)

        central = QtWidgets.QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        self.scanner = SDRScanner(device=self.device_box.currentText(), parent=self)
        self.player = AudioPlayer(device=self.device_box.currentText(), parent=self)

        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.scanner.spectrum_ready.connect(self.canvas.update_spectrum)
        self.scanner.frequency_selected.connect(self.update_frequency)

    @QtCore.pyqtSlot(float)
    def update_frequency(self, freq):
        self.freq_label.setText(f"Freq: {freq/1e6:.3f} MHz")
        self.log.appendPlainText(f"Selected frequency: {freq/1e6:.3f} MHz")
        self.player.start(freq)

    @QtCore.pyqtSlot()
    def notify_activity(self):
        QMessageBox.information(self, "Activity", "Signal detected")

    def start(self):
        device = self.device_box.currentText()
        self.scanner.device = device
        self.player.device = device
        self.log.appendPlainText(f"Starting scan with {device}")
        self.scanner.start()

    def stop(self):
        self.log.appendPlainText("Stopping")
        self.scanner.stop()
        self.player.stop()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
