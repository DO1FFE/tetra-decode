#!/usr/bin/env bash
set -euo pipefail

PROJEKTWURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="${PROJEKTWURZEL}/dist-installer/TETRA-Decode-Windows-Offline-Setup.exe"
PRUEFSUMME="${INSTALLER}.sha256"

log() {
    printf '[Windows-Offline-Installer] %s\n' "$*"
}

die() {
    printf '[Windows-Offline-Installer] Fehler: %s\n' "$*" >&2
    exit 1
}

cd "${PROJEKTWURZEL}"

command -v makensis >/dev/null 2>&1 || die "makensis fehlt. Installiere NSIS, z. B. mit: sudo apt-get install nsis"
[[ -f tetra-decode.exe ]] || die "tetra-decode.exe fehlt."
[[ -f third_party/osmo-tetra/src/demod/simdemod3.py ]] || die "third_party/osmo-tetra ist nicht initialisiert."
[[ -f installer_payload/osmocom-tetra/tetra-rx.exe ]] || die "osmocom-tetra-Payload fehlt."
[[ -f installer_payload/rtl-sdr/x64/rtl_sdr.exe ]] || die "RTL-SDR-Payload fehlt."
[[ -f installer_payload/zadig/zadig.exe ]] || die "Zadig-Payload fehlt."
find installer_payload/gnuradio -maxdepth 1 -name 'radioconda-*-Windows-x86_64.exe' -print -quit | grep -q . || \
    die "Radioconda/GNU-Radio-Payload fehlt. Baue zuerst mit scripts/build_windows_installer.ps1 oder lade den Payload nach installer_payload/gnuradio."

mkdir -p dist-installer
log "Baue NSIS-Offline-Installer..."
makensis windows-offline-installer.nsi

sha256sum "${INSTALLER}" | sed "s#${INSTALLER}#$(basename "${INSTALLER}")#" > "${PRUEFSUMME}"
log "Fertig: ${INSTALLER}"
log "Prüfsumme: $(cat "${PRUEFSUMME}")"

# © 2026 Erik Schauer, do1ffe@darc.de
