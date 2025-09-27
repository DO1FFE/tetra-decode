#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="/usr/local"
BUILD_DIR="${PROJECT_ROOT}/.build/osmo-tetra"

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Benötigtes Programm '$1' wurde nicht gefunden."
}

run_sudo() {
    if [[ "${EUID}" -ne 0 ]]; then
        sudo "$@"
    else
        "$@"
    fi
}

install_packages() {
    local manager=""
    if command -v apt-get >/dev/null 2>&1; then
        manager="apt"
    elif command -v dnf >/dev/null 2>&1; then
        manager="dnf"
    elif command -v pacman >/dev/null 2>&1; then
        manager="pacman"
    elif command -v zypper >/dev/null 2>&1; then
        manager="zypper"
    fi

    case "$manager" in
        apt)
            log "Verwende apt, um Systemabhängigkeiten zu installieren."
            run_sudo apt-get update
            run_sudo apt-get install -y \
                build-essential pkg-config cmake ninja-build git wget curl \
                autoconf automake libtool \
                libfftw3-dev libitpp-dev libusb-1.0-0-dev libpcsclite-dev \
                libgnutls28-dev libboost-all-dev libgmp-dev liborc-0.4-dev \
                rtl-sdr sox
            # osmocom-Abhängigkeiten
            run_sudo apt-get install -y libosmocore-dev libosmo-dsp-dev || \
                log "libosmocore-dev nicht verfügbar. Wird bei Bedarf aus den Quellen gebaut."
            ;;
        dnf)
            log "Verwende dnf, um Systemabhängigkeiten zu installieren."
            run_sudo dnf install -y \
                @"Development Tools" @"C Development Tools and Libraries" \
                git wget curl cmake ninja-build autoconf automake libtool \
                fftw-devel itpp-devel \
                libusbx-devel pcsclite-devel gnutls-devel boost-devel gmp-devel orc-devel \
                rtl-sdr sox || true
            ;;
        pacman)
            log "Verwende pacman, um Systemabhängigkeiten zu installieren."
            run_sudo pacman -Sy --noconfirm --needed \
                base-devel git wget curl cmake ninja autoconf automake libtool \
                fftw libusb pcsclite gnutls boost-libs gmp orc sox rtl-sdr || true
            ;;
        zypper)
            log "Verwende zypper, um Systemabhängigkeiten zu installieren."
            run_sudo zypper refresh
            run_sudo zypper install -y \
                -t pattern devel_C_C++ git wget curl cmake ninja autoconf automake libtool fftw3-devel itpp-devel libusb-1_0-devel pcsclite-devel \
                libgnutls-devel libboost_headers-devel libgmp-devel orc-devel rtl-sdr sox || true
            ;;
        *)
            log "Kein unterstützter Paketmanager gefunden. Überspringe Systempakete."
            ;;
    esac
}

build_osmo_tetra() {
    if command -v receiver1 >/dev/null 2>&1 && command -v tetra-rx >/dev/null 2>&1; then
        log "osmocom-tetra scheint bereits installiert zu sein."
        return
    fi

    require_command git

    mkdir -p "${BUILD_DIR}"
    if [[ ! -d "${BUILD_DIR}/osmo-tetra" ]]; then
        log "Klone osmocom/osmo-tetra..."
        git clone --depth 1 https://gitea.osmocom.org/sdr/osmo-tetra.git "${BUILD_DIR}/osmo-tetra"
    else
        log "Aktualisiere vorhandenes osmo-tetra Repository..."
        (cd "${BUILD_DIR}/osmo-tetra" && git pull --ff-only)
    fi

    pushd "${BUILD_DIR}/osmo-tetra" >/dev/null
    log "Führe Autotools-Konfiguration für osmo-tetra aus..."
    if [[ ! -f configure ]]; then
        ./autogen.sh
    fi

    log "Starte Build von osmo-tetra..."
    ./configure --prefix="${INSTALL_PREFIX}"
    make -j"$(nproc)"
    run_sudo make install
    run_sudo ldconfig || true
    popd >/dev/null
}

install_python_packages() {
    log "Installiere Python-Abhängigkeiten..."
    require_command python3
    python3 -m pip install --upgrade pip
    python3 -m pip install -r "${PROJECT_ROOT}/requirements.txt"
}

main() {
    log "Starte Setup für tetra-decode (Linux)."
    install_packages
    build_osmo_tetra
    install_python_packages
    log "Setup abgeschlossen."
}

main "$@"
