#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="/usr/local"
BUILD_DIR="${PROJECT_ROOT}/.build/osmo-tetra"

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
    printf 'Fehler: %s\n' "$*" >&2
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
                libglib2.0-0 portaudio19-dev rtl-sdr sox
            # osmocom-Abhängigkeiten
            run_sudo apt-get install -y libosmocore-dev libosmo-dsp-dev || true
            if ! dpkg -s libosmocore-dev >/dev/null 2>&1; then
                log "libosmocore-dev ist nicht installiert. Es findet kein automatischer Quell-Build statt; bitte manuell installieren oder aus den Quellen bauen."
            fi
            local osmo_dsp_via_source=false
            local osmo_dsp_pc_name=""
            if command -v pkg-config >/dev/null 2>&1; then
                for pc_name in libosmodsp libosmo-dsp; do
                    if pkg-config --exists "${pc_name}" >/dev/null 2>&1; then
                        osmo_dsp_via_source=true
                        osmo_dsp_pc_name="${pc_name}"
                        local osmo_dsp_prefix=""
                        osmo_dsp_prefix="$(pkg-config --variable=prefix "${pc_name}" 2>/dev/null || true)"
                        if [[ "${osmo_dsp_prefix}" == "/usr/local" ]]; then
                            log "libosmo-dsp wurde über /usr/local erkannt (pkg-config: ${pc_name})."
                        else
                            log "libosmo-dsp wurde über pkg-config erkannt (${pc_name}, Prefix: ${osmo_dsp_prefix:-unbekannt})."
                        fi
                        break
                    fi
                done
            fi
            if [[ "${osmo_dsp_via_source}" == false ]]; then
                if compgen -G "/usr/local/include/osmo-dsp/*.h" >/dev/null || compgen -G "/usr/local/lib/libosmo-dsp*" >/dev/null; then
                    osmo_dsp_via_source=true
                    log "libosmo-dsp wurde über /usr/local erkannt (Header/Library-Pfade)."
                fi
            fi
            if [[ "${osmo_dsp_via_source}" == false && -d /usr/local/lib/pkgconfig ]]; then
                if [[ ":${PKG_CONFIG_PATH:-}:" != *":/usr/local/lib/pkgconfig:"* ]]; then
                    export PKG_CONFIG_PATH="${PKG_CONFIG_PATH:+${PKG_CONFIG_PATH}:}/usr/local/lib/pkgconfig"
                    log "PKG_CONFIG_PATH wurde um /usr/local/lib/pkgconfig ergänzt, damit osmo-tetra Build-Abhängigkeiten gefunden werden."
                fi
            fi
            if ! dpkg -s libosmo-dsp-dev >/dev/null 2>&1; then
                if [[ "${osmo_dsp_via_source}" == true ]]; then
                    log "libosmo-dsp wurde über /usr/local erkannt; dpkg-Prüfung für libosmo-dsp-dev wird übersprungen."
                else
                    log "libosmo-dsp-dev ist nicht installiert. Es findet kein automatischer Quell-Build statt; bitte manuell installieren oder aus den Quellen bauen."
                fi
            fi
            ;;
        dnf)
            log "Verwende dnf, um Systemabhängigkeiten zu installieren."
            run_sudo dnf install -y \
                @"Development Tools" @"C Development Tools and Libraries" \
                git wget curl cmake ninja-build autoconf automake libtool \
                fftw-devel itpp-devel \
                libusbx-devel pcsclite-devel gnutls-devel boost-devel gmp-devel orc-devel \
                glib2 portaudio-devel \
                rtl-sdr sox || true
            ;;
        pacman)
            log "Verwende pacman, um Systemabhängigkeiten zu installieren."
            run_sudo pacman -Sy --noconfirm --needed \
                base-devel git wget curl cmake ninja autoconf automake libtool \
                fftw libusb pcsclite gnutls boost-libs gmp orc glib2 portaudio sox rtl-sdr || true
            ;;
        zypper)
            log "Verwende zypper, um Systemabhängigkeiten zu installieren."
            run_sudo zypper refresh
            run_sudo zypper install -y \
                -t pattern devel_C_C++ git wget curl cmake ninja autoconf automake libtool fftw3-devel itpp-devel libusb-1_0-devel pcsclite-devel \
                libgnutls-devel libboost_headers-devel libgmp-devel orc-devel glib2 portaudio-devel rtl-sdr sox || true
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
    local osmo_tetra_git_url="${OSMO_TETRA_GIT_URL:-https://gitea.osmocom.org/sdr/osmo-tetra.git}"
    local osmo_tetra_mirror_url="https://github.com/osmocom/osmo-tetra.git"

    if [[ ! -d "${BUILD_DIR}/osmo-tetra" ]]; then
        log "Klone osmocom/osmo-tetra von ${osmo_tetra_git_url}..."
        if ! GIT_TERMINAL_PROMPT=0 git clone --depth 1 "${osmo_tetra_git_url}" "${BUILD_DIR}/osmo-tetra"; then
            if [[ "${osmo_tetra_git_url}" != "${osmo_tetra_mirror_url}" ]]; then
                log "Klonen fehlgeschlagen. Versuche Mirror ${osmo_tetra_mirror_url}..."
                GIT_TERMINAL_PROMPT=0 git clone --depth 1 "${osmo_tetra_mirror_url}" "${BUILD_DIR}/osmo-tetra" || {
                    log "Klonen von osmocom-tetra ist fehlgeschlagen."
                    return 1
                }
            else
                log "Klonen von osmocom-tetra ist fehlgeschlagen."
                return 1
            fi
        fi
    else
        log "Aktualisiere vorhandenes osmo-tetra Repository..."
        (cd "${BUILD_DIR}/osmo-tetra" && GIT_TERMINAL_PROMPT=0 git pull --ff-only)
    fi

    pushd "${BUILD_DIR}/osmo-tetra" >/dev/null
    log "Führe Autotools-Konfiguration für osmo-tetra aus..."
    if [[ ! -f configure ]]; then
        if [[ -f ./autogen.sh ]]; then
            chmod +x ./autogen.sh || die "Konnte autogen.sh nicht ausführbar machen."
            ./autogen.sh || die "Autotools-Konfiguration über autogen.sh ist fehlgeschlagen."
        else
            require_command autoreconf
            require_command autoconf
            require_command automake
            require_command libtool
            autoreconf -fi || die "Autotools-Konfiguration über autoreconf ist fehlgeschlagen."
        fi
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

    local ensure_python_pip
    ensure_python_pip() {
        if python3 -m pip --version >/dev/null 2>&1; then
            return 0
        fi
        log "pip fehlt für python3. Versuche, pip nachzuinstallieren..."
        if python3 -m ensurepip --upgrade >/dev/null 2>&1; then
            return 0
        fi
        case "${manager}" in
            apt)
                run_sudo apt-get update
                run_sudo apt-get install -y python3-pip python3-venv
                ;;
            dnf)
                run_sudo dnf install -y python3-pip python3-virtualenv || true
                ;;
            pacman)
                run_sudo pacman -Sy --noconfirm --needed python-pip || true
                ;;
            zypper)
                run_sudo zypper refresh
                run_sudo zypper install -y python3-pip || true
                ;;
            *)
                log "Kein unterstützter Paketmanager gefunden, um pip zu installieren."
                ;;
        esac
        python3 -m pip --version >/dev/null 2>&1
    }

    local create_venv
    create_venv() {
        if python3 -m venv --upgrade-deps "$1" >/dev/null 2>&1; then
            return 0
        fi
        log "Erstellen der virtuellen Umgebung fehlgeschlagen. Installiere venv-Unterstützung und versuche erneut..."
        case "${manager}" in
            apt)
                run_sudo apt-get update
                run_sudo apt-get install -y python3-venv
                ;;
            dnf)
                run_sudo dnf install -y python3-virtualenv || true
                ;;
            pacman)
                run_sudo pacman -Sy --noconfirm --needed python-virtualenv || true
                ;;
            zypper)
                run_sudo zypper refresh
                run_sudo zypper install -y python3-virtualenv || true
                ;;
            *)
                ;;
        esac
        python3 -m venv --upgrade-deps "$1"
    }

    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        log "Virtuelle Umgebung aktiv: ${VIRTUAL_ENV}. Installiere dort."
        ensure_python_pip || true
        python3 -m pip install --upgrade pip
        python3 -m pip install -r "${PROJECT_ROOT}/requirements.txt"
        return
    fi

    local venv_path="${PROJECT_ROOT}/.venv"
    log "Keine virtuelle Umgebung aktiv. Verwende ${venv_path}."
    if [[ ! -d "${venv_path}" || ! -x "${venv_path}/bin/python3" || ! -f "${venv_path}/bin/activate" ]]; then
        if [[ -d "${venv_path}" ]]; then
            log "Vorhandene virtuelle Umgebung ist unvollständig. Erstelle sie neu."
            rm -rf "${venv_path}"
        fi
        log "Erstelle virtuelle Umgebung in ${venv_path}..."
        create_venv "${venv_path}"
    fi

    if [[ -f "${venv_path}/bin/activate" ]]; then
        # shellcheck source=/dev/null
        source "${venv_path}/bin/activate"
        log "Virtuelle Umgebung aktiviert: ${VIRTUAL_ENV}. Installiere dort."
        ensure_python_pip || true
        python3 -m pip install --upgrade pip
        python3 -m pip install -r "${PROJECT_ROOT}/requirements.txt"
    else
        log "Aktivierung der virtuellen Umgebung fehlgeschlagen. Installiere Python-Abhängigkeiten mit --user."
        ensure_python_pip || true
        python3 -m pip install --user -r "${PROJECT_ROOT}/requirements.txt"
    fi
}

main() {
    log "Starte Setup für tetra-decode (Linux)."
    install_packages
    build_osmo_tetra
    install_python_packages
    log "Setup abgeschlossen."
}

main "$@"
