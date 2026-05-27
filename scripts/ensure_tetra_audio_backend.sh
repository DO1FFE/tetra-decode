#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEC_URL="https://www.etsi.org/deliver/etsi_en/300300_300399/30039502/01.03.01_60/en_30039502v010301p0.zip"
CODEC_MD5="a8115fe68ef8f8cc466f4192572a1e3e"
PATCH_DIR="${PROJECT_ROOT}/third_party/osmo-tetra/etsi_codec-patches"
BUILD_DIR="${PROJECT_ROOT}/.build/tetra-codec"
ARCHIV="${BUILD_DIR}/$(basename "${CODEC_URL}")"
QUELLORDNER="${BUILD_DIR}/quelle"
CODEC_TOOL_DIR="${PROJECT_ROOT}/tools/tetra-codec/bin"

log() {
    printf '[TETRA-Audio] %s\n' "$*"
}

die() {
    printf '[TETRA-Audio] Fehler: %s\n' "$*" >&2
    exit 1
}

pruefe_werkzeuge() {
    command -v python3 >/dev/null 2>&1 || die "python3 fehlt."
    command -v make >/dev/null 2>&1 || die "make fehlt."
    command -v gcc >/dev/null 2>&1 || die "gcc fehlt."
    command -v patch >/dev/null 2>&1 || die "patch fehlt."
    command -v md5sum >/dev/null 2>&1 || die "md5sum fehlt."
    command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || die "curl oder wget fehlt."
}

lade_codec() {
    mkdir -p "${BUILD_DIR}"
    if [[ -f "${ARCHIV}" ]]; then
        if [[ "$(md5sum "${ARCHIV}" | awk '{print $1}')" == "${CODEC_MD5}" ]]; then
            log "Codec-Archiv ist bereits vorhanden."
            return
        fi
        log "Verwerfe unvollständiges Codec-Archiv."
        rm -f "${ARCHIV}"
    fi

    if command -v curl >/dev/null 2>&1; then
        log "Lade ETSI-TETRA-Codec..."
        curl -L --fail -A "Mozilla/5.0" --output "${ARCHIV}" "${CODEC_URL}"
    else
        log "Lade ETSI-TETRA-Codec..."
        wget --user-agent="Mozilla/5.0" -O "${ARCHIV}" "${CODEC_URL}"
    fi

    local ist_md5
    ist_md5="$(md5sum "${ARCHIV}" | awk '{print $1}')"
    [[ "${ist_md5}" == "${CODEC_MD5}" ]] || die "Codec-Prüfsumme stimmt nicht (${ist_md5})."
}

entpacke_codec_kleingeschrieben() {
    rm -rf "${QUELLORDNER}"
    mkdir -p "${QUELLORDNER}"
    python3 - "${ARCHIV}" "${QUELLORDNER}" <<'PY'
import pathlib
import sys
import zipfile

archiv = pathlib.Path(sys.argv[1])
ziel = pathlib.Path(sys.argv[2])
for info in zipfile.ZipFile(archiv).infolist():
    name = info.filename.lower()
    if not name or name.endswith("/"):
        continue
    pfad = ziel / name
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archiv).open(info) as src, pfad.open("wb") as dst:
        dst.write(src.read())
PY
}

patch_codec() {
    log "Patch für ETSI-Codec anwenden..."
    (
        cd "${QUELLORDNER}"
        while IFS= read -r patchdatei; do
            patchdatei="${patchdatei%$'\r'}"
            [[ -z "${patchdatei}" ]] && continue
            patch -p1 -N -E < "${PATCH_DIR}/${patchdatei}"
        done < "${PATCH_DIR}/series"
    )
}

patch_codec_streaming() {
    log "Live-Flush für Codec-Pipes aktivieren..."
    python3 - "${QUELLORDNER}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])

sdecoder = root / "c-code" / "sdecoder.c"
text = sdecoder.read_text(encoding="latin-1")
alt = "    fwrite(synth, sizeof(Word16), L_frame,  f_syn);   /* Write output file */"
neu = alt + "\n    fflush(f_syn);"
if "fflush(f_syn);" not in text:
    text = text.replace(alt, neu)
sdecoder.write_text(text, encoding="latin-1")

cdecoder = root / "c-code" / "cdecoder.c"
text = cdecoder.read_text(encoding="latin-1")
alt = """\t\tif( fwrite( Reordered_array+137, sizeof(short), 137, fout ) \n\t\t\t\t\t!= 137 ) {\n\t\t\tfputs(\"cdecoder: can't write to output_file\",stderr );\n\t\t\tbreak;\n\t\t}"""
neu = alt + "\n\t\tfflush(fout);"
if "fflush(fout);" not in text:
    text = text.replace(alt, neu)
cdecoder.write_text(text, encoding="latin-1")
PY
}

baue_codec() {
    log "Baue cdecoder und sdecoder..."
    make -C "${QUELLORDNER}/c-code"
    mkdir -p "${CODEC_TOOL_DIR}"
    install -m 0755 "${QUELLORDNER}/c-code/cdecoder" "${CODEC_TOOL_DIR}/cdecoder"
    install -m 0755 "${QUELLORDNER}/c-code/sdecoder" "${CODEC_TOOL_DIR}/sdecoder"
}

baue_osmocom() {
    log "Baue TETRA-Decoder mit Audio-Burst-Ausgang..."
    bash "${PROJECT_ROOT}/scripts/ensure_osmocom_tetra.sh"
}

pruefe_backend() {
    [[ -x "${CODEC_TOOL_DIR}/cdecoder" ]] || die "cdecoder wurde nicht gebaut."
    [[ -x "${CODEC_TOOL_DIR}/sdecoder" ]] || die "sdecoder wurde nicht gebaut."
    [[ -x "${PROJECT_ROOT}/tools/osmocom-tetra/bin/tetra-rx" ]] || die "tetra-rx wurde nicht gebaut."
    log "Fertig. Codec: ${CODEC_TOOL_DIR}, Decoder: ${PROJECT_ROOT}/tools/osmocom-tetra/bin"
}

pruefe_werkzeuge
baue_osmocom
if [[ ! -x "${CODEC_TOOL_DIR}/cdecoder" || ! -x "${CODEC_TOOL_DIR}/sdecoder" ]]; then
    lade_codec
    entpacke_codec_kleingeschrieben
    patch_codec
    patch_codec_streaming
    baue_codec
else
    log "Codec-Werkzeuge sind bereits gebaut."
fi
pruefe_backend

# © 2026 Erik Schauer, do1ffe@darc.de
