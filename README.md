# TETRA Decode

This repository contains a simple PyQt5 application demonstrating how to scan
frequencies with an SDR (e.g. RTL-SDR, HackRF, LimeSDR) between 380 and 430 MHz.
The strongest frequency is automatically selected and demodulated to audio
using external command line tools such as `rtl_power` and `rtl_fm`.

The GUI shows a realtime spectrum, provides start/stop controls, and plays
received audio through the speakers using PyAudio.

Run the application with:

```bash
python sdr_gui.py
```

External SDR utilities must be installed and accessible in the system path.
