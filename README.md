# TETRA Decode

This repository contains a simple PyQt5 application demonstrating how to scan
frequencies with an SDR (e.g. RTL-SDR, HackRF, LimeSDR) between 380 and 430 MHz.
The strongest frequency is automatically selected and demodulated to audio
using external command line tools such as `rtl_power` and `rtl_fm`.
It now also integrates the osmocom-tetra tools (`receiver1`, `demod_float`,
`tetra-rx`) to decode unencrypted TETRA control information.

The GUI shows a realtime spectrum, provides start/stop controls, and plays
received audio through the speakers using PyAudio.

Additional features include a scheduler for automatic scan/decoding cycles,
cell information display with CSV export, basic packet statistics, Telegram
notifications on activity, audio recording and spectrum snapshots. A light and
dark theme can be selected in the settings tab.

Run the application with:

```bash
python sdr_gui.py
```

External SDR utilities as well as the osmocom-tetra binaries must be installed
and accessible in the system path.
