#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="/usr/local"
BUILD_DIR="${PROJECT_ROOT}/.build/osmo-tetra"

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

run_sudo() {
    if [[ "${EUID}" -ne 0 ]]; then
        sudo "$@"
    else
        "$@"
    fi
}

PKG_MANAGER=""
APT_UPDATED=0

detect_package_manager() {
    if command -v apt-get >/dev/null 2>&1; then
        PKG_MANAGER="apt"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MANAGER="dnf"
    elif command -v pacman >/dev/null 2>&1; then
        PKG_MANAGER="pacman"
    elif command -v zypper >/dev/null 2>&1; then
        PKG_MANAGER="zypper"
    else
        PKG_MANAGER=""
    fi
}

ensure_package_manager() {
    if [[ -z "${PKG_MANAGER}" ]]; then
        detect_package_manager
        if [[ -z "${PKG_MANAGER}" ]]; then
            log "Kein unterstützter Paketmanager gefunden. Bitte installiere fehlende Pakete manuell."
            return 1
        fi
    fi
    return 0
}

update_apt_once() {
    if [[ "${PKG_MANAGER}" == "apt" && "${APT_UPDATED}" -eq 0 ]]; then
        run_sudo apt-get update
        APT_UPDATED=1
    fi
}

install_system_packages() {
    local packages=("$@")
    ensure_package_manager || return 1
    case "${PKG_MANAGER}" in
        apt)
            update_apt_once
            run_sudo apt-get install -y "${packages[@]}"
            ;;
        dnf)
            run_sudo dnf install -y "${packages[@]}"
            ;;
        pacman)
            run_sudo pacman -Sy --noconfirm --needed "${packages[@]}"
            ;;
        zypper)
            run_sudo zypper install -y "${packages[@]}"
            ;;
    esac
}

have_commands() {
    local cmd
    for cmd in "$@"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            return 1
        fi
    done
    return 0
}

ensure_rtl_sdr() {
    local rtl_cmds=(rtl_power rtl_fm rtl_test)
    if have_commands "${rtl_cmds[@]}"; then
        log "RTL-SDR Werkzeuge bereits vorhanden."
        return
    fi

    log "Installiere RTL-SDR Werkzeuge..."
    if ensure_package_manager; then
        case "${PKG_MANAGER}" in
            apt)
                install_system_packages rtl-sdr sox
                ;;
            dnf)
                install_system_packages rtl-sdr sox || true
                ;;
            pacman)
                install_system_packages rtl-sdr sox || true
                ;;
            zypper)
                install_system_packages rtl-sdr sox || true
                ;;
        esac
    else
        log "RTL-SDR Werkzeuge konnten nicht automatisch installiert werden."
    fi

    if ! have_commands "${rtl_cmds[@]}"; then
        log "RTL-SDR Werkzeuge fehlen weiterhin. Bitte installiere sie manuell."
    fi
}

ensure_build_dependencies() {
    ensure_package_manager || return
    case "${PKG_MANAGER}" in
        apt)
            install_system_packages build-essential pkg-config cmake ninja-build git wget curl \
                autoconf automake libtool \
                libfftw3-dev libitpp-dev libusb-1.0-0-dev libpcsclite-dev \
                libgnutls28-dev libboost-all-dev libgmp-dev liborc-0.4-dev
            install_system_packages libosmocore-dev libosmo-dsp-dev || true
            ;;
        dnf)
            install_system_packages @"Development Tools" @"C Development Tools and Libraries" \
                git wget curl cmake ninja-build autoconf automake libtool \
                fftw-devel itpp-devel \
                libusbx-devel pcsclite-devel gnutls-devel boost-devel gmp-devel orc-devel || true
            ;;
        pacman)
            install_system_packages base-devel git wget curl cmake ninja autoconf automake libtool \
                fftw libusb pcsclite gnutls boost-libs gmp orc || true
            ;;
        zypper)
            install_system_packages -t pattern devel_C_C++ git wget curl cmake ninja autoconf automake libtool \
                fftw3-devel itpp-devel libusb-1_0-devel pcsclite-devel \
                libgnutls-devel libboost_headers-devel libgmp-devel orc-devel || true
            ;;
    esac
}

build_osmo_tetra() {
    local osmo_cmds=(receiver1 tetra-rx demod_float)
    if have_commands "${osmo_cmds[@]}"; then
        log "osmocom-tetra bereits vorhanden."
        return
    fi

    ensure_build_dependencies

    if ! command -v git >/dev/null 2>&1; then
        log "git wird benötigt, um osmocom-tetra zu bauen. Bitte installiere git und versuche es erneut."
        return
    fi

    mkdir -p "${BUILD_DIR}"
    if [[ ! -d "${BUILD_DIR}/osmo-tetra" ]]; then
        log "Klone osmocom/osmo-tetra..."
        git clone --depth 1 https://gitea.osmocom.org/sdr/osmo-tetra.git "${BUILD_DIR}/osmo-tetra"
    else
        log "Aktualisiere vorhandenes osmo-tetra Repository..."
        (cd "${BUILD_DIR}/osmo-tetra" && git pull --ff-only)
    fi

    pushd "${BUILD_DIR}/osmo-tetra" >/dev/null
    if [[ ! -f configure ]]; then
        log "Führe autogen.sh aus..."
        ./autogen.sh
    fi

    log "Konfiguriere osmocom-tetra..."
    ./configure --prefix="${INSTALL_PREFIX}"
    log "Baue osmocom-tetra..."
    make -j"$(nproc)"
    log "Installiere osmocom-tetra..."
    run_sudo make install
    run_sudo ldconfig || true
    popd >/dev/null

    if have_commands "${osmo_cmds[@]}"; then
        log "osmocom-tetra Installation abgeschlossen."
    else
        log "osmocom-tetra konnte nicht installiert werden."
    fi
}

install_python_requirements() {
    if command -v python3 >/dev/null 2>&1; then
        log "Installiere Python-Abhängigkeiten..."
        python3 -m pip install --upgrade pip
        python3 -m pip install -r "${PROJECT_ROOT}/requirements.txt"
    else
        log "python3 wurde nicht gefunden. Überspringe Python-Abhängigkeiten."
    fi
}

main() {
    log "Prüfe und installiere zusätzliche Abhängigkeiten (Linux)."
    ensure_rtl_sdr
    build_osmo_tetra
    install_python_requirements
    log "install.sh abgeschlossen."
}

main "$@"
