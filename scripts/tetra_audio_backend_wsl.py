#!/usr/bin/env python3
"""Wandelt Telive-kompatible TETRA-Traffic-Bursts live in PCM um."""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time


FRAME_PREFIX = 13
TRAFFIC_BYTES = 1380
MIN_FRAME_BYTES = FRAME_PREFIX + TRAFFIC_BYTES
PCM_CHUNK_BYTES = 320


def _status(text: str) -> None:
    print(f"[TETRA-Audio] {text}", file=sys.stderr, flush=True)


def _decoder_befehl(programm: str) -> list[str]:
    if shutil.which("stdbuf"):
        return ["stdbuf", "-o0", "-e0", programm, "/dev/stdin", "/dev/stdout"]
    return [programm, "/dev/stdin", "/dev/stdout"]


def _starte_codec(cdecoder: str, sdecoder: str):
    cproc = subprocess.Popen(
        _decoder_befehl(cdecoder),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    sproc = subprocess.Popen(
        _decoder_befehl(sdecoder),
        stdin=cproc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if cproc.stdout:
        cproc.stdout.close()
    return cproc, sproc


def _verwerfe_stderr(proc: subprocess.Popen) -> None:
    stream = proc.stderr
    if not stream:
        return
    try:
        for _chunk in iter(lambda: stream.read(4096), b""):
            pass
    except Exception:
        pass


def _pcm_weiterreichen(proc: subprocess.Popen, stopp: threading.Event) -> None:
    stream = proc.stdout
    if not stream:
        return
    ausgabe = sys.stdout.buffer
    while not stopp.is_set():
        try:
            daten = stream.read(PCM_CHUNK_BYTES)
        except Exception:
            break
        if not daten:
            if proc.poll() is not None:
                break
            time.sleep(0.02)
            continue
        try:
            ausgabe.write(daten)
            ausgabe.flush()
        except BrokenPipeError:
            stopp.set()
            break


def _beende(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=1.5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live-Backend für unverschlüsselte TETRA-Sprachframes."
    )
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, required=True)
    parser.add_argument("--cdecoder", default=os.environ.get("TETRA_CDECODER", "cdecoder"))
    parser.add_argument("--sdecoder", default=os.environ.get("TETRA_SDECODER", "sdecoder"))
    args = parser.parse_args()

    stopp = threading.Event()

    def _signal_handler(_signum, _frame):
        stopp.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    cproc = sproc = None
    sock = None
    try:
        cproc, sproc = _starte_codec(args.cdecoder, args.sdecoder)
        for proc in (cproc, sproc):
            threading.Thread(target=_verwerfe_stderr, args=(proc,), daemon=True).start()
        threading.Thread(target=_pcm_weiterreichen, args=(sproc, stopp), daemon=True).start()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((args.udp_host, args.udp_port))
        sock.settimeout(0.25)
        _status(f"hört auf UDP {args.udp_host}:{args.udp_port}")

        while not stopp.is_set():
            if cproc.poll() is not None or sproc.poll() is not None:
                _status("Codec-Prozess wurde beendet")
                return 3
            try:
                paket, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            if len(paket) < MIN_FRAME_BYTES or not paket.startswith(b"TRA:"):
                continue
            if not cproc.stdin:
                continue
            try:
                cproc.stdin.write(paket[FRAME_PREFIX:FRAME_PREFIX + TRAFFIC_BYTES])
                cproc.stdin.flush()
            except BrokenPipeError:
                _status("Codec-Pipe wurde geschlossen")
                return 4
        return 0
    except Exception as exc:
        _status(f"Fehler: {exc}")
        return 2
    finally:
        stopp.set()
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if cproc and cproc.stdin:
            try:
                cproc.stdin.close()
            except Exception:
                pass
        _beende(sproc)
        _beende(cproc)


if __name__ == "__main__":
    raise SystemExit(main())

# © 2026 Erik Schauer, do1ffe@darc.de
