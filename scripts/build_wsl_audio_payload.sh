#!/usr/bin/env bash
set -euo pipefail

PROJEKTWURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="debian:11"
PLATTFORM="linux/amd64"
BENUTZER_ID="$(id -u)"
GRUPPEN_ID="$(id -g)"

log() {
    printf '[WSL-Audio-Payload] %s\n' "$*"
}

die() {
    printf '[WSL-Audio-Payload] Fehler: %s\n' "$*" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || die "Docker fehlt."

cd "${PROJEKTWURZEL}"

log "Baue x86_64-Linux-Artefakte in ${IMAGE}..."
docker run --rm --platform "${PLATTFORM}" \
    -v "${PROJEKTWURZEL}:/src" \
    -w /src \
    "${IMAGE}" \
    bash -lc '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y --no-install-recommends \
    ca-certificates build-essential pkg-config libosmocore-dev \
    python3 curl wget patch unzip binutils >/dev/null

git -C third_party/osmo-tetra apply -R ../../patches/osmo-tetra/audio_udp_backend.patch 2>/dev/null || true
rm -rf tools/osmocom-tetra tools/tetra-codec .build/tetra-codec
find third_party/osmo-tetra/src \
    \( -name "*.o" -o -name "*.a" -o -name "tetra-rx" -o -name "float_to_bits" -o -name "tunctl" \) \
    -delete

chmod +x scripts/ensure_tetra_audio_backend.sh scripts/ensure_osmocom_tetra.sh
scripts/ensure_tetra_audio_backend.sh
strip tools/osmocom-tetra/bin/tetra-rx \
      tools/osmocom-tetra/bin/float_to_bits \
      tools/tetra-codec/bin/cdecoder \
      tools/tetra-codec/bin/sdecoder \
      tools/tetra-codec/bin/tetra-audio-backend

rm -rf installer_payload/wsl-audio-backend
mkdir -p installer_payload/wsl-audio-backend/tools/osmocom-tetra/bin \
         installer_payload/wsl-audio-backend/tools/osmocom-tetra/lib \
         installer_payload/wsl-audio-backend/tools/tetra-codec/bin \
         installer_payload/wsl-audio-backend/licenses/debian

cp tools/osmocom-tetra/bin/tetra-rx \
   tools/osmocom-tetra/bin/float_to_bits \
   installer_payload/wsl-audio-backend/tools/osmocom-tetra/bin/
cp tools/tetra-codec/bin/cdecoder \
   tools/tetra-codec/bin/sdecoder \
   tools/tetra-codec/bin/tetra-audio-backend \
   installer_payload/wsl-audio-backend/tools/tetra-codec/bin/

for lib in \
    /usr/lib/x86_64-linux-gnu/libtalloc.so.2* \
    /usr/lib/x86_64-linux-gnu/libosmocore.so.16* \
    /usr/lib/x86_64-linux-gnu/libsctp.so.1*
do
    cp -L "$lib" installer_payload/wsl-audio-backend/tools/osmocom-tetra/lib/
done

for pkg in libtalloc2 libosmocore16 libsctp1
do
    cp -a "/usr/share/doc/${pkg}/copyright" \
        "installer_payload/wsl-audio-backend/licenses/debian/${pkg}.copyright"
done

find installer_payload/wsl-audio-backend -type f -exec chmod 0644 {} +
chmod 0755 installer_payload/wsl-audio-backend/tools/osmocom-tetra/bin/* \
           installer_payload/wsl-audio-backend/tools/tetra-codec/bin/*
chown -R '"${BENUTZER_ID}:${GRUPPEN_ID}"' \
    installer_payload/wsl-audio-backend tools .build third_party/osmo-tetra
'

cat > installer_payload/wsl-audio-backend/README.txt <<'EOF'
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
EOF

chmod 0644 installer_payload/wsl-audio-backend/README.txt
git -C third_party/osmo-tetra apply -R ../../patches/osmo-tetra/audio_udp_backend.patch 2>/dev/null || true

log "Fertig: installer_payload/wsl-audio-backend"

# © 2026 Erik Schauer, do1ffe@darc.de
