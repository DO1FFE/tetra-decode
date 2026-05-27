TETRA-WSL-Audio-Backend-Payload

Enthalten sind vorgebaute x86_64-Linux-Werkzeuge für WSL:
- tools/osmocom-tetra/bin/tetra-rx mit lokalem UDP-Audio-Burst-Ausgang
- tools/osmocom-tetra/bin/float_to_bits
- tools/tetra-codec/bin/cdecoder
- tools/tetra-codec/bin/sdecoder
- tools/tetra-codec/bin/tetra-audio-backend
- notwendige dynamische Bibliotheken für tetra-rx unter tools/osmocom-tetra/lib

Build-Basis: Debian 11 amd64, glibc 2.31, libosmocore 1.4.2.
Die App setzt beim Start LD_LIBRARY_PATH auf tools/osmocom-tetra/lib.
Es werden keine WSL-Buildpakete und kein ETSI-Codec-Download auf dem Zielsystem benötigt.

© 2026 Erik Schauer, do1ffe@darc.de
