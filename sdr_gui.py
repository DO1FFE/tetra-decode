import os
import sys
import subprocess
import threading
import shutil
import argparse
from collections import deque
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import importlib
import re
import json
import wave
import time
import tempfile
import pkgutil
import ctypes.util
import shlex
import glob
try:
    import qdarkstyle
except Exception:
    qdarkstyle = None

try:
    import requests
except Exception:
    requests = None

try:
    import numpy as np
except Exception:
    pip_verfuegbar = pkgutil.find_loader("pip") is not None
    if pip_verfuegbar:
        hinweis = (
            "Fehlendes Python-Modul 'numpy'. Bitte installiere es, z. B. mit "
            "'python3 -m pip install numpy'."
        )
    else:
        hinweis = (
            "Fehlendes Python-Modul 'numpy' und 'pip' ist nicht verfügbar. "
            "Installiere zuerst pip (z. B. 'python3 -m ensurepip --upgrade' "
            "oder 'sudo apt-get install python3-pip') und danach "
            "'python3 -m pip install numpy'."
        )
    print(hinweis, file=sys.stderr)
    raise SystemExit(1)
if sys.platform.startswith("linux"):
    libgl = ctypes.util.find_library("GL")
    if libgl is None:
        print(
            "Fehlende Systembibliothek 'libGL.so.1'. Bitte installiere "
            "'libgl1' (z. B. 'sudo apt-get install libgl1') und starte "
            "das Programm erneut.",
            file=sys.stderr,
        )
        raise SystemExit(1)

from PyQt5 import QtWidgets, QtCore, QtGui
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pyaudio


if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _resource_roots():
    """Liefert mögliche Wurzeln für gebündelte und portable Ressourcen."""
    roots = [PROJECT_ROOT]
    if getattr(sys, "frozen", False):
        roots.extend([os.path.dirname(PROJECT_ROOT), os.getcwd()])
    if sys.platform.startswith("win"):
        program_data = os.environ.get("ProgramData")
        if program_data:
            roots.append(os.path.join(program_data, "tetra-decode"))

    unique_roots = []
    seen = set()
    for root in roots:
        if not root:
            continue
        normalized = os.path.normcase(os.path.abspath(root))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_roots.append(root)
    return unique_roots


TOOL_BASENAMES = {
    "receiver1",
    "tetra-rx",
    "rtl_power",
    "rtl_fm",
    "rtl_sdr",
    "rtl_test",
    "demod_float",
    "float_to_bits",
}


def _tool_filenames():
    if sys.platform.startswith("win"):
        suffixes = (".exe", ".cmd", ".bat")
        return {name + suffix for name in TOOL_BASENAMES for suffix in suffixes}
    return set(TOOL_BASENAMES)


def _prepend_tool_paths():
    """Macht lokale und Setup-Toolverzeichnisse fuer subprocess/shutil.which sichtbar."""
    roots = []
    for root in _resource_roots():
        roots.extend([
            os.path.join(root, "tools"),
            os.path.join(root, "bin"),
            os.path.join(root, "installer_payload"),
            root,
        ])

    def _tool_dir_priority(path: str) -> int:
        lowered = path.lower()
        if "x64" in lowered or "64" in lowered:
            return 0
        if "x86" in lowered or "32" in lowered:
            return 2
        return 1

    tool_files = _tool_filenames()
    current_paths = [path for path in os.environ.get("PATH", "").split(os.pathsep) if path]
    discovered = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        root_discovered = []
        for directory, _dirnames, filenames in os.walk(root):
            available = {name.lower() for name in filenames}
            if not tool_files.intersection(available):
                continue
            normalized = os.path.normcase(os.path.abspath(directory))
            if normalized in discovered or normalized in root_discovered:
                continue
            root_discovered.append(normalized)
        discovered.extend(sorted(root_discovered, key=_tool_dir_priority))

    if discovered:
        promoted = set(discovered)
        remaining = [
            path for path in current_paths
            if os.path.normcase(os.path.abspath(path)) not in promoted
        ]
        os.environ["PATH"] = os.pathsep.join(discovered + remaining)


_prepend_tool_paths()


def _official_demod_script():
    for root in _resource_roots():
        script = os.path.join(
            root,
            "third_party",
            "osmo-tetra",
            "src",
            "demod",
            "simdemod3.py",
        )
        if os.path.exists(script):
            return script
    return None


_GNURADIO_PYTHON_CACHE = None
_WSL_OSMO_CACHE = None

_RTL_U8_TO_COMPLEX64_SCRIPT = r"""
import sys
import os
import numpy as np

mode = os.environ.get("TETRA_IQ_MODE", "normal").strip().lower()

while True:
    chunk = sys.stdin.buffer.read(262144)
    if not chunk:
        break
    if len(chunk) % 2:
        chunk = chunk[:-1]
    if not chunk:
        continue
    iq = np.frombuffer(chunk, dtype=np.uint8).astype(np.float32)
    iq = (iq - 127.5) / 128.0
    i_samples = iq[0::2]
    q_samples = iq[1::2]
    if mode == "conjugate":
        complex_iq = i_samples - 1j * q_samples
    elif mode == "swap":
        complex_iq = q_samples + 1j * i_samples
    elif mode == "swap_conjugate":
        complex_iq = q_samples - 1j * i_samples
    else:
        complex_iq = i_samples + 1j * q_samples
    sys.stdout.buffer.write(complex_iq.astype(np.complex64).tobytes())
    sys.stdout.buffer.flush()
"""


def _hidden_subprocess_kwargs():
    """Verhindert sichtbare Konsolenfenster bei Hilfsprogrammen unter Windows."""
    if not sys.platform.startswith("win"):
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _gnuradio_python_candidates():
    candidates = [] if getattr(sys, "frozen", False) else [sys.executable]
    for name in ("python3", "python"):
        executable = shutil.which(name)
        if executable:
            candidates.append(executable)

    if sys.platform.startswith("win"):
        env_roots = [
            os.environ.get("RADIOCONDA_ROOT"),
            os.environ.get("CONDA_PREFIX"),
        ]
        static_roots = [
            os.path.join(os.environ.get("USERPROFILE", ""), "radioconda"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "radioconda"),
            os.path.join(os.environ.get("ProgramFiles", ""), "radioconda"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "radioconda"),
            os.path.join(os.environ.get("ProgramData", ""), "radioconda"),
        ]
        candidates.extend(
            os.path.join(root, "python.exe")
            for root in env_roots + static_roots
            if root
        )
        for root in (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramData"),
        ):
            if not root:
                continue
            candidates.extend(glob.glob(os.path.join(root, "GNU Radio*", "bin", "python.exe")))
            candidates.extend(glob.glob(os.path.join(root, "GNURadio*", "bin", "python.exe")))

    unique = []
    seen = set()
    for candidate in candidates:
        if not candidate or not os.path.exists(candidate):
            continue
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(os.path.abspath(candidate))
    return unique


def _gnuradio_env_for(executable: str):
    env = os.environ.copy()
    if not sys.platform.startswith("win"):
        return env
    root = os.path.dirname(os.path.abspath(executable))
    path_dirs = [
        root,
        os.path.join(root, "Library", "bin"),
        os.path.join(root, "Scripts"),
        os.path.join(root, "bin"),
    ]
    if os.path.basename(root).lower() == "bin":
        parent = os.path.dirname(root)
        path_dirs.extend([
            parent,
            os.path.join(parent, "Library", "bin"),
            os.path.join(parent, "Scripts"),
        ])
    existing = [path for path in env.get("PATH", "").split(os.pathsep) if path]
    promoted = []
    for path in path_dirs:
        if path and os.path.isdir(path) and path not in promoted:
            promoted.append(path)
    env["PATH"] = os.pathsep.join(promoted + existing)
    return env


def _promote_gnuradio_runtime(executable: str):
    env = _gnuradio_env_for(executable)
    os.environ["PATH"] = env.get("PATH", os.environ.get("PATH", ""))


def _find_gnuradio_python():
    global _GNURADIO_PYTHON_CACHE
    if _GNURADIO_PYTHON_CACHE is not None:
        return _GNURADIO_PYTHON_CACHE or None

    for executable in _gnuradio_python_candidates():
        try:
            result = subprocess.run(
                [executable, "-c", "import gnuradio"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                env=_gnuradio_env_for(executable),
                **_hidden_subprocess_kwargs(),
            )
        except Exception:
            continue
        if result.returncode == 0:
            _promote_gnuradio_runtime(executable)
            _GNURADIO_PYTHON_CACHE = executable
            return executable

    _GNURADIO_PYTHON_CACHE = ""
    return None


def _wsl_path(path: str):
    if not sys.platform.startswith("win") or not shutil.which("wsl.exe"):
        return None
    try:
        result = subprocess.run(
            ["wsl.exe", "wslpath", "-a", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    converted = result.stdout.strip()
    return converted or None


def _wsl_osmo_decoder_available():
    global _WSL_OSMO_CACHE
    if _WSL_OSMO_CACHE is not None:
        return _WSL_OSMO_CACHE
    if not (sys.platform.startswith("win") and shutil.which("wsl.exe") and shutil.which("rtl_sdr")):
        _WSL_OSMO_CACHE = False
        return False
    demod_script = _official_demod_script()
    wsl_demod_script = _wsl_path(demod_script) if demod_script else None
    if not wsl_demod_script:
        _WSL_OSMO_CACHE = False
        return False
    check_cmd = (
        f"test -f {shlex.quote(wsl_demod_script)} && "
        "command -v python3 >/dev/null && "
        "python3 -c 'import gnuradio' >/dev/null 2>&1 && "
        "command -v tetra-rx >/dev/null"
    )
    try:
        result = subprocess.run(
            ["wsl.exe", "--", "bash", "-lc", check_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        _WSL_OSMO_CACHE = False
        return False
    _WSL_OSMO_CACHE = result.returncode == 0
    return _WSL_OSMO_CACHE


def _official_osmo_decoder_available():
    return bool(
        shutil.which("rtl_sdr")
        and shutil.which("tetra-rx")
        and _official_demod_script()
        and _find_gnuradio_python()
    ) or (sys.platform.startswith("win") and _wsl_osmo_decoder_available())


def _native_osmo_tools_available():
    return bool(shutil.which("tetra-rx") and shutil.which("float_to_bits"))


def _legacy_osmo_decoder_available():
    return bool(
        shutil.which("receiver1")
        and shutil.which("tetra-rx")
        and any(shutil.which(cmd) for cmd in ("demod_float", "float_to_bits"))
    )


_TETRA_RX_AUDIO_CACHE = None


def _tetra_rx_supports_audio():
    global _TETRA_RX_AUDIO_CACHE
    if _TETRA_RX_AUDIO_CACHE is not None:
        return _TETRA_RX_AUDIO_CACHE
    executable = shutil.which("tetra-rx")
    if not executable:
        _TETRA_RX_AUDIO_CACHE = False
        return False
    try:
        result = subprocess.run(
            [executable, "-h"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        _TETRA_RX_AUDIO_CACHE = False
        return False
    output = result.stdout or ""
    _TETRA_RX_AUDIO_CACHE = bool(re.search(r"(^|\s)-a(\s|,|$)", output))
    return _TETRA_RX_AUDIO_CACHE


def _legacy_audio_decoder_available():
    return _legacy_osmo_decoder_available() and _tetra_rx_supports_audio()


TETRA_DEFAULT_RANGES = [
    ("380-385 MHz (BOS Unterband)", 380e6, 385e6),
    ("390-395 MHz (BOS Oberband/Basis)", 390e6, 395e6),
    ("406,1-410 MHz (BOS DMO)", 406.1e6, 410e6),
    ("410-420 MHz (Bündelfunk Unterband)", 410e6, 420e6),
    ("420-430 MHz (Bündelfunk Oberband/Basis)", 420e6, 430e6),
    ("430-440 MHz (Amateurfunk 70 cm)", 430e6, 440e6),
    ("440-443 MHz (Bündelfunk Unterband)", 440e6, 443e6),
    ("445-448 MHz (Bündelfunk Oberband/Basis)", 445e6, 448e6),
]
TETRA_SCAN_BIN_HZ = 12_500
TETRA_CHANNEL_RASTER_HZ = 12_500


def _terminate_process_list(procs):
    for proc in procs:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
    for proc in procs:
        if not proc:
            continue
        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _classify_tetra_lines(lines, bits_size=0):
    crc_ok = 0
    unit_ok = 0
    sysinfo = 0
    resource = 0
    encrypted = False
    talkgroups = set()

    for line in lines:
        if re.search(r"CRC COMP:\s*0x[0-9A-Fa-f]+\s+OK\b", line):
            crc_ok += 1
        if re.search(r"\bTMV-UNITDATA\.ind\b.*\bCRC=1\b", line):
            unit_ok += 1
        if "BNCH SYSINFO" in line or "SYSINFO PDU" in line:
            sysinfo += 1
        if "RESOURCE" in line:
            resource += 1
        if re.search(r"\b(?:Encr=|ENCRYPTED|CACH|LIP)\b", line, re.IGNORECASE):
            encrypted = True
        talkgroups.update(extract_talkgroup_ids(line))

    confirmed = bool(crc_ok or unit_ok or sysinfo)
    if confirmed:
        details = []
        if crc_ok:
            details.append(f"CRC OK: {crc_ok}")
        if unit_ok:
            details.append(f"MAC OK: {unit_ok}")
        if sysinfo:
            details.append(f"SYSINFO: {sysinfo}")
        if resource:
            details.append(f"RESOURCE: {resource}")
        if talkgroups:
            details.append("Sprechgruppen/Adressen: " + ", ".join(sorted(talkgroups)[:8]))
        audio_status = "verschlüsselt/unklar" if encrypted else "keine Audioframes"
        return {
            "confirmed": True,
            "status": "bestätigt",
            "details": "; ".join(details) or "gültige TETRA-Bursts",
            "audio": audio_status,
            "talkgroups": sorted(talkgroups),
        }

    if lines:
        return {
            "confirmed": False,
            "status": "unklar",
            "details": "Dekoder-Ausgabe ohne gültige CRC",
            "audio": "-",
            "talkgroups": sorted(talkgroups),
        }

    if bits_size and bits_size < 4096:
        details = f"zu wenige Demodulationsbits ({bits_size} Byte)"
    else:
        details = "keine gültigen TETRA-Bursts"
    return {
        "confirmed": False,
        "status": "kein TETRA",
        "details": details,
        "audio": "-",
        "talkgroups": [],
    }


def _decoder_line_type(line: str):
    if re.search(r"CRC COMP:\s*0x[0-9A-Fa-f]+\s+OK\b", line):
        return "CRC OK"
    if "CRC COMP:" in line:
        return "CRC"
    if "BNCH SYSINFO" in line or "SYSINFO PDU" in line:
        return "Netzinfo"
    if "ACCESS-ASSIGN" in line:
        return "Zugriff"
    if "RESOURCE" in line:
        return "Ressource"
    if re.search(r"\bTMV-UNITDATA\.ind\b", line):
        return "MAC"
    if "D-SDS" in line or "U-SDS" in line or re.search(r"\bSDS\b", line):
        return "SDS"
    if re.search(r"\bMM\b|LOCATION|AUTHENTICATION|ATTACH|DETACH", line, re.I):
        return "Mobilität"
    if re.search(r"\bCM\b|CALL|CONNECT|DISCONNECT", line, re.I):
        return "Rufsteuerung"
    if re.search(r"\b(?:ENCRYPTED|Encr=[1-9]|CIPHER)\b", line, re.I):
        return "Verschlüsselung"
    if "Keine gültigen TETRA-Bursts" in line or "Zu wenige Demodulationsbits" in line:
        return "Status"
    return "Rohdaten"


def _extract_sysinfo(line: str):
    match = re.search(
        r"BNCH SYSINFO\s+\(DL\s+(\d+)\s+Hz,\s+UL\s+(\d+)\s+Hz\),"
        r"\s+service_details\s+0x([0-9A-Fa-f]+)\s+(.*)",
        line,
    )
    if not match:
        return None
    rest = match.group(4).strip()
    info = {
        "dl_hz": int(match.group(1)),
        "ul_hz": int(match.group(2)),
        "service_details": "0x" + match.group(3).lower(),
    }
    cck = re.search(r"CCK ID\s+(\d+)", rest)
    hyperframe = re.search(r"Hyperframe\s+(\d+)", rest)
    if cck:
        info["cck_id"] = cck.group(1)
    if hyperframe:
        info["hyperframe"] = hyperframe.group(1)
    return info


LOG_DIR = os.path.expanduser("~")
CONFIG_FILE = os.path.expanduser("~/.tetra_gui_config.json")
logger = logging.getLogger("tetra")
handler = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "tetra.log"), when="midnight", backupCount=7, encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logger.setLevel(logging.INFO)
logger.addHandler(handler)

ERSTELLUNGSJAHR = 2026


def _copyright_text():
    aktuelles_jahr = datetime.now().year
    jahre = (
        str(ERSTELLUNGSJAHR)
        if aktuelles_jahr <= ERSTELLUNGSJAHR
        else f"{ERSTELLUNGSJAHR} - {aktuelles_jahr}"
    )
    return f"© {jahre} Erik Schauer, do1ffe@darc.de"


def list_sdr_devices():
    """Gibt eine Liste erkannter RTL-SDR-Geräte zurück."""
    devices = []
    try:
        out = subprocess.check_output(
            ["rtl_test", "-t"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=5,
            **_hidden_subprocess_kwargs(),
        )
        for line in out.splitlines():
            match = re.match(r"^\s*(\d+):\s*(.+)$", line)
            if match:
                index = int(match.group(1))
                name = match.group(2).strip()
                devices.append((name, index))
    except Exception:
        pass
    if not devices:
        try:
            out = subprocess.check_output(
                ["lsusb"],
                text=True,
                timeout=5,
                **_hidden_subprocess_kwargs(),
            )
            for line in out.splitlines():
                if "RTL" in line or "Realtek" in line:
                    label = line.strip()
                    match = re.match(r"^Bus\s+\d+\s+Device\s+\d+:\s*(.+)$", label)
                    if match:
                        label = match.group(1).strip()
                    devices.append((label, None))
        except Exception:
            pass
    return devices or [("RTL-SDR", 0)]


def extract_talkgroup_ids(line: str):
    muster = re.compile(
        r"\b(?:TGID|TG|GSSI|talkgroup|group)\s*[:=]?\s*(0x[0-9A-Fa-f]+|\d+)\b",
        re.IGNORECASE,
    )
    ids = []
    for match in muster.finditer(line):
        raw = match.group(1)
        try:
            value = int(raw, 0)
            ids.append(str(value))
        except ValueError:
            ids.append(raw)
    addr_muster = re.compile(
        r"\bAddr=(?:SSI|SMI|USSI|SSI\s+\+\s+Event\s+Label|"
        r"SMI\s+\+\s+Event\s+Label|SSI\s+\+\s+Usage\s+Marker)\("
        r"(0x[0-9A-Fa-f]+|\d+)",
        re.IGNORECASE,
    )
    for match in addr_muster.finditer(line):
        raw = match.group(1)
        try:
            value = int(raw, 0)
            text = str(value)
        except ValueError:
            text = raw
        if text not in ids:
            ids.append(text)
    return ids


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


_MAX_GAIN_CACHE = None


def _normalize_gain_setting(value):
    if value is None:
        return "max"
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in ("max", "maximum"):
        return "max"
    try:
        return float(text)
    except ValueError:
        return "max"


def _parse_gain_argument(parser: argparse.ArgumentParser, value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        parser.error("Der Gain-Wert darf nicht leer sein.")
    lowered = text.lower()
    if lowered in ("max", "maximum"):
        return "max"
    try:
        return float(text)
    except ValueError:
        parser.error("Der Gain-Wert muss eine Zahl in dB oder 'max' sein.")


def _parse_gain_values_from_rtl_test(output: str):
    gains = []
    in_section = False
    for line in output.splitlines():
        if re.search(r"gain values", line, re.IGNORECASE):
            in_section = True
        if in_section:
            gains.extend(
                float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", line)
            )
            if not line.strip():
                in_section = False
        if in_section and re.search(r"sampling", line, re.IGNORECASE):
            in_section = False
    return sorted(set(gains))


def _ermittle_max_gain():
    global _MAX_GAIN_CACHE
    if _MAX_GAIN_CACHE is not None:
        return _MAX_GAIN_CACHE
    fallback_gain = 49.6
    try:
        out = subprocess.check_output(
            ["rtl_test", "-t"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=5,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        _MAX_GAIN_CACHE = fallback_gain
        return _MAX_GAIN_CACHE
    parsed_gains = _parse_gain_values_from_rtl_test(out)
    _MAX_GAIN_CACHE = max(parsed_gains) if parsed_gains else fallback_gain
    return _MAX_GAIN_CACHE


def _resolve_gain_value(setting):
    normalized = _normalize_gain_setting(setting)
    if normalized == "max":
        return _ermittle_max_gain()
    return float(normalized)


def _available_gain_values():
    try:
        out = subprocess.check_output(
            ["rtl_test", "-t"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=5,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return []
    return _parse_gain_values_from_rtl_test(out)


def _capture_rtl_sdr_iq(
    frequency_hz: float,
    sample_rate: int,
    seconds: float,
    ppm: int,
    gain,
    device_id=None,
):
    samples = max(16_384, int(sample_rate * seconds))
    cmd = [
        "rtl_sdr",
        "-p", str(int(ppm)),
        "-g", str(_resolve_gain_value(gain)),
        "-f", str(int(frequency_hz)),
        "-s", str(int(sample_rate)),
        "-n", str(samples),
    ]
    if device_id is not None:
        cmd.extend(["-d", str(device_id)])
    cmd.append("-")
    try:
        raw = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            timeout=max(8, int(seconds) + 8),
            **_hidden_subprocess_kwargs(),
        )
    except Exception as exc:
        raise RuntimeError(f"rtl_sdr-Aufnahme fehlgeschlagen: {exc}") from exc
    if len(raw) < 4096:
        raise RuntimeError(f"rtl_sdr lieferte zu wenige IQ-Daten ({len(raw)} Byte).")
    return raw


def _estimate_reference_peak(
    reference_hz: float,
    ppm: int,
    gain,
    device_id=None,
    sample_rate: int = 1_024_000,
    seconds: float = 1.0,
    tune_offset_hz: float = 50_000.0,
    search_span_hz: float = 100_000.0,
):
    tune_hz = reference_hz - tune_offset_hz
    raw = _capture_rtl_sdr_iq(
        tune_hz,
        sample_rate,
        seconds,
        ppm,
        gain,
        device_id=device_id,
    )
    iq_u8 = np.frombuffer(raw, dtype=np.uint8)
    if iq_u8.size % 2:
        iq_u8 = iq_u8[:-1]
    clipped = float(np.mean((iq_u8 <= 1) | (iq_u8 >= 254)))
    iq = iq_u8.astype(np.float32)
    complex_iq = (iq[0::2] - 127.5) + 1j * (iq[1::2] - 127.5)
    if complex_iq.size < 16_384:
        raise RuntimeError("Zu wenige IQ-Samples für FFT-Auswertung.")

    fft_len = min(131_072, 1 << int(np.floor(np.log2(complex_iq.size))))
    fft_len = max(16_384, fft_len)
    chunk_count = max(1, min(24, complex_iq.size // fft_len))
    window = np.hanning(fft_len).astype(np.float32)
    power_linear = None
    for index in range(chunk_count):
        samples = complex_iq[index * fft_len:(index + 1) * fft_len]
        samples = samples - np.mean(samples)
        spectrum = np.fft.fftshift(np.fft.fft(samples * window))
        chunk_power = np.abs(spectrum) ** 2
        power_linear = chunk_power if power_linear is None else power_linear + chunk_power
    power_linear = power_linear / max(1, chunk_count)
    power_db = 10.0 * np.log10(power_linear + 1e-12)
    freqs = np.fft.fftshift(np.fft.fftfreq(fft_len, d=1.0 / sample_rate))

    span = max(5_000.0, float(search_span_hz))
    mask = np.abs(freqs - tune_offset_hz) <= span
    if not np.any(mask):
        mask = np.ones_like(freqs, dtype=bool)

    masked_power = power_db[mask]
    masked_freqs = freqs[mask]
    peak_index = int(np.argmax(masked_power))
    peak_db = float(masked_power[peak_index])
    noise_db = float(np.median(masked_power))
    if span >= 120_000.0:
        candidate_half_span = min(35_000.0, span / 3.0)
        channel_half_width = min(95_000.0, span * 0.55)
        offsets = np.linspace(8_000.0, channel_half_width, 80)
        candidates = np.linspace(
            tune_offset_hz - candidate_half_span,
            tune_offset_hz + candidate_half_span,
            701,
        )
        best_center = float(masked_freqs[peak_index])
        best_score = None
        for center in candidates:
            left = np.interp(center - offsets, freqs, power_db)
            right = np.interp(center + offsets, freqs, power_db)
            energy = np.mean(np.interp(center + np.linspace(-channel_half_width, channel_half_width, 100), freqs, power_db))
            asymmetry = float(np.mean(np.abs(left - right)))
            score = asymmetry - 0.02 * energy
            if best_score is None or score < best_score:
                best_score = score
                best_center = float(center)
        peak_offset_hz = best_center
    else:
        peak_offset_hz = float(masked_freqs[peak_index])
    snr_db = peak_db - noise_db
    residual_hz = peak_offset_hz - tune_offset_hz
    ppm_delta = -residual_hz / reference_hz * 1_000_000.0
    return {
        "reference_hz": float(reference_hz),
        "tune_hz": float(tune_hz),
        "expected_offset_hz": float(tune_offset_hz),
        "peak_offset_hz": peak_offset_hz,
        "residual_hz": float(residual_hz),
        "ppm_delta": float(ppm_delta),
        "peak_db": peak_db,
        "noise_db": noise_db,
        "snr_db": float(snr_db),
        "clipped": clipped,
        "samples": int(fft_len * chunk_count),
    }


def _qt_xcb_verfuegbar() -> bool:
    if not sys.platform.startswith("linux"):
        return True

    qt_platform = os.environ.get("QT_QPA_PLATFORM", "").strip()
    if qt_platform and qt_platform != "xcb":
        return True

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False

    fehlende_libs = [
        lib for lib in ("xcb", "xkbcommon-x11") if ctypes.util.find_library(lib) is None
    ]
    if fehlende_libs:
        return False

    plugin_pfade = []
    env_pfade = [pfad for pfad in os.environ.get("QT_PLUGIN_PATH", "").split(os.pathsep) if pfad]
    plugin_pfade.extend(env_pfade)
    plugin_pfade.append(QtCore.QLibraryInfo.location(QtCore.QLibraryInfo.PluginsPath))

    for basis in filter(None, plugin_pfade):
        plattform_dir = os.path.join(basis, "platforms")
        if not os.path.isdir(plattform_dir):
            continue
        try:
            for datei in os.listdir(plattform_dir):
                if datei.startswith("libqxcb.so"):
                    return True
        except OSError:
            continue
    return False


def _parse_frequenzbereich(parser: argparse.ArgumentParser, werte):
    if werte is None:
        return None
    start_mhz, end_mhz = werte
    if start_mhz <= 0 or end_mhz <= 0 or end_mhz <= start_mhz:
        parser.error("Der Frequenzbereich muss zwei positive Werte in MHz (Start < Ende) enthalten.")
    return start_mhz, end_mhz


def _resolve_device(geraete, name, index):
    if index is not None:
        for label, device_id in geraete:
            if device_id == index:
                return label, index
    if name:
        for label, device_id in geraete:
            if label == name:
                return label, device_id
    if geraete:
        return geraete[0]
    return "RTL-SDR", None


def _starte_cli_modus(fehlermeldung: str) -> None:
    print(fehlermeldung, file=sys.stderr)
    print("Starte das Programm im Kommandozeilenmodus.", file=sys.stderr)
    print("\n=== TETRA-Decoder (CLI-Modus) ===")
    print("Hinweis: Für die grafische Oberfläche müssen X11/Qt-xcb verfügbar sein.")
    print("\nGefundene SDR-Geräte:")
    geraete = list_sdr_devices()
    for name, index in geraete:
        if index is None:
            print(f"- {name}")
        else:
            print(f"- {name} (Index {index})")
    print("\nBeende den CLI-Modus mit Strg+C.")

    config = load_config()
    parser = argparse.ArgumentParser(
        prog="tetra-decode",
        description="TETRA-Decoder im CLI-Modus",
    )
    parser.add_argument(
        "--geraet-name",
        help="Name des SDR-Geräts (wie in der Geräte-Liste angezeigt).",
    )
    parser.add_argument(
        "--geraet-index",
        type=int,
        help="Index des SDR-Geräts (z. B. 0).",
    )
    parser.add_argument(
        "--ppm",
        type=int,
        help="PPM-Korrektur für den SDR-Empfänger.",
    )
    parser.add_argument(
        "--gain",
        help="Gain in dB oder 'max' für den höchsten verfügbaren Gain-Wert.",
    )
    parser.add_argument(
        "--frequenzbereich",
        nargs=2,
        type=float,
        metavar=("START_MHZ", "ENDE_MHZ"),
        help="Frequenzbereich in MHz (z. B. 380 430).",
    )
    parser.add_argument(
        "--filter-regex",
        help="Regex-Filter f\u00fcr die Ausgabe im CLI-Modus.",
    )
    parser.add_argument(
        "--talkgroup",
        action="append",
        help="Sprechgruppen-ID f\u00fcr die Anzeige (mehrfach nutzbar).",
    )
    parser.add_argument(
        "--talkgroups-file",
        help="Datei mit Sprechgruppen-IDs (eine pro Zeile oder kommagetrennt).",
    )
    parser.add_argument(
        "--export-csv",
        metavar="PFAD",
        help="CSV-Export der erkannten Zellen in die angegebene Datei.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Gibt beim Beenden eine kurze Statistik aus.",
    )
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument(
        "--auto-dekodierung",
        dest="auto_dekodierung",
        action="store_true",
        help="Automatische Dekodierung nach der Frequenzauswahl aktivieren.",
    )
    auto_group.add_argument(
        "--kein-auto-dekodierung",
        dest="auto_dekodierung",
        action="store_false",
        help="Automatische Dekodierung deaktivieren.",
    )
    audio_group = parser.add_mutually_exclusive_group()
    audio_group.add_argument(
        "--audio-wiedergabe",
        dest="audio_wiedergabe",
        action="store_true",
        help="Dekodiertes Audio wiedergeben.",
    )
    audio_group.add_argument(
        "--kein-audio-wiedergabe",
        dest="audio_wiedergabe",
        action="store_false",
        help="Audio-Wiedergabe deaktivieren.",
    )
    record_group = parser.add_mutually_exclusive_group()
    record_group.add_argument(
        "--audio-record",
        dest="audio_record",
        action="store_true",
        help="Dekodiertes Audio als WAV speichern (setzt Audio-Wiedergabe voraus).",
    )
    record_group.add_argument(
        "--kein-audio-record",
        dest="audio_record",
        action="store_false",
        help="Audio-Aufnahme deaktivieren.",
    )
    parser.set_defaults(auto_dekodierung=None, audio_wiedergabe=None, audio_record=None)

    args = parser.parse_args()
    override_config = False

    ppm = config.get("ppm", 0)
    if args.ppm is not None:
        ppm = args.ppm
        config["ppm"] = ppm
        override_config = True

    gain_setting = _normalize_gain_setting(config.get("gain", "max"))
    if args.gain is not None:
        gain_setting = _parse_gain_argument(parser, args.gain)
        config["gain"] = gain_setting
        override_config = True

    frequenzbereich = _parse_frequenzbereich(parser, args.frequenzbereich)
    if frequenzbereich is None:
        start_mhz = config.get("cli_freq_start_mhz")
        end_mhz = config.get("cli_freq_end_mhz")
        if start_mhz is not None and end_mhz is not None:
            frequenzbereich = (float(start_mhz), float(end_mhz))
        else:
            frequenzbereich = (380.0, 430.0)
    else:
        config["cli_freq_start_mhz"] = frequenzbereich[0]
        config["cli_freq_end_mhz"] = frequenzbereich[1]
        override_config = True

    auto_dekodierung = config.get("cli_auto_decode", True)
    if args.auto_dekodierung is not None:
        auto_dekodierung = args.auto_dekodierung
        config["cli_auto_decode"] = auto_dekodierung
        override_config = True

    audio_wiedergabe = config.get("cli_play_audio", False)
    if args.audio_wiedergabe is not None:
        audio_wiedergabe = args.audio_wiedergabe
        config["cli_play_audio"] = audio_wiedergabe
        override_config = True

    audio_record = config.get("cli_record_audio", False)
    if args.audio_record is not None:
        audio_record = args.audio_record
        config["cli_record_audio"] = audio_record
        override_config = True

    filter_regex = config.get("cli_filter_regex", "")
    if args.filter_regex is not None:
        filter_regex = args.filter_regex
        config["cli_filter_regex"] = filter_regex
        override_config = True

    selected_talkgroups = set()
    gespeicherte_talkgroups = config.get("selected_talkgroups", [])
    if isinstance(gespeicherte_talkgroups, list):
        selected_talkgroups.update(str(tg_id) for tg_id in gespeicherte_talkgroups)

    def _parse_talkgroup_tokens(tokens):
        ids = set()
        for token in filter(None, tokens):
            token = str(token).strip()
            if not token:
                continue
            found = extract_talkgroup_ids(token)
            if found:
                ids.update(found)
            else:
                for part in re.split(r"[,\s]+", token):
                    part = part.strip()
                    if part:
                        ids.add(part)
        return ids

    if args.talkgroup:
        selected_talkgroups = _parse_talkgroup_tokens(args.talkgroup)
        config["selected_talkgroups"] = sorted(selected_talkgroups)
        override_config = True

    if args.talkgroups_file:
        file_ids = set()
        try:
            with open(args.talkgroups_file, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    file_ids.update(_parse_talkgroup_tokens([line]))
        except OSError as exc:
            print(f"Warnung: Konnte Sprechgruppen-Datei nicht lesen: {exc}", file=sys.stderr)
        else:
            selected_talkgroups = file_ids
            config["selected_talkgroups"] = sorted(selected_talkgroups)
            override_config = True

    device_name = args.geraet_name if args.geraet_name is not None else config.get("cli_device_name")
    device_id = args.geraet_index if args.geraet_index is not None else config.get("cli_device_id")
    if isinstance(device_id, str) and device_id.strip().isdigit():
        device_id = int(device_id)
    if args.geraet_name is not None:
        config["cli_device_name"] = device_name
        override_config = True
    if args.geraet_index is not None:
        config["cli_device_id"] = device_id
        override_config = True

    device_name, device_id = _resolve_device(geraete, device_name, device_id)

    if override_config:
        save_config(config)

    app = QtCore.QCoreApplication([])

    class CLIRunner(QtCore.QObject):
        def __init__(
            self,
            device_name: str,
            device_id: int | None,
            ppm: int,
            gain_setting,
            freq_range_mhz: tuple[float, float],
            auto_decode: bool,
            play_audio: bool,
            record_audio: bool,
            filter_regex: str,
            selected_talkgroups: set[str],
            export_csv_path: str | None,
            stats_enabled: bool,
        ):
            super().__init__()
            self._device_name = device_name
            self._device_id = device_id
            self._scanner = SDRScanner(
                device=device_name,
                ppm=ppm,
                gain=gain_setting,
                parent=self,
            )
            self._decoder = TetraDecoder(ppm=ppm, parent=self)
            self._decoder.device_id = device_id
            self._decoder.gain = gain_setting
            self._scanner.device_id = device_id
            self._current_frequency = None
            self._last_peak = None
            self._last_spectrum = None
            self._freq_range_mhz = freq_range_mhz
            self._auto_decode = auto_decode
            self._play_audio = play_audio
            self._record_audio = record_audio
            self._filter_regex = filter_regex
            self.selected_talkgroups = selected_talkgroups
            self._export_csv_path = export_csv_path
            self._stats_enabled = stats_enabled
            self.cells = {}
            self.packet_counts = {}
            self.talkgroups = {}
            self._manual_lock = False
            self._stdin_thread = None
            self._dec_audio_player = None
            if self._play_audio:
                self._dec_audio_player = DecodedAudioPlayer(parent=self)
                self._decoder.audio.connect(self._dec_audio_player.process)

            self._scanner.spectrum_ready.connect(self._handle_spectrum)
            self._scanner.frequency_selected.connect(self._handle_frequency)
            self._decoder.output.connect(self._handle_decoder_output)
            self._decoder.finished.connect(self._decoder_finished)

        def start(self):
            start_hz = self._freq_range_mhz[0] * 1e6
            end_hz = self._freq_range_mhz[1] * 1e6
            self._scanner.start(start_hz, end_hz)
            self._start_cli_input_thread()

        def stop(self):
            self._scanner.stop()
            self._decoder.stop()
            if self._dec_audio_player:
                self._dec_audio_player.stop()

        def finalize(self):
            if self._export_csv_path:
                self.export_cells_csv(self._export_csv_path)
            if self._stats_enabled:
                self.print_stats()

        @QtCore.pyqtSlot(np.ndarray, np.ndarray)
        def _handle_spectrum(self, freqs, powers):
            if freqs is None or powers is None or len(freqs) == 0 or len(powers) == 0:
                return
            self._last_spectrum = (np.array(freqs, copy=True), np.array(powers, copy=True))
            max_idx = int(np.argmax(powers))
            freq = float(freqs[max_idx])
            power = float(powers[max_idx])
            self._last_peak = (freq, power)
            print(
                f"Frequenz {freq/1e6:.3f} MHz, Leistung {power:.1f} dB",
                flush=True,
            )

        @QtCore.pyqtSlot(float)
        def _handle_frequency(self, freq):
            if self._manual_lock:
                print(
                    f"Automatische Frequenz ignoriert (Manuell aktiv): {freq/1e6:.3f} MHz",
                    flush=True,
                )
                return
            if self._current_frequency and abs(freq - self._current_frequency) < 1:
                return
            self._set_frequency_and_process(freq, source="scan")

        def _set_frequency_and_process(self, freq: float, source: str = "manual"):
            self._current_frequency = freq
            if source == "manual":
                print(f"Manuell ausgewählt: {freq/1e6:.3f} MHz", flush=True)
            else:
                print(f"Gewählte Frequenz: {freq/1e6:.3f} MHz", flush=True)
            if not self._auto_decode:
                print(
                    f"Frequenz {freq/1e6:.3f} MHz erkannt (Auto-Dekodierung aus).",
                    flush=True,
                )
                return
            print(f"Starte Dekoder auf {freq/1e6:.3f} MHz", flush=True)
            self._scanner.stop()
            self._decoder.stop()
            if self._dec_audio_player:
                self._dec_audio_player.start(record=self._record_audio)
            self._decoder.start(freq)

        @QtCore.pyqtSlot(str)
        def _handle_decoder_output(self, line: str):
            if not self._line_matches_selected_talkgroup(line):
                return
            if self._filter_regex:
                try:
                    if not re.search(self._filter_regex, line):
                        return
                except re.error:
                    pass
            print(line, flush=True)
            self.parse_cell_info(line)
            self.parse_packet_type(line)
            self.parse_talkgroups(line)
            for tg_id in extract_talkgroup_ids(line):
                print(f"Talkgroup {tg_id} empfangen", flush=True)

        def _line_matches_selected_talkgroup(self, line: str) -> bool:
            if not self.selected_talkgroups:
                return True
            ids = extract_talkgroup_ids(line)
            if not ids:
                return False
            return any(tg_id in self.selected_talkgroups for tg_id in ids)

        @QtCore.pyqtSlot()
        def _decoder_finished(self):
            print("Dekoder gestoppt.", flush=True)
            if self._dec_audio_player:
                self._dec_audio_player.stop()

        def _set_manual_lock(self, enabled: bool):
            self._manual_lock = enabled
            status = "Manuell" if enabled else "Automatisch"
            print(f"Modus gewechselt: {status}", flush=True)

        def _start_cli_input_thread(self):
            if self._stdin_thread and self._stdin_thread.is_alive():
                return
            self._stdin_thread = threading.Thread(
                target=self._cli_input_loop,
                daemon=True,
            )
            self._stdin_thread.start()

        def _cli_input_loop(self):
            while True:
                try:
                    line = sys.stdin.readline()
                except Exception:
                    break
                if not line:
                    break
                cmd = line.strip()
                if not cmd:
                    continue
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_handle_cli_command",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, cmd),
                )

        @QtCore.pyqtSlot(str)
        def _handle_cli_command(self, command: str):
            try:
                parts = shlex.split(command)
            except ValueError as exc:
                print(f"Ungültige Eingabe: {exc}", flush=True)
                return
            if not parts:
                return
            cmd = parts[0].lower()
            if cmd == "lock":
                self._set_manual_lock(True)
                return
            if cmd == "unlock":
                self._set_manual_lock(False)
                return
            if cmd == "freq":
                if len(parts) < 2:
                    print("Bitte eine Frequenz in MHz angeben: freq <MHz>", flush=True)
                    return
                try:
                    mhz = float(parts[1])
                except ValueError:
                    print("Ungültige Frequenz. Beispiel: freq 395.625", flush=True)
                    return
                self._set_manual_lock(True)
                self._set_frequency_and_process(mhz * 1e6, source="manual")
                return
            if cmd == "save-png":
                png_dir = None
                rest = parts[1:]
                for idx, arg in enumerate(rest):
                    if arg.startswith("--png-dir="):
                        png_dir = arg.split("=", 1)[1] or None
                        continue
                    if arg == "--png-dir":
                        if idx + 1 >= len(rest):
                            print("Bitte Verzeichnis nach --png-dir angeben.", flush=True)
                            return
                        png_dir = rest[idx + 1]
                self.save_spectrum_png(png_dir)
                return
            print(
                "Unbekannter Befehl. Verfügbar: lock, unlock, freq <MHz>, save-png [--png-dir <Pfad>]",
                flush=True,
            )

        def save_spectrum_png(self, png_dir: str | None = None):
            if not self._last_spectrum:
                print("Kein Spektrum zum Speichern vorhanden.", flush=True)
                return
            freqs, powers = self._last_spectrum
            ziel = png_dir or os.path.expanduser("~/TetraScans")
            os.makedirs(ziel, exist_ok=True)
            fname = datetime.now().strftime("scan_%Y%m%d_%H%M%S.png")
            fig = Figure(figsize=(8, 4))
            ax = fig.add_subplot(1, 1, 1)
            ax.plot(freqs / 1e6, powers, linewidth=1.0)
            ax.set_xlabel("Frequenz (MHz)")
            ax.set_ylabel("Leistung (dB)")
            ax.set_title("Spektrum")
            ax.grid(True, linestyle="--", alpha=0.4)
            fig.tight_layout()
            fig.savefig(os.path.join(ziel, fname))
            print(f"Spektrum gespeichert: {os.path.join(ziel, fname)}", flush=True)

        def export_cells_csv(self, path: str):
            try:
                with open(path, "w") as fh:
                    fh.write("Zelle,LAC,MCC,MNC,Frequenz\n")
                    for cell in self.cells.values():
                        fh.write(
                            f"{cell.get('cell','')},{cell.get('lac','')},"
                            f"{cell.get('mcc','')},{cell.get('mnc','')},{cell.get('freq','')}\n"
                        )
            except OSError as exc:
                print(f"Konnte CSV nicht schreiben: {exc}", file=sys.stderr, flush=True)
            else:
                print(f"CSV-Export abgeschlossen: {path}", flush=True)

        def print_stats(self):
            print("\nStatistik (CLI):", flush=True)
            print(f"- Zellen erkannt: {len(self.cells)}", flush=True)
            if self.packet_counts:
                paket_teile = ", ".join(
                    f"{typ}: {anzahl}"
                    for typ, anzahl in sorted(self.packet_counts.items())
                )
                print(f"- Pakettypen: {paket_teile}", flush=True)
            else:
                print("- Pakettypen: keine", flush=True)
            if self.talkgroups:
                print(f"- Sprechgruppen: {len(self.talkgroups)}", flush=True)
                haeufig = sorted(
                    self.talkgroups.items(),
                    key=lambda item: item[1].get("count", 0),
                    reverse=True,
                )[:5]
                if haeufig:
                    info = ", ".join(
                        f"{tg_id} ({werte.get('count', 0)})"
                        for tg_id, werte in haeufig
                    )
                    print(f"  Top 5: {info}", flush=True)
            else:
                print("- Sprechgruppen: keine", flush=True)

        def parse_cell_info(self, line: str):
            m = re.search(
                r"Cell\s*ID[:=]\s*(\w+).*LAC[:=]\s*(\w+).*MCC[:=]\s*(\d+).*MNC[:=]\s*(\d+)",
                line,
                re.I,
            )
            if not m:
                return
            freq_text = ""
            if self._current_frequency is not None:
                freq_text = f"{self._current_frequency/1e6:.3f}"
            cell = {
                "cell": m.group(1),
                "lac": m.group(2),
                "mcc": m.group(3),
                "mnc": m.group(4),
                "freq": freq_text,
            }
            self.cells[cell["cell"]] = cell

        def parse_packet_type(self, line: str):
            types = ["SDS", "MM", "CM"]
            for t in types:
                if t in line:
                    self.packet_counts[t] = self.packet_counts.get(t, 0) + 1
                    break

        def parse_talkgroups(self, line: str):
            ids = extract_talkgroup_ids(line)
            if not ids:
                return
            now = datetime.now()
            for tg_id in ids:
                info = self.talkgroups.get(tg_id, {"count": 0, "last_seen": now})
                info["count"] = info.get("count", 0) + 1
                info["last_seen"] = now
                self.talkgroups[tg_id] = info

    if device_id is None:
        device_text = "ohne Index"
    else:
        device_text = f"Index {device_id}"
    print(
        "CLI-Start mit Gerät "
        f"{device_text} ({device_name}), "
        f"PPM {ppm}, "
        f"Frequenzbereich {frequenzbereich[0]:.1f}-{frequenzbereich[1]:.1f} MHz, "
        f"Gain {_resolve_gain_value(gain_setting):.1f} dB, "
        f"Auto-Dekodierung {'an' if auto_dekodierung else 'aus'}, "
        f"Audio {'an' if audio_wiedergabe else 'aus'}"
        + (", Aufnahme an" if audio_record else ""),
        flush=True,
    )

    runner = CLIRunner(
        device_name,
        device_id,
        ppm,
        gain_setting,
        frequenzbereich,
        auto_dekodierung,
        audio_wiedergabe,
        audio_record,
        filter_regex,
        selected_talkgroups,
        args.export_csv,
        args.stats,
    )
    runner.start()
    try:
        while True:
            app.processEvents()
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nCLI-Modus beendet.")
        runner.stop()
        runner.finalize()


class SetupWorker(QtCore.QThread):
    """Prüft externe Werkzeuge und Python-Module und installiert sie."""

    log = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    REQUIRED_CMDS = {
        "rtl_power": "rtl-sdr",
        "rtl_fm": "rtl-sdr",
        "rtl_sdr": "rtl-sdr",
        "rtl_test": "rtl-sdr",
    }
    DEMOD_ALTERNATIVES = ("demod_float", "float_to_bits")
    DEMOD_PKG = "osmocom-tetra"

    PY_MODULES = ["pyaudio", "numpy", "matplotlib", "PyQt5", "requests", "qdarkstyle"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._install_script_ran = False

    @classmethod
    def detect_missing_requirements(cls):
        """Gibt ein Tupel mit fehlenden Befehlen, Modulen und optionalen Werkzeugen zurück."""
        missing_cmds = [cmd for cmd in cls.REQUIRED_CMDS if not shutil.which(cmd)]
        if not (
            _official_osmo_decoder_available()
            or _legacy_osmo_decoder_available()
            or _native_osmo_tools_available()
        ):
            missing_cmds.append("osmocom-tetra decoder")
        missing_mods = [mod for mod in cls.PY_MODULES if not cls._has_module(mod)]
        missing_optional = []

        if sys.platform.startswith("win") and shutil.which("choco") and not shutil.which("zadig"):
            missing_optional.append("zadig")

        return missing_cmds, missing_mods, missing_optional

    @staticmethod
    def decoder_notice():
        if _official_osmo_decoder_available() or _legacy_osmo_decoder_available():
            return None
        if _native_osmo_tools_available():
            return (
                "Osmocom-TETRA-Binaries gefunden. Fuer Live-Demodulation wird "
                "zusaetzlich GNU Radio Python oder WSL mit GNU Radio benoetigt."
            )
        return None

    @staticmethod
    def _has_module(name: str) -> bool:
        try:
            importlib.import_module(name)
            return True
        except Exception:
            return False

    def run(self):
        for cmd, pkg in self.REQUIRED_CMDS.items():
            if shutil.which(cmd):
                continue
            if self._run_install_script() and shutil.which(cmd):
                continue
            if sys.platform.startswith("linux"):
                self.log.emit(f"Installiere {cmd} über apt ({pkg})")
                self._run_cmd(["sudo", "apt-get", "install", "-y", pkg])
            elif sys.platform.startswith("win"):
                if pkg in ("rtl-sdr", "osmocom-tetra"):
                    if self._run_install_script() and shutil.which(cmd):
                        continue
                    self.log.emit(f"{cmd} fehlt - bitte {pkg} manuell installieren")
                elif shutil.which("choco"):
                    self.log.emit(f"Installiere {cmd} über choco ({pkg})")
                    self._run_cmd(["choco", "install", "-y", pkg])
                else:
                    self.log.emit(f"{cmd} fehlt - bitte {pkg} manuell installieren")
            else:
                self.log.emit(f"{cmd} fehlt - bitte {pkg} manuell installieren")

        if not (_official_osmo_decoder_available() or _legacy_osmo_decoder_available()):
            if _native_osmo_tools_available():
                self.log.emit(
                    "Osmocom-TETRA-Binaries gefunden. Fuer Live-Demodulation wird "
                    "zusaetzlich GNU Radio Python oder WSL mit GNU Radio benoetigt."
                )
            elif self._run_install_script() and (
                _official_osmo_decoder_available() or _legacy_osmo_decoder_available()
            ):
                pass
            elif sys.platform.startswith("linux"):
                self.log.emit(
                    "osmocom-tetra Decoder fehlt. Bitte install.sh ausfuehren "
                    "oder GNU Radio, tetra-rx und float_to_bits installieren."
                )
            elif sys.platform.startswith("win"):
                self.log.emit(
                    "osmocom-tetra Decoder fehlt. Der Windows-Installer bringt "
                    "tetra-rx/float_to_bits mit; fuer Live-Demodulation wird "
                    "zusaetzlich GNU Radio Python oder WSL benoetigt."
                )
            else:
                self.log.emit("osmocom-tetra Decoder fehlt - bitte manuell installieren.")

        for mod in self.PY_MODULES:
            if self._has_module(mod):
                continue
            if self._run_install_script() and self._has_module(mod):
                continue
            self.log.emit(f"Installiere Python-Modul {mod}")
            self._run_cmd([sys.executable, "-m", "pip", "install", mod])

        if sys.platform.startswith("win") and shutil.which("choco") and not shutil.which("zadig"):
            if self._run_install_script() and shutil.which("zadig"):
                pass
            else:
                self.log.emit("Installiere Zadig über choco")
                self._run_cmd(["choco", "install", "-y", "zadig"])

        setup_file = os.path.expanduser("~/.tetra_setup_done")
        try:
            with open(setup_file, "w"):
                pass
        except Exception:
            pass
        self.finished.emit()

    def _run_cmd(self, cmd):
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **_hidden_subprocess_kwargs(),
            )
            for line in proc.stdout:
                self.log.emit(line.rstrip())
            proc.wait()
        except Exception as exc:
            self.log.emit(f"Konnte {' '.join(cmd)} nicht ausführen: {exc}")

    def _run_install_script(self) -> bool:
        if self._install_script_ran:
            return False

        if sys.platform.startswith("linux"):
            script = os.path.join(PROJECT_ROOT, "install.sh")
            if not os.path.exists(script):
                return False
            self._install_script_ran = True
            self.log.emit("Starte install.sh, um fehlende Abhängigkeiten zu installieren...")
            self._run_cmd([script])
            return True

        if sys.platform.startswith("win"):
            script = os.path.join(PROJECT_ROOT, "install.ps1")
            if not os.path.exists(script):
                return False
            try:
                is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                is_admin = False
            if not is_admin:
                self.log.emit(
                    "install.ps1 benoetigt Administratorrechte. Starte die App "
                    "als Administrator oder nutze den Windows-Installer erneut."
                )
                return False
            self._install_script_ran = True
            self.log.emit("Starte install.ps1, um fehlende Abhängigkeiten zu installieren...")
            self._run_cmd([
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script,
            ])
            return True

        return False



class CalibrationWorker(QtCore.QThread):
    """Berechnet PPM und RF-Gain anhand eines bekannten Referenzsignals."""

    log = QtCore.pyqtSignal(str)
    ppm_ready = QtCore.pyqtSignal(dict)
    gain_ready = QtCore.pyqtSignal(dict)

    def __init__(
        self,
        mode: str,
        reference_hz: float,
        search_span_hz: float,
        device_id=None,
        ppm: int = 0,
        gain="max",
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.reference_hz = reference_hz
        self.search_span_hz = search_span_hz
        self.device_id = device_id
        self.ppm = ppm
        self.gain = gain
        self._running = threading.Event()

    def stop(self):
        self._running.clear()

    def run(self):
        self._running.set()
        try:
            if not shutil.which("rtl_sdr"):
                self.log.emit("rtl_sdr nicht gefunden; Kalibrierung nicht möglich.")
                return

            gain_for_ppm = self.gain
            if self.mode in ("gain", "both"):
                gain_result = self._auto_gain()
                if gain_result and self._running.is_set():
                    gain_for_ppm = gain_result["gain"]
                    self.gain_ready.emit(gain_result)

            if self.mode in ("ppm", "both") and self._running.is_set():
                self._auto_ppm(gain_for_ppm)
        finally:
            self._running.clear()

    def _auto_ppm(self, gain):
        self.log.emit(
            f"PPM-Kalibrierung auf {self.reference_hz/1e6:.4f} MHz startet..."
        )
        result = _estimate_reference_peak(
            self.reference_hz,
            self.ppm,
            gain,
            device_id=self.device_id,
            seconds=3.0,
            tune_offset_hz=self._tune_offset_hz(),
            search_span_hz=self.search_span_hz,
        )
        exact_ppm = self.ppm + result["ppm_delta"]
        result["old_ppm"] = int(self.ppm)
        result["new_ppm_exact"] = float(exact_ppm)
        result["new_ppm"] = int(round(exact_ppm))
        result["gain"] = float(_resolve_gain_value(gain))
        if result["snr_db"] < 8.0:
            result["warning"] = "Referenzsignal schwach; Ergebnis prüfen."
        self.ppm_ready.emit(result)

    def _auto_gain(self):
        gains = _available_gain_values()
        if not gains:
            gains = [0.0, 10.0, 20.0, 30.0, 40.0, _ermittle_max_gain()]
        gains = sorted(set(float(gain) for gain in gains))
        if len(gains) > 9:
            indices = np.linspace(0, len(gains) - 1, 9).round().astype(int)
            gains = [gains[int(index)] for index in indices]

        self.log.emit(
            f"RF-Gain-Automatik auf {self.reference_hz/1e6:.4f} MHz testet "
            f"{len(gains)} Stufen..."
        )
        best = None
        measurements = []
        for gain in gains:
            if not self._running.is_set():
                break
            try:
                result = _estimate_reference_peak(
                    self.reference_hz,
                    self.ppm,
                    gain,
                    device_id=self.device_id,
                    seconds=0.55,
                    tune_offset_hz=self._tune_offset_hz(),
                    search_span_hz=self.search_span_hz,
                )
            except Exception as exc:
                self.log.emit(f"Gain {gain:.1f} dB konnte nicht gemessen werden: {exc}")
                continue
            score = result["snr_db"] - result["clipped"] * 1000.0
            result.update({"gain": float(gain), "score": float(score)})
            measurements.append(result)
            self.log.emit(
                f"Gain {gain:.1f} dB: SNR {result['snr_db']:.1f} dB, "
                f"Clipping {result['clipped']*100:.2f}%"
            )
            if best is None or score > best["score"]:
                best = result

        if best is None:
            self.log.emit("RF-Gain-Automatik fand keine brauchbare Messung.")
            return None

        return {
            "gain": float(best["gain"]),
            "snr_db": float(best["snr_db"]),
            "clipped": float(best["clipped"]),
            "score": float(best["score"]),
            "measurements": len(measurements),
            "reference_hz": float(self.reference_hz),
        }

    def _tune_offset_hz(self):
        return min(250_000.0, max(50_000.0, float(self.search_span_hz) * 1.5))


class SDRScanner(QtCore.QObject):
    """Scannt einen Frequenzbereich mit rtl_power und sendet Spektrumsdaten."""

    spectrum_ready = QtCore.pyqtSignal(np.ndarray, np.ndarray)
    frequency_selected = QtCore.pyqtSignal(float)

    def __init__(self, device: str, ppm: int = 0, gain=None, parent=None):
        super().__init__(parent)
        self.device = device
        self.device_id = None
        self.ppm = ppm
        self.gain = gain
        self._thread = None
        self._running = threading.Event()
        self._process = None

    def start(self, f_start=380e6, f_end=430e6, bin_size=10e3):
        """Startet den Scan mit rtl_power."""
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._scan,
                                         args=(f_start, f_end, bin_size),
                                         daemon=True)
        self._thread.start()

    def stop(self):
        self._running.clear()
        if self._process:
            self._process.terminate()
            self._process = None
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def _scan(self, f_start, f_end, bin_size):
        gain_value = _resolve_gain_value(self.gain)
        cmd = [
            "rtl_power",
            "-p", str(self.ppm),
            "-g", str(gain_value),
            f"-f{f_start/1e6:.0f}M:{f_end/1e6:.0f}M:{int(bin_size)}",
            "-i", "1", "-"
        ]
        if self.device_id is not None:
            cmd.extend(["-d", str(self.device_id)])
        try:
            self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL,
                                             text=True,
                                             **_hidden_subprocess_kwargs())
        except (FileNotFoundError, OSError):
            # rtl_power nicht gefunden oder nicht startbar, Daten simulieren
            self._simulate_scan(f_start, f_end, bin_size)
            return

        emitted_data = False
        while self._running.is_set():
            line = self._process.stdout.readline()
            if not line:
                break
            parts = line.strip().split(',')
            if len(parts) < 7:
                continue
            try:
                # rtl_power gibt Startfrequenz (parts[2]), Schrittweite (parts[4]) und Leistungswerte aus
                f0 = float(parts[2])
                bin_hz = float(parts[4])
                powers = np.array(list(map(float, parts[6:])))
            except ValueError:
                continue
            if powers.size == 0:
                continue
            freqs = f0 + bin_hz * np.arange(len(powers))
            self.spectrum_ready.emit(freqs, powers)
            emitted_data = True
            max_idx = np.argmax(powers)
            self.frequency_selected.emit(freqs[max_idx])

        should_simulate = self._running.is_set() and not emitted_data
        if self._process:
            if self._process.poll() is None:
                self._process.terminate()
            self._process = None
        if should_simulate:
            logger.info("rtl_power lieferte keine Spektrumsdaten; nutze Simulationsdaten.")
            self._simulate_scan(f_start, f_end, bin_size)

    def _simulate_scan(self, f_start, f_end, bin_size):
        freqs = np.arange(f_start, f_end, bin_size)
        while self._running.is_set():
            noise = np.random.normal(-80, 5, size=len(freqs))
            peak_idx = np.random.randint(0, len(freqs))
            noise[peak_idx] += 20
            self.spectrum_ready.emit(freqs, noise)
            self.frequency_selected.emit(freqs[peak_idx])
            QtCore.QThread.sleep(1)


class TetraSignalSearchWorker(QtCore.QThread):
    """Sucht Träger im TETRA-Raster und validiert sie mit tetra-rx."""

    log = QtCore.pyqtSignal(str)
    candidate = QtCore.pyqtSignal(dict)

    def __init__(
        self,
        ranges,
        device_id=None,
        ppm: int = 0,
        gain="max",
        scan_seconds: int = 5,
        probe_seconds: int = 6,
        max_candidates: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.ranges = list(ranges)
        self.device_id = device_id
        self.ppm = ppm
        self.gain = gain
        self.scan_seconds = scan_seconds
        self.probe_seconds = probe_seconds
        self.max_candidates = max_candidates
        self._running = threading.Event()
        self._procs = []
        self._proc_lock = threading.RLock()

    def stop(self):
        self._running.clear()
        self._terminate_processes()

    def _add_proc(self, proc):
        with self._proc_lock:
            self._procs.append(proc)

    def _terminate_processes(self):
        with self._proc_lock:
            procs = list(self._procs)
            self._procs = []
        _terminate_process_list(procs)

    def run(self):
        self._running.set()
        try:
            if not shutil.which("rtl_power"):
                self.log.emit("rtl_power nicht gefunden; Signalsuche nicht möglich.")
                return
            if not self._windows_native_probe_available():
                self.log.emit(
                    "Hinweis: TETRA-Prüfung braucht rtl_sdr, tetra-rx, "
                    "GNU Radio Python und simdemod3.py."
                )

            candidates = {}
            for label, start_hz, end_hz in self.ranges:
                if not self._running.is_set():
                    break
                self.log.emit(f"Scanne {label} nach TETRA-Kandidaten...")
                spectrum = self._scan_range(start_hz, end_hz)
                if not spectrum:
                    self.log.emit(f"{label}: keine Spektrumsdaten empfangen.")
                    continue
                range_candidates = self._find_candidates(spectrum, label)
                self.log.emit(
                    f"{label}: {len(range_candidates)} Kandidaten aus Pegeldaten."
                )
                for entry in range_candidates:
                    key = int(round(entry["frequency_hz"] / TETRA_CHANNEL_RASTER_HZ))
                    current = candidates.get(key)
                    if current is None or entry["power"] > current["power"]:
                        candidates[key] = entry

            ordered = sorted(
                candidates.values(),
                key=lambda item: item["power"],
                reverse=True,
            )
            if self.max_candidates and self.max_candidates > 0:
                ordered = ordered[: self.max_candidates]
            if not ordered:
                self.log.emit("Keine auffälligen TETRA-Kandidaten gefunden.")
                return

            for index, entry in enumerate(ordered, start=1):
                if not self._running.is_set():
                    break
                frequency = entry["frequency_hz"]
                entry = dict(entry)
                entry.update({
                    "status": "möglich",
                    "details": (
                        f"Pegel {entry['delta']:+.1f} dB über Median; "
                        "Dekoderprüfung startet"
                    ),
                    "audio": "-",
                    "lines": [],
                })
                self.candidate.emit(entry)
                self.log.emit(
                    f"Prüfe Kandidat {index}/{len(ordered)}: "
                    f"{frequency/1e6:.4f} MHz"
                )
                probe = self._probe_frequency_sweep(frequency)
                entry.update(probe)
                self.candidate.emit(entry)
        finally:
            self._running.clear()
            self._terminate_processes()

    def _scan_range(self, start_hz: float, end_hz: float):
        gain_value = _resolve_gain_value(self.gain)
        cmd = [
            "rtl_power",
            "-p", str(self.ppm),
            "-g", str(gain_value),
            f"-f{start_hz/1e6:.3f}M:{end_hz/1e6:.3f}M:{TETRA_SCAN_BIN_HZ}",
            "-i", "1",
            "-",
        ]
        if self.device_id is not None:
            cmd.extend(["-d", str(self.device_id)])

        samples = []
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                **_hidden_subprocess_kwargs(),
            )
            self._add_proc(proc)
            deadline = time.time() + max(1, self.scan_seconds)
            while self._running.is_set() and time.time() < deadline:
                if not proc.stdout:
                    break
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.05)
                    continue
                parsed = self._parse_rtl_power_line(line)
                samples.extend(parsed)
        except Exception as exc:
            self.log.emit(f"rtl_power-Scan fehlgeschlagen: {exc}")
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            self._terminate_processes()
        return samples

    @staticmethod
    def _parse_rtl_power_line(line: str):
        parts = line.strip().split(",")
        if len(parts) < 7:
            return []
        try:
            f0 = float(parts[2])
            bin_hz = float(parts[4])
            powers = [float(value) for value in parts[6:] if value.strip()]
        except ValueError:
            return []
        return [
            (f0 + bin_hz * index, power)
            for index, power in enumerate(powers)
        ]

    def _find_candidates(self, spectrum, label: str):
        buckets = {}
        for freq, power in spectrum:
            key = int(round(freq / TETRA_CHANNEL_RASTER_HZ))
            current = buckets.get(key)
            if current is None or power > current:
                buckets[key] = power
        if not buckets:
            return []

        powers = np.array(list(buckets.values()), dtype=float)
        median = float(np.median(powers))
        p75 = float(np.percentile(powers, 75))
        threshold = max(median + 4.0, p75 + 1.5)

        raw = []
        for key, power in buckets.items():
            freq = key * TETRA_CHANNEL_RASTER_HZ
            if power >= threshold:
                raw.append((freq, power, power - median))
        if len(raw) < 3:
            top = sorted(
                (
                    (key * TETRA_CHANNEL_RASTER_HZ, power, power - median)
                    for key, power in buckets.items()
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:6]
            seen_freqs = {freq for freq, _power, _delta in raw}
            raw.extend(item for item in top if item[0] not in seen_freqs)

        clusters = []
        for freq, power, delta in sorted(raw, key=lambda item: item[0]):
            if not clusters or freq - clusters[-1][-1][0] > 25_000:
                clusters.append([])
            clusters[-1].append((freq, power, delta))

        clustered = []
        for cluster in clusters:
            weights = np.array(
                [max(0.1, power - median) for _freq, power, _delta in cluster],
                dtype=float,
            )
            freqs = np.array([freq for freq, _power, _delta in cluster], dtype=float)
            center = float(np.average(freqs, weights=weights))
            center = round(center / TETRA_CHANNEL_RASTER_HZ) * TETRA_CHANNEL_RASTER_HZ
            best_power = max(power for _freq, power, _delta in cluster)
            best_delta = max(delta for _freq, _power, delta in cluster)
            clustered.append((center, best_power, best_delta))

        selected = []
        for freq, power, delta in sorted(clustered, key=lambda item: item[1], reverse=True):
            if any(abs(freq - item["frequency_hz"]) < 37_500 for item in selected):
                continue
            selected.append({
                "frequency_hz": float(freq),
                "frequency_mhz": freq / 1e6,
                "power": float(power),
                "delta": float(delta),
                "range": label,
            })
        return selected

    def _windows_native_probe_available(self):
        return bool(
            sys.platform.startswith("win")
            and _official_demod_script()
            and _find_gnuradio_python()
            and shutil.which("rtl_sdr")
            and shutil.which("tetra-rx")
        )

    def _rtl_sdr_probe_cmd(self, frequency: float, seconds: float | None = None):
        probe_seconds = max(1.0, float(seconds if seconds is not None else self.probe_seconds))
        cmd = [
            "rtl_sdr",
            "-p", str(self.ppm),
            "-g", str(_resolve_gain_value(self.gain)),
            "-f", str(int(frequency)),
            "-s", "2000000",
            "-n", str(int(2_000_000 * probe_seconds)),
        ]
        if self.device_id is not None:
            cmd.extend(["-d", str(self.device_id)])
        cmd.append("-")
        return cmd

    def _probe_frequency_sweep(self, frequency: float):
        quick_seconds = max(3.0, min(float(self.probe_seconds), 4.0))
        attempts = [
            (frequency, "normal", quick_seconds),
            (frequency - 12_500, "normal", quick_seconds),
            (frequency + 12_500, "normal", quick_seconds),
            (frequency, "conjugate", quick_seconds),
        ]
        best = None
        attempt_texts = []
        for probe_frequency, iq_mode, seconds in attempts:
            if not self._running.is_set():
                break
            result = self._probe_frequency(
                probe_frequency,
                iq_mode=iq_mode,
                probe_seconds=seconds,
            )
            attempt_texts.append(
                f"{probe_frequency/1e6:.4f} MHz/{iq_mode}: {result.get('status')}"
            )
            result["probe_frequency_hz"] = probe_frequency
            result["iq_mode"] = iq_mode
            if result.get("confirmed"):
                result["details"] = (
                    f"{result.get('details', '')}; Prüfmitte "
                    f"{probe_frequency/1e6:.4f} MHz, IQ {iq_mode}"
                )
                return result
            if result.get("status") in ("Fehler", "nicht geprüft", "abgebrochen"):
                return result
            if best is None or result.get("bits_size", 0) > best.get("bits_size", 0):
                best = result

        if best is None:
            return {
                "status": "abgebrochen",
                "details": "Signalsuche wurde gestoppt",
                "audio": "-",
                "lines": [],
                "bits_size": 0,
            }
        best = dict(best)
        best["details"] = (
            f"{best.get('details', 'keine gültigen TETRA-Bursts')}; "
            "geprüft: " + " | ".join(attempt_texts)
        )
        return best

    def _probe_frequency(
        self,
        frequency: float,
        iq_mode: str = "normal",
        probe_seconds: float | None = None,
    ):
        if not self._windows_native_probe_available():
            return {
                "status": "nicht geprüft",
                "details": "Dekoderkette für die Prüfung nicht vollständig gefunden",
                "audio": "-",
                "lines": [],
                "bits_size": 0,
            }

        demod_script = _official_demod_script()
        gnuradio_python = _find_gnuradio_python()
        bits_path = None
        lines = []
        bits_size = 0
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bits")
            bits_path = tmp.name
            tmp.close()

            with open(bits_path, "wb") as bits_out:
                conv_env = _gnuradio_env_for(gnuradio_python)
                conv_env["TETRA_IQ_MODE"] = iq_mode
                p1 = subprocess.Popen(
                    self._rtl_sdr_probe_cmd(frequency, seconds=probe_seconds),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    **_hidden_subprocess_kwargs(),
                )
                self._add_proc(p1)
                pconv = subprocess.Popen(
                    [gnuradio_python, "-u", "-c", _RTL_U8_TO_COMPLEX64_SCRIPT],
                    stdin=p1.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=conv_env,
                    **_hidden_subprocess_kwargs(),
                )
                self._add_proc(pconv)
                if p1.stdout:
                    p1.stdout.close()
                p2 = subprocess.Popen(
                    [gnuradio_python, demod_script],
                    stdin=pconv.stdout,
                    stdout=bits_out,
                    stderr=subprocess.DEVNULL,
                    env=_gnuradio_env_for(gnuradio_python),
                    **_hidden_subprocess_kwargs(),
                )
                self._add_proc(p2)
                if pconv.stdout:
                    pconv.stdout.close()

                active_seconds = max(1.0, float(probe_seconds or self.probe_seconds))
                deadline = time.time() + max(5, active_seconds + 5)
                while self._running.is_set() and time.time() < deadline:
                    if p2.poll() is not None:
                        break
                    time.sleep(0.1)
                self._terminate_processes()

            if not self._running.is_set():
                return {
                    "status": "abgebrochen",
                    "details": "Signalsuche wurde gestoppt",
                    "audio": "-",
                    "lines": [],
                    "bits_size": bits_size,
                }

            bits_size = os.path.getsize(bits_path)
            if bits_size == 0:
                return {
                    "confirmed": False,
                    "status": "Fehler",
                    "details": (
                        "keine IQ-/Demodulationsdaten; RTL-SDR vermutlich belegt "
                        "oder Treiberzugriff blockiert"
                    ),
                    "audio": "-",
                    "lines": [],
                    "bits_size": bits_size,
                }
            if bits_size >= 4096:
                p3 = subprocess.Popen(
                    ["tetra-rx", bits_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    **_hidden_subprocess_kwargs(),
                )
                self._add_proc(p3)
                try:
                    out, _ = p3.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    self._terminate_processes()
                    out = ""
                lines = [
                    line.strip()
                    for line in out.splitlines()
                    if line.strip() and line.strip() != "EOF"
                ][:300]
                self._terminate_processes()

            result = _classify_tetra_lines(lines, bits_size)
            result["lines"] = lines
            result["bits_size"] = bits_size
            return result
        except Exception as exc:
            self._terminate_processes()
            return {
                "status": "Fehler",
                "details": f"Prüfung fehlgeschlagen: {exc}",
                "audio": "-",
                "lines": lines,
                "bits_size": bits_size,
            }
        finally:
            if bits_path:
                try:
                    os.remove(bits_path)
                except OSError:
                    pass


class AudioPlayer(QtCore.QObject):
    """Empfängt Audio von rtl_fm und spielt es über PyAudio ab."""

    def __init__(self, device: str, ppm: int = 0, gain=None, parent=None):
        super().__init__(parent)
        self.device = device
        self.device_id = None
        self.ppm = ppm
        self.gain = gain
        self._process = None
        self._stream = None
        self._audio_thread = None
        self._stop_requested = threading.Event()
        self._state_lock = threading.RLock()
        self._pa = None
        self.agc_level = 10000
        self.activity_threshold = 1000
        self.record_file = None
        self.record_last = 0

    def start(self, frequency):
        self.stop()
        with self._state_lock:
            alter_thread = self._audio_thread
        if alter_thread and alter_thread.is_alive():
            logger.warning(
                "Audiowiedergabe wird nicht neu gestartet, weil der alte Thread "
                "noch beendet wird."
            )
            return
        self._stop_requested.clear()
        gain_value = _resolve_gain_value(self.gain)
        cmd = [
            "rtl_fm",
            "-p", str(self.ppm),
            "-g", str(gain_value),
            "-f", str(int(frequency)),
            "-s", "48000",
            "-"
        ]
        if self.device_id is not None:
            cmd.extend(["-d", str(self.device_id)])
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL,
                                       **_hidden_subprocess_kwargs())
        except (FileNotFoundError, OSError) as exc:
            logger.warning("rtl_fm konnte nicht gestartet werden: %s", exc)
            return

        try:
            if self._pa is None:
                self._pa = pyaudio.PyAudio()
            stream = self._pa.open(format=pyaudio.paInt16,
                                   channels=1,
                                   rate=48000,
                                   output=True,
                                   frames_per_buffer=1024)
        except Exception as exc:
            logger.warning("Audiowiedergabe konnte nicht gestartet werden: %s", exc)
            process.terminate()
            try:
                process.wait(timeout=1)
            except Exception:
                pass
            return

        thread = threading.Thread(target=self._play,
                                  args=(process, stream),
                                  daemon=True)
        with self._state_lock:
            self._process = process
            self._stream = stream
            self._audio_thread = thread
        thread.start()

    def stop(self):
        self._stop_requested.set()
        with self._state_lock:
            process = self._process
            thread = self._audio_thread

        if process and process.poll() is None:
            process.terminate()

        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2)

        with self._state_lock:
            if self._process is process:
                self._process = None
            if self._audio_thread is thread and (not thread or not thread.is_alive()):
                self._audio_thread = None

        if not thread or not thread.is_alive():
            self._close_recording()

    def _play(self, process, stream):
        if not process or not process.stdout:
            return
        try:
            while not self._stop_requested.is_set():
                data = process.stdout.read(2048)
                if not data:
                    break
                try:
                    audio = np.frombuffer(data, dtype=np.int16)
                except ValueError:
                    continue
                if audio.size == 0:
                    continue
                # AGC anwenden
                level = np.max(np.abs(audio))
                if level > 0:
                    gain = self.agc_level / level
                    audio = (audio * gain).astype(np.int16)
                hat_aktivitaet = np.max(np.abs(audio)) > self.activity_threshold
                if hat_aktivitaet:
                    parent = self.parent()
                    if parent is not None:
                        QtCore.QMetaObject.invokeMethod(
                            parent, "notify_activity", QtCore.Qt.QueuedConnection
                        )
                    self._start_recording()
                self._write_recording(audio)
                stream.write(audio.tobytes())
        except Exception as exc:
            if not self._stop_requested.is_set():
                logger.warning("Audiowiedergabe wurde beendet: %s", exc)
        finally:
            self._stop_requested.set()
            self._close_stream(stream)
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=1)
            except Exception:
                pass
            self._close_recording()
            with self._state_lock:
                if self._process is process:
                    self._process = None
                if self._stream is stream:
                    self._stream = None
                if self._audio_thread is threading.current_thread():
                    self._audio_thread = None

    def _close_stream(self, stream):
        try:
            if stream.is_active():
                stream.stop_stream()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _close_recording(self):
        if self.record_file:
            try:
                self.record_file.close()
            finally:
                self.record_file = None

    def _start_recording(self):
        if self.record_file:
            self.record_last = time.time()
            return
        path = os.path.expanduser("~/TetraRecordings")
        os.makedirs(path, exist_ok=True)
        fname = datetime.now().strftime("rec_%Y%m%d_%H%M%S.wav")
        self.record_file = wave.open(os.path.join(path, fname), "wb")
        self.record_file.setnchannels(1)
        self.record_file.setsampwidth(2)
        self.record_file.setframerate(48000)
        self.record_last = time.time()

    def _write_recording(self, audio):
        if self.record_file:
            self.record_file.writeframes(audio.tobytes())
            if time.time() - self.record_last > 2:
                self.record_file.close()
                self.record_file = None


class LEDIndicator(QtWidgets.QFrame):
    """Einfaches LED-Anzeige-Widget mit Farbe."""

    def __init__(self, size=20, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.set_color("green")

    def set_color(self, color: str):
        self.setStyleSheet(
            f"background-color: {color}; border-radius: {self._size // 2}px;"
        )


class DecodedAudioPlayer(QtCore.QObject):
    """Spielt dekodierte TETRA-Audioframes über PyAudio ab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pa = None
        self._stream = None
        self.record = False
        self._wav = None

    def start(self, record: bool = False):
        self.stop()
        self.record = record
        if self._pa is None:
            self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=8000,
            output=True,
            frames_per_buffer=1024,
        )
        if record:
            path = os.path.expanduser("~/TetraVoice")
            os.makedirs(path, exist_ok=True)
            name = datetime.now().strftime("voice_%Y%m%d_%H%M%S.wav")
            self._wav = wave.open(os.path.join(path, name), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(8000)

    def stop(self):
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._wav:
            self._wav.close()
            self._wav = None

    def process(self, data: bytes):
        if not self._stream:
            return
        self._stream.write(data)
        if self._wav:
            self._wav.writeframes(data)


class TetraDecoder(QtCore.QObject):
    """Startet osmocom-tetra-Werkzeuge und liefert dekodierte Ausgabe."""

    output = QtCore.pyqtSignal(str)
    audio = QtCore.pyqtSignal(bytes)
    encrypted = QtCore.pyqtSignal()
    finished = QtCore.pyqtSignal()

    def __init__(self, ppm: int = 0, parent=None):
        super().__init__(parent)
        self.ppm = ppm
        self.gain = "max"
        self.device_id = None
        self._thread = None
        self._running = threading.Event()
        self._procs = []
        self._audio_thread = None
        self._audio_path = None
        self._audio_mode = None

    def audio_output_supported(self):
        return _legacy_audio_decoder_available()

    def start(self, frequency: float):
        """Startet die Dekodierkette für die angegebene Frequenz."""
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, args=(frequency,), daemon=True)
        self._thread.start()

    def stop(self):
        """Stoppt die Dekodierung und beendet Kindprozesse."""
        self._running.clear()
        self._terminate_processes()
        if (
            self._audio_thread
            and self._audio_thread.is_alive()
            and threading.current_thread() is not self._audio_thread
        ):
            self._audio_thread.join(timeout=1)
        if (
            self._thread
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=1)
        self._thread = None
        self._audio_thread = None
        self._cleanup_audio_file()

    def _cleanup_audio_file(self):
        if self._audio_path:
            try:
                os.remove(self._audio_path)
            except OSError:
                pass
            self._audio_path = None
            self._audio_mode = None

    def _terminate_processes(self):
        for proc in self._procs:
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in self._procs:
            if not proc:
                continue
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
        self._procs = []

    def _rtl_sdr_cmd(self, frequency: float):
        cmd = [
            "rtl_sdr",
            "-p", str(self.ppm),
            "-g", str(_resolve_gain_value(self.gain)),
            "-f", str(int(frequency)),
            "-s", "2000000",
        ]
        if self.device_id is not None:
            cmd.extend(["-d", str(self.device_id)])
        cmd.append("-")
        return cmd

    def _windows_native_batch_available(self):
        return bool(
            sys.platform.startswith("win")
            and _official_demod_script()
            and _find_gnuradio_python()
            and shutil.which("rtl_sdr")
            and shutil.which("tetra-rx")
        )

    def _official_pipeline(self, frequency: float):
        demod_script = _official_demod_script()
        if sys.platform.startswith("win"):
            wsl_demod_script = _wsl_path(demod_script) if demod_script else None
            if (
                wsl_demod_script
                and shutil.which("wsl.exe")
                and shutil.which("rtl_sdr")
                and _wsl_osmo_decoder_available()
            ):
                return [
                    self._rtl_sdr_cmd(frequency),
                    ["wsl.exe", "--", "bash", "-lc", f"python3 {shlex.quote(wsl_demod_script)}"],
                    ["wsl.exe", "--", "bash", "-lc", "tetra-rx /dev/stdin"],
                ]
            return None

        gnuradio_python = _find_gnuradio_python()
        if (
            not demod_script
            or not gnuradio_python
            or not shutil.which("rtl_sdr")
            or not shutil.which("tetra-rx")
        ):
            return None

        return [
            self._rtl_sdr_cmd(frequency),
            [gnuradio_python, demod_script],
            ["tetra-rx", "/dev/stdin"],
        ]

    def _run_windows_native_batches(self, frequency: float):
        demod_script = _official_demod_script()
        gnuradio_python = _find_gnuradio_python()
        if not demod_script or not gnuradio_python:
            self.output.emit("GNU Radio/simdemod3.py nicht verfügbar")
            return

        self.output.emit(
            "Nutze Windows-kompatible Osmocom-TETRA Pipeline "
            "(rtl_sdr -> u8/complex64-Konverter -> simdemod3.py -> tetra-rx)."
        )
        self.output.emit(
            "Audioausgabe: mit der aktuellen Windows-Osmocom-Pipeline nicht verfügbar; "
            "Steuerdaten, Netzinfos und Sprechgruppen/Adressen werden dekodiert."
        )
        batch_seconds = 10
        while self._running.is_set():
            bits_path = None
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bits")
                bits_path = tmp.name
                tmp.close()

                with open(bits_path, "wb") as bits_out:
                    p1 = subprocess.Popen(
                        self._rtl_sdr_cmd(frequency),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        **_hidden_subprocess_kwargs(),
                    )
                    self._procs.append(p1)
                    pconv = subprocess.Popen(
                        [gnuradio_python, "-u", "-c", _RTL_U8_TO_COMPLEX64_SCRIPT],
                        stdin=p1.stdout,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        **_hidden_subprocess_kwargs(),
                    )
                    self._procs.append(pconv)
                    if p1.stdout:
                        p1.stdout.close()
                    p2 = subprocess.Popen(
                        [gnuradio_python, demod_script],
                        stdin=pconv.stdout,
                        stdout=bits_out,
                        stderr=subprocess.DEVNULL,
                        **_hidden_subprocess_kwargs(),
                    )
                    self._procs.append(p2)
                    if pconv.stdout:
                        pconv.stdout.close()

                    deadline = time.time() + batch_seconds
                    while self._running.is_set() and time.time() < deadline:
                        if any(proc.poll() is not None for proc in (p1, pconv, p2)):
                            break
                        time.sleep(0.1)

                    self._terminate_processes()

                if not self._running.is_set():
                    break
                bits_size = os.path.getsize(bits_path)
                if bits_size < 4096:
                    self.output.emit(
                        f"Zu wenige Demodulationsbits empfangen ({bits_size} Byte)."
                    )
                    continue

                p3 = subprocess.Popen(
                    ["tetra-rx", bits_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    **_hidden_subprocess_kwargs(),
                )
                self._procs.append(p3)
                dekodiert = False
                if p3.stdout:
                    for line in p3.stdout:
                        if not self._running.is_set():
                            break
                        txt = line.rstrip()
                        if not txt or txt == "EOF":
                            continue
                        dekodiert = True
                        self.output.emit(txt)
                        if re.search(r"\b(?:ENCRYPTED|Encr=[1-9]|CIPHER)\b", txt, re.I):
                            self.encrypted.emit()
                try:
                    p3.wait(timeout=5)
                except Exception:
                    pass
                finally:
                    self._terminate_processes()
                if not dekodiert:
                    self.output.emit(
                        "Keine gültigen TETRA-Bursts in diesem Zeitfenster dekodiert."
                    )
            except Exception as exc:
                self.output.emit(f"Windows-TETRA-Dekodierung fehlgeschlagen: {exc}")
                self._terminate_processes()
            finally:
                if bits_path:
                    try:
                        os.remove(bits_path)
                    except OSError:
                        pass

    def _legacy_pipeline(self, frequency: float, audio_enabled: bool):
        receiver_cmd = ["receiver1", "-f", str(int(frequency)), "-p", str(self.ppm)]
        if self.device_id is not None:
            receiver_cmd.extend(["-d", str(self.device_id)])

        if shutil.which("demod_float"):
            demod_cmd = ["demod_float"]
        elif shutil.which("float_to_bits"):
            demod_cmd = ["float_to_bits"]
        else:
            demod_cmd = ["demod_float"]

        return [
            receiver_cmd,
            demod_cmd,
            ["tetra-rx"] + (["-a", self._audio_path] if audio_enabled else []),
        ]

    def _ensure_audio_output(self):
        if not sys.platform.startswith("win") and hasattr(os, "mkfifo"):
            self._audio_path = os.path.join(
                tempfile.gettempdir(), f"tetra_audio_fifo_{os.getpid()}"
            )
            if os.path.exists(self._audio_path):
                os.remove(self._audio_path)
            os.mkfifo(self._audio_path)
            self._audio_mode = "fifo"
        else:
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".raw")
            self._audio_path = tmp_file.name
            tmp_file.close()
            self._audio_mode = "file"
        self.output.emit(
            f"Audioausgabe aktiviert ({self._audio_mode}), Pfad: {self._audio_path}"
        )

    def _run(self, frequency: float):
        self._procs = []
        self._audio_thread = None
        p3 = None
        try:
            if self._windows_native_batch_available():
                self._run_windows_native_batches(frequency)
                return

            cmds = self._official_pipeline(frequency)
            audio_enabled = False
            if cmds:
                self.output.emit(
                    "Nutze offizielle Osmocom-TETRA Pipeline "
                    "(rtl_sdr -> simdemod3.py -> tetra-rx)."
                )
            else:
                audio_enabled = _legacy_audio_decoder_available()
                if audio_enabled:
                    self._ensure_audio_output()
                else:
                    self.output.emit(
                        "Audioausgabe: nicht verfügbar, weil kein audiofähiger "
                        "Legacy-Decoder gefunden wurde."
                    )
                cmds = self._legacy_pipeline(frequency, audio_enabled)

            # Prüfen, ob alle Befehle vor dem Start vorhanden sind
            for cmd in cmds:
                if not shutil.which(cmd[0]):
                    self.output.emit(f"{cmd[0]} nicht im PATH gefunden")
                    self._running.clear()
                    self.finished.emit()
                    return
            p1 = subprocess.Popen(
                cmds[0],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_hidden_subprocess_kwargs(),
            )
            self._procs.append(p1)
            p2 = subprocess.Popen(
                cmds[1],
                stdin=p1.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_hidden_subprocess_kwargs(),
            )
            self._procs.append(p2)
            p1.stdout.close()
            p3 = subprocess.Popen(
                cmds[2],
                stdin=p2.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **_hidden_subprocess_kwargs(),
            )
            p2.stdout.close()
            self._procs.append(p3)
            if audio_enabled:
                self._audio_thread = threading.Thread(target=self._read_audio, daemon=True)
                self._audio_thread.start()

            if p3 and p3.stdout:
                for line in p3.stdout:
                    if not self._running.is_set():
                        break
                    txt = line.rstrip()
                    self.output.emit(txt)
                    if re.search(r"\b(?:ENCRYPTED|Encr=[1-9]|CIPHER)\b", txt, re.I):
                        self.encrypted.emit()
        except Exception as exc:
            self.output.emit(f"Decoder konnte nicht gestartet werden: {exc}")
        finally:
            self._running.clear()
            self._terminate_processes()
            if (
                self._audio_thread
                and self._audio_thread.is_alive()
                and threading.current_thread() is not self._audio_thread
            ):
                self._audio_thread.join(timeout=1)
            self._audio_thread = None
            self._cleanup_audio_file()
            self.finished.emit()

    def _read_audio(self):
        try:
            while self._running.is_set():
                try:
                    if self._audio_mode == "fifo":
                        with open(self._audio_path, "rb", buffering=0) as fh:
                            while self._running.is_set():
                                data = fh.read(320)
                                if not data:
                                    time.sleep(0.05)
                                    break
                                self.audio.emit(data)
                    elif self._audio_mode == "file":
                        with open(self._audio_path, "rb", buffering=0) as fh:
                            pos = 0
                            while self._running.is_set():
                                try:
                                    size = os.path.getsize(self._audio_path)
                                except OSError:
                                    time.sleep(0.05)
                                    continue
                                if size - pos < 320:
                                    time.sleep(0.05)
                                    continue
                                fh.seek(pos)
                                data = fh.read(320)
                                pos = fh.tell()
                                if data:
                                    self.audio.emit(data)
                                else:
                                    time.sleep(0.05)
                    else:
                        time.sleep(0.05)
                except Exception:
                    time.sleep(0.05)
        finally:
            self._cleanup_audio_file()


class SpectrumCanvas(FigureCanvas):
    """Matplotlib-Canvas für die Spektrumsanzeige."""

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Frequenz [Hz]")
        self.ax.set_ylabel("Leistung [dB]")
        self.line, = self.ax.plot([], [])

    def update_spectrum(self, freqs, powers):
        self.line.set_data(freqs, powers)
        self.ax.relim()
        self.ax.autoscale_view()
        self.draw()


class MainWindow(QtWidgets.QMainWindow):
    """Hauptfenster der Anwendung."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SDR-Scanner")
        self.resize(900, 700)

        # Widgets, die in mehreren Tabs verwendet werden
        self.start_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay),
            "Starten",
        )
        self.stop_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaStop),
            "Stopp",
        )
        self.freq_label = QtWidgets.QLabel("Frequenz: k. A.")

        self.canvas = SpectrumCanvas()
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.freq_list = QtWidgets.QListWidget()

        self.activity_led = LEDIndicator()

        self.device_box = QtWidgets.QComboBox()
        self.refresh_devices()

        self.freq_range_box = QtWidgets.QComboBox()
        for label, start_hz, end_hz in TETRA_DEFAULT_RANGES:
            self.freq_range_box.addItem(label, (start_hz, end_hz))

        self.agc_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.agc_slider.setRange(5000, 20000)
        self.agc_slider.setValue(10000)
        self.agc_value = QtWidgets.QLabel(str(self.agc_slider.value()))

        # Konfiguration muss während der Tab-Erstellung verfügbar sein
        self.config = {
            "theme": "light",
            "telegram_token": "",
            "telegram_chat": "",
            "scheduler_interval": 15,
            "scheduler_enabled": False,
            "ppm": 0,
            "gain": "max",
            "audio_agc_level": 10000,
            "freq_range_label": "",
            "talkgroups": {},
            "selected_talkgroups": [],
            "talkgroup_filter_enabled": False,
            "calibration_ref_mhz": 99.2,
            "calibration_search_khz": 180,
            "calibrate_on_start": True,
            "tetra_probe_all_candidates": True,
            "tetra_max_candidates": 0,
            "audio_mode": "safe",
            "record_audio": False,
            "monitor_cycle_delay_sec": 5,
            "ui_profile_version": 2,
        }
        self.config.update(load_config())
        if int(self.config.get("ui_profile_version", 0) or 0) < 2:
            self.config["calibrate_on_start"] = True
            self.config["ui_profile_version"] = 2
        if abs(float(self.config.get("calibration_ref_mhz", 99.2)) - 421.0375) < 0.0001:
            self.config["calibration_ref_mhz"] = 99.2
        if int(self.config.get("calibration_search_khz", 180)) == 100:
            self.config["calibration_search_khz"] = 180
        self.config["gain"] = _normalize_gain_setting(self.config.get("gain", "max"))
        self.agc_slider.setValue(int(self.config.get("audio_agc_level", 10000)))
        gespeicherter_bereich = str(self.config.get("freq_range_label", ""))
        if gespeicherter_bereich:
            index = self.freq_range_box.findText(gespeicherter_bereich)
            if index >= 0:
                self.freq_range_box.setCurrentIndex(index)

        self.manual_lock = False
        self.tetra_signal_search = None
        self._signal_search_rows = {}
        self._overview_signal_rows = {}
        self.calibration_worker = None
        self.monitoring_active = False
        self.monitor_timer = QtCore.QTimer(self)
        self.monitor_timer.setSingleShot(True)
        self.monitor_timer.timeout.connect(self._run_monitoring_cycle)

        self.tabs = QtWidgets.QTabWidget()
        self._build_modern_tabs()

        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)
        lay.setContentsMargins(10, 10, 10, 6)
        lay.setSpacing(6)
        lay.addWidget(self.tabs)
        self.footer_label = QtWidgets.QLabel(_copyright_text())
        self.footer_label.setObjectName("footerLabel")
        self.footer_label.setAlignment(QtCore.Qt.AlignRight)
        lay.addWidget(self.footer_label)
        self.setCentralWidget(central)

        self.scanner = SDRScanner(
            device=self.device_box.currentText(),
            ppm=self.config.get("ppm", 0),
            gain=self.config.get("gain", "max"),
            parent=self,
        )
        self.player = AudioPlayer(
            device=self.device_box.currentText(),
            ppm=self.config.get("ppm", 0),
            gain=self.config.get("gain", "max"),
            parent=self,
        )
        self.decoder = TetraDecoder(ppm=self.config.get("ppm", 0), parent=self)
        self.dec_audio_player = DecodedAudioPlayer(parent=self)

        self.scheduler_timer = QtCore.QTimer(self)
        self.scheduler_timer.timeout.connect(self.run_scheduled_cycle)

        if self.config.get("theme") == "dark":
            self.apply_theme("dark")

        self.update_scheduler()

        self.agc_slider.valueChanged.connect(self._update_agc)
        self.ppm_spin.valueChanged.connect(self._update_ppm)
        self.freq_range_box.currentIndexChanged.connect(self._on_freq_range_change)
        self.rf_gain_spin.valueChanged.connect(self._update_rf_gain)
        self.rf_gain_max_cb.toggled.connect(self._toggle_rf_gain_max)
        self.ref_freq_spin.valueChanged.connect(
            lambda value: self.config.__setitem__("calibration_ref_mhz", float(value))
        )
        self.cal_span_spin.valueChanged.connect(
            lambda value: self.config.__setitem__("calibration_search_khz", int(value))
        )
        self.calibrate_on_start_cb.toggled.connect(
            lambda checked: self.config.__setitem__("calibrate_on_start", bool(checked))
        )
        self.ppm_cal_btn.clicked.connect(lambda: self.start_calibration("ppm"))
        self.gain_cal_btn.clicked.connect(lambda: self.start_calibration("gain"))
        self.full_cal_btn.clicked.connect(lambda: self.start_calibration("both"))
        self.probe_all_candidates_cb.toggled.connect(self._on_probe_all_candidates_change)
        self.max_candidates_spin.valueChanged.connect(
            lambda value: self.config.__setitem__("tetra_max_candidates", int(value))
        )
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.freq_list.itemDoubleClicked.connect(self._select_frequency_from_list)
        self.scanner.spectrum_ready.connect(self.canvas.update_spectrum)
        self.scanner.spectrum_ready.connect(self._update_scan_results)
        self.scanner.frequency_selected.connect(self.update_frequency)

        self.decoder.output.connect(self._append_tetra)
        self.decoder.finished.connect(self._decoder_finished)
        self.decoder.audio.connect(self.dec_audio_player.process)
        self.decoder.encrypted.connect(self._encrypted_signal)

        self.tetra_start_btn.clicked.connect(self.start_decoding)
        self.tetra_stop_btn.clicked.connect(self.stop_decoding)
        self.tetra_search_btn.clicked.connect(self.start_tetra_signal_search)
        self.tetra_search_stop_btn.clicked.connect(self.stop_tetra_signal_search)
        self.decode_selected_signal_btn.clicked.connect(self.decode_selected_signal_candidate)
        self.signal_search_table.itemDoubleClicked.connect(
            self._decode_signal_candidate_from_item
        )
        self.overview_channel_table.itemDoubleClicked.connect(
            self._decode_signal_candidate_from_item
        )
        self.overview_monitor_btn.toggled.connect(self._toggle_monitoring)
        self.overview_search_btn.clicked.connect(self.start_tetra_signal_search)
        self.overview_stop_search_btn.clicked.connect(self.stop_tetra_signal_search)
        self.overview_decode_btn.clicked.connect(self.decode_selected_signal_candidate)
        self.overview_calibrate_btn.clicked.connect(lambda: self.start_calibration("both"))
        self.overview_start_scan_btn.clicked.connect(self.start)
        self.overview_stop_btn.clicked.connect(self.stop)
        self.audio_mode_combo.currentIndexChanged.connect(self._on_audio_mode_change)
        self.play_audio_cb.toggled.connect(self._toggle_dec_audio)
        self.record_audio_cb.toggled.connect(
            lambda checked: self.config.__setitem__("record_audio", bool(checked))
        )

        self.theme_combo.currentIndexChanged.connect(self._on_theme_change)
        self.scheduler_enable_cb.toggled.connect(self.update_scheduler)
        self.scheduler_interval_spin.valueChanged.connect(self.update_scheduler)
        self.export_cells_btn.clicked.connect(self.export_cells_csv)
        self.token_edit.textChanged.connect(lambda t: self.config.__setitem__("telegram_token", t))
        self.chat_edit.textChanged.connect(lambda t: self.config.__setitem__("telegram_chat", t))
        self.talkgroup_select_all_btn.clicked.connect(
            lambda: self._set_all_talkgroup_selection(True)
        )
        self.talkgroup_select_none_btn.clicked.connect(
            lambda: self._set_all_talkgroup_selection(False)
        )
        self.talkgroup_filter_cb.toggled.connect(self._on_talkgroup_filter_change)

        self._update_ppm(self.ppm_spin.value())
        self._apply_gain_setting(self.config.get("gain", "max"))
        self._update_agc(self.agc_slider.value())
        self.apply_theme(self.config.get("theme", "light"))
        self._refresh_dashboard_status()

        self.freq_history = deque(maxlen=10)
        self.scan_results = {}
        self.current_frequency = None
        self.cells = {}
        self.packet_counts = {}
        self.talkgroups = {}
        self.decoder_data = deque(maxlen=1000)
        self.network_infos = {}
        self.selected_talkgroups = set()
        self._load_talkgroups_from_config()
        self._load_selected_talkgroups_from_config()
        self._update_talkgroups_table()

        self.talkgroup_table.itemChanged.connect(self._handle_talkgroup_selection_change)

        self.setup_worker = None
        missing_cmds, missing_mods, missing_optional = SetupWorker.detect_missing_requirements()
        decoder_notice = SetupWorker.decoder_notice()
        if decoder_notice:
            self.log.appendPlainText(decoder_notice)
        if missing_cmds or missing_mods or missing_optional:
            self.log.appendPlainText("Starte automatische Pr\u00fcfung der Zusatzprogramme...")
            if missing_cmds:
                self.log.appendPlainText(
                    "Fehlende Programme: " + ", ".join(sorted(missing_cmds))
                )
            if missing_mods:
                self.log.appendPlainText(
                    "Fehlende Python-Module: " + ", ".join(sorted(missing_mods))
                )
            if missing_optional:
                self.log.appendPlainText(
                    "Fehlende Zusatzwerkzeuge: " + ", ".join(sorted(missing_optional))
                )

            self.setup_worker = SetupWorker()
            self.setup_worker.log.connect(self.log.appendPlainText)
            self.setup_worker.log.connect(logger.info)
            self.setup_worker.finished.connect(
                lambda: self.log.appendPlainText("Setup abgeschlossen")
            )
            self.setup_worker.start()
        else:
            if decoder_notice:
                self.log.appendPlainText("Alle installierten Basiswerkzeuge wurden gefunden.")
            else:
                self.log.appendPlainText(
                    "Alle ben\u00f6tigten Zusatzprogramme wurden bereits gefunden."
                )

        if self.config.get("calibrate_on_start", False):
            QtCore.QTimer.singleShot(1500, lambda: self.start_calibration("both"))

    def _build_modern_tabs(self):
        """Erstellt die moderne Hauptoberfläche."""

        def standard_layout(widget):
            layout = QtWidgets.QVBoxLayout(widget)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(12)
            return layout

        def statuskarte(titel, wert, detail=""):
            rahmen = QtWidgets.QFrame()
            rahmen.setObjectName("statusCard")
            rahmen.setFrameShape(QtWidgets.QFrame.StyledPanel)
            layout = QtWidgets.QVBoxLayout(rahmen)
            layout.setContentsMargins(14, 12, 14, 12)
            layout.setSpacing(4)
            titel_label = QtWidgets.QLabel(titel)
            titel_label.setObjectName("statusTitle")
            wert_label = QtWidgets.QLabel(wert)
            wert_label.setObjectName("statusValue")
            detail_label = QtWidgets.QLabel(detail)
            detail_label.setObjectName("statusDetail")
            detail_label.setWordWrap(True)
            layout.addWidget(titel_label)
            layout.addWidget(wert_label)
            layout.addWidget(detail_label)
            return rahmen, wert_label, detail_label

        def richte_tabelle_ein(tabelle, stretch_spalte=None):
            tabelle.setAlternatingRowColors(True)
            tabelle.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            tabelle.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            tabelle.verticalHeader().setVisible(False)
            tabelle.setShowGrid(False)
            tabelle.setWordWrap(False)
            tabelle.horizontalHeader().setHighlightSections(False)
            if stretch_spalte is not None:
                for spalte in range(tabelle.columnCount()):
                    modus = (
                        QtWidgets.QHeaderView.Stretch
                        if spalte == stretch_spalte
                        else QtWidgets.QHeaderView.ResizeToContents
                    )
                    tabelle.horizontalHeader().setSectionResizeMode(spalte, modus)

        def aktionsknopf(text, icon=None, primaer=False):
            knopf = QtWidgets.QPushButton(text)
            if icon is not None:
                knopf.setIcon(QtWidgets.QApplication.style().standardIcon(icon))
            if primaer:
                knopf.setProperty("klasse", "primaer")
            return knopf

        tab_overview = QtWidgets.QWidget()
        overview_layout = standard_layout(tab_overview)
        kopf = QtWidgets.QHBoxLayout()
        titel_block = QtWidgets.QVBoxLayout()
        titel = QtWidgets.QLabel("TETRA Decode")
        titel.setObjectName("appTitle")
        untertitel = QtWidgets.QLabel("SDR-Überwachung, Kanäle, Sprechgruppen und Audio")
        untertitel.setObjectName("appSubtitle")
        titel_block.addWidget(titel)
        titel_block.addWidget(untertitel)
        kopf.addLayout(titel_block)
        kopf.addStretch()
        self.overview_monitor_btn = aktionsknopf(
            "Überwachung starten",
            QtWidgets.QStyle.SP_MediaPlay,
            primaer=True,
        )
        self.overview_monitor_btn.setCheckable(True)
        kopf.addWidget(self.overview_monitor_btn)
        overview_layout.addLayout(kopf)

        status_grid = QtWidgets.QGridLayout()
        status_grid.setSpacing(10)
        (
            geraet_card,
            self.dashboard_device_value,
            self.dashboard_device_detail,
        ) = statuskarte("SDR-Gerät", "wird geprüft", "")
        (
            kal_card,
            self.dashboard_calibration_value,
            self.dashboard_calibration_detail,
        ) = statuskarte("Kalibrierung", "bereit", "PPM und RF-Gain")
        (
            scan_card,
            self.dashboard_scan_value,
            self.dashboard_scan_detail,
        ) = statuskarte("Überwachung", "gestoppt", "alle aktivierten Bereiche")
        (
            tetra_card,
            self.dashboard_tetra_value,
            self.dashboard_tetra_detail,
        ) = statuskarte("TETRA", "0 bestätigt", "keine aktive Frequenz")
        (
            audio_card,
            self.dashboard_audio_value,
            self.dashboard_audio_detail,
        ) = statuskarte("Audio", "wartet", "Modus: automatisch")
        (
            tg_card,
            self.dashboard_talkgroup_value,
            self.dashboard_talkgroup_detail,
        ) = statuskarte("Sprechgruppen", "0", "keine Aktivität")
        status_grid.addWidget(geraet_card, 0, 0)
        status_grid.addWidget(kal_card, 0, 1)
        status_grid.addWidget(scan_card, 0, 2)
        status_grid.addWidget(tetra_card, 1, 0)
        status_grid.addWidget(audio_card, 1, 1)
        status_grid.addWidget(tg_card, 1, 2)
        overview_layout.addLayout(status_grid)

        actions = QtWidgets.QHBoxLayout()
        self.overview_calibrate_btn = aktionsknopf("Kalibrieren", QtWidgets.QStyle.SP_BrowserReload)
        self.overview_search_btn = aktionsknopf("Einmal suchen", QtWidgets.QStyle.SP_FileDialogContentsView)
        self.overview_stop_search_btn = aktionsknopf("Suche stoppen", QtWidgets.QStyle.SP_MediaStop)
        self.overview_decode_btn = aktionsknopf("Auswahl dekodieren", QtWidgets.QStyle.SP_MediaPlay)
        self.overview_start_scan_btn = aktionsknopf("Spektrum starten", QtWidgets.QStyle.SP_MediaPlay)
        self.overview_stop_btn = aktionsknopf("Alles stoppen", QtWidgets.QStyle.SP_MediaStop)
        self.overview_stop_search_btn.setEnabled(False)
        actions.addWidget(self.overview_calibrate_btn)
        actions.addWidget(self.overview_search_btn)
        actions.addWidget(self.overview_stop_search_btn)
        actions.addWidget(self.overview_decode_btn)
        actions.addStretch()
        actions.addWidget(self.overview_start_scan_btn)
        actions.addWidget(self.overview_stop_btn)
        overview_layout.addLayout(actions)

        self.overview_channel_table = QtWidgets.QTableWidget(0, 5)
        self.overview_channel_table.setHorizontalHeaderLabels(
            ["Frequenz", "Status", "Pegel", "Audio", "Letzte Sichtung"]
        )
        richte_tabelle_ein(self.overview_channel_table, stretch_spalte=1)
        overview_layout.addWidget(self.overview_channel_table, 1)

        tab_channels = QtWidgets.QWidget()
        channel_layout = standard_layout(tab_channels)
        kanal_toolbar = QtWidgets.QHBoxLayout()
        self.tetra_start_btn = aktionsknopf(
            "Dekodierung starten",
            QtWidgets.QStyle.SP_MediaPlay,
        )
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn = aktionsknopf("Stopp", QtWidgets.QStyle.SP_MediaStop)
        self.tetra_stop_btn.setEnabled(False)
        self.tetra_auto_cb = QtWidgets.QCheckBox("Automatisch nach Scan")
        self.tetra_search_btn = aktionsknopf("TETRA-Signale suchen", QtWidgets.QStyle.SP_FileDialogContentsView)
        self.tetra_search_stop_btn = aktionsknopf("Suche stoppen", QtWidgets.QStyle.SP_MediaStop)
        self.tetra_search_stop_btn.setEnabled(False)
        self.decode_selected_signal_btn = aktionsknopf(
            "Ausgewählte Frequenz dekodieren",
            QtWidgets.QStyle.SP_MediaPlay,
        )
        kanal_toolbar.addWidget(self.tetra_start_btn)
        kanal_toolbar.addWidget(self.tetra_stop_btn)
        kanal_toolbar.addWidget(self.tetra_auto_cb)
        kanal_toolbar.addStretch()
        kanal_toolbar.addWidget(self.tetra_search_btn)
        kanal_toolbar.addWidget(self.tetra_search_stop_btn)
        kanal_toolbar.addWidget(self.decode_selected_signal_btn)
        channel_layout.addLayout(kanal_toolbar)

        suchoptionen_layout = QtWidgets.QHBoxLayout()
        self.probe_all_candidates_cb = QtWidgets.QCheckBox("Alle gefundenen Kandidaten prüfen")
        self.probe_all_candidates_cb.setChecked(
            bool(self.config.get("tetra_probe_all_candidates", True))
        )
        self.max_candidates_spin = QtWidgets.QSpinBox()
        self.max_candidates_spin.setRange(1, 500)
        self.max_candidates_spin.setValue(
            max(1, int(self.config.get("tetra_max_candidates", 10) or 10))
        )
        self.max_candidates_spin.setEnabled(not self.probe_all_candidates_cb.isChecked())
        suchoptionen_layout.addWidget(self.probe_all_candidates_cb)
        suchoptionen_layout.addWidget(QtWidgets.QLabel("Max. Kandidaten:"))
        suchoptionen_layout.addWidget(self.max_candidates_spin)
        suchoptionen_layout.addStretch()
        channel_layout.addLayout(suchoptionen_layout)

        self.signal_search_table = QtWidgets.QTableWidget(0, 5)
        self.signal_search_table.setHorizontalHeaderLabels(
            ["Frequenz", "Pegel", "Status", "Details", "Audio"]
        )
        richte_tabelle_ein(self.signal_search_table, stretch_spalte=3)
        channel_layout.addWidget(self.signal_search_table, 2)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Regex-Filter")
        channel_layout.addWidget(self.filter_edit)
        self.tetra_output = QtWidgets.QPlainTextEdit()
        self.tetra_output.setReadOnly(True)
        self.tetra_output.setMaximumBlockCount(2000)
        channel_layout.addWidget(self.tetra_output, 1)

        tab_talkgroups = QtWidgets.QWidget()
        talk_layout = standard_layout(tab_talkgroups)
        auswahl_layout = QtWidgets.QHBoxLayout()
        self.talkgroup_filter_cb = QtWidgets.QCheckBox("Nur ausgewählte anzeigen")
        self.talkgroup_filter_cb.setChecked(
            bool(self.config.get("talkgroup_filter_enabled", False))
        )
        self.talkgroup_select_all_btn = aktionsknopf("Alle auswählen")
        self.talkgroup_select_none_btn = aktionsknopf("Auswahl löschen")
        auswahl_layout.addWidget(self.talkgroup_filter_cb)
        auswahl_layout.addStretch()
        auswahl_layout.addWidget(self.talkgroup_select_all_btn)
        auswahl_layout.addWidget(self.talkgroup_select_none_btn)
        talk_layout.addLayout(auswahl_layout)
        self.talkgroup_table = QtWidgets.QTableWidget(0, 5)
        self.talkgroup_table.setHorizontalHeaderLabels(
            ["Auswahl", "TG-ID/Adresse", "Frequenz", "Treffer", "Letzte Aktivität"]
        )
        richte_tabelle_ein(self.talkgroup_table, stretch_spalte=4)
        talk_layout.addWidget(self.talkgroup_table)

        tab_audio_data = QtWidgets.QWidget()
        audio_data_layout = standard_layout(tab_audio_data)
        audio_bar = QtWidgets.QHBoxLayout()
        audio_bar.addWidget(QtWidgets.QLabel("Aktivität:"))
        audio_bar.addWidget(self.activity_led)
        audio_bar.addSpacing(16)
        audio_bar.addWidget(QtWidgets.QLabel("Audio-Modus:"))
        self.audio_mode_combo = QtWidgets.QComboBox()
        self.audio_mode_combo.addItem("Nur unverschlüsselt", "safe")
        self.audio_mode_combo.addItem("Immer versuchen", "always")
        self.audio_mode_combo.addItem("Aus", "off")
        audio_mode = str(self.config.get("audio_mode", "safe"))
        audio_index = self.audio_mode_combo.findData(audio_mode)
        self.audio_mode_combo.setCurrentIndex(audio_index if audio_index >= 0 else 0)
        audio_bar.addWidget(self.audio_mode_combo)
        self.play_audio_cb = QtWidgets.QCheckBox("Audio aktiv")
        self.play_audio_cb.setChecked(self.audio_mode_combo.currentData() != "off")
        audio_bar.addWidget(self.play_audio_cb)
        self.record_audio_cb = QtWidgets.QCheckBox("als WAV speichern")
        self.record_audio_cb.setChecked(bool(self.config.get("record_audio", False)))
        audio_bar.addWidget(self.record_audio_cb)
        audio_bar.addStretch()
        self.audio_status_label = QtWidgets.QLabel("Audio-Status: wartet")
        self.audio_status_label.setObjectName("audioStatus")
        audio_bar.addWidget(self.audio_status_label)
        audio_data_layout.addLayout(audio_bar)

        self.decoder_data_table = QtWidgets.QTableWidget(0, 4)
        self.decoder_data_table.setHorizontalHeaderLabels(
            ["Zeit", "Frequenz", "Typ", "Inhalt"]
        )
        richte_tabelle_ein(self.decoder_data_table, stretch_spalte=3)
        audio_data_layout.addWidget(self.decoder_data_table)

        tab_network = QtWidgets.QWidget()
        network_layout = standard_layout(tab_network)
        network_split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        zellen_widget = QtWidgets.QWidget()
        zellen_layout = QtWidgets.QVBoxLayout(zellen_widget)
        zellen_layout.setContentsMargins(0, 0, 0, 0)
        self.cell_table = QtWidgets.QTableWidget(0, 5)
        self.cell_table.setHorizontalHeaderLabels(
            ["Zell-ID", "LAC", "MCC", "MNC", "Frequenz"]
        )
        richte_tabelle_ein(self.cell_table, stretch_spalte=4)
        zellen_layout.addWidget(self.cell_table)
        self.export_cells_btn = aktionsknopf("CSV-Export", QtWidgets.QStyle.SP_DialogSaveButton)
        zellen_layout.addWidget(self.export_cells_btn, alignment=QtCore.Qt.AlignRight)
        stats_widget = QtWidgets.QWidget()
        stats_layout = QtWidgets.QVBoxLayout(stats_widget)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_canvas = FigureCanvas(Figure(figsize=(4, 3)))
        self.stats_ax = self.stats_canvas.figure.add_subplot(111)
        stats_layout.addWidget(self.stats_canvas)
        network_split.addWidget(zellen_widget)
        network_split.addWidget(stats_widget)
        network_split.setSizes([260, 220])
        network_layout.addWidget(network_split)

        tab_spectrum = QtWidgets.QWidget()
        spectrum_layout = standard_layout(tab_spectrum)
        ctl_layout = QtWidgets.QHBoxLayout()
        ctl_layout.addWidget(self.start_btn)
        ctl_layout.addWidget(self.stop_btn)
        ctl_layout.addWidget(self.freq_label)
        ctl_layout.addStretch()
        self.save_png_btn = aktionsknopf("PNG speichern", QtWidgets.QStyle.SP_DialogSaveButton)
        ctl_layout.addWidget(self.save_png_btn)
        self.manual_lock_btn = aktionsknopf("Modus: Automatisch")
        self.manual_lock_btn.setCheckable(True)
        ctl_layout.addWidget(self.manual_lock_btn)
        spectrum_layout.addLayout(ctl_layout)
        spectrum_layout.addWidget(self.canvas, 2)
        spectrum_layout.addWidget(QtWidgets.QLabel("Letzte Frequenzen:"))
        spectrum_layout.addWidget(self.freq_list, 1)
        self.save_png_btn.clicked.connect(self.save_spectrum_png)
        self.manual_lock_btn.toggled.connect(self._toggle_manual_lock)

        tab_settings = QtWidgets.QWidget()
        settings_layout = standard_layout(tab_settings)
        settings_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        links = QtWidgets.QWidget()
        rechts = QtWidgets.QWidget()
        f_links = QtWidgets.QFormLayout(links)
        f_links.setLabelAlignment(QtCore.Qt.AlignRight)
        f_rechts = QtWidgets.QFormLayout(rechts)
        f_rechts.setLabelAlignment(QtCore.Qt.AlignRight)
        dev_layout = QtWidgets.QHBoxLayout()
        dev_layout.addWidget(self.device_box)
        refresh = aktionsknopf("Neu suchen", QtWidgets.QStyle.SP_BrowserReload)
        refresh.clicked.connect(self.refresh_devices)
        dev_layout.addWidget(refresh)
        f_links.addRow("Gerät:", dev_layout)
        f_links.addRow("Frequenzbereich:", self.freq_range_box)
        self.ppm_spin = QtWidgets.QSpinBox()
        self.ppm_spin.setRange(-100, 100)
        self.ppm_spin.setValue(self.config.get("ppm", 0))
        f_links.addRow("PPM:", self.ppm_spin)

        self.ref_freq_spin = QtWidgets.QDoubleSpinBox()
        self.ref_freq_spin.setRange(24.0, 1800.0)
        self.ref_freq_spin.setDecimals(4)
        self.ref_freq_spin.setSingleStep(0.0125)
        self.ref_freq_spin.setValue(float(self.config.get("calibration_ref_mhz", 99.2)))
        self.ref_freq_spin.setSuffix(" MHz")
        f_links.addRow("Referenzfrequenz:", self.ref_freq_spin)

        self.cal_span_spin = QtWidgets.QSpinBox()
        self.cal_span_spin.setRange(5, 500)
        self.cal_span_spin.setValue(int(self.config.get("calibration_search_khz", 180)))
        self.cal_span_spin.setSuffix(" kHz")
        f_links.addRow("Suchbreite ±:", self.cal_span_spin)

        kal_layout = QtWidgets.QHBoxLayout()
        self.ppm_cal_btn = aktionsknopf("PPM berechnen")
        self.gain_cal_btn = aktionsknopf("RF-Gain automatisch")
        self.full_cal_btn = aktionsknopf("Start-Kalibrierung", QtWidgets.QStyle.SP_BrowserReload)
        kal_layout.addWidget(self.ppm_cal_btn)
        kal_layout.addWidget(self.gain_cal_btn)
        kal_layout.addWidget(self.full_cal_btn)
        f_links.addRow("Kalibrierung:", kal_layout)

        self.calibrate_on_start_cb = QtWidgets.QCheckBox("beim Programmstart")
        self.calibrate_on_start_cb.setChecked(
            bool(self.config.get("calibrate_on_start", True))
        )
        self.calibration_status_label = QtWidgets.QLabel(
            "Referenz: WDR 2 Essen 99,200 MHz"
        )
        start_cal_layout = QtWidgets.QHBoxLayout()
        start_cal_layout.addWidget(self.calibrate_on_start_cb)
        start_cal_layout.addWidget(self.calibration_status_label)
        f_links.addRow("Auto-Kalibrierung:", start_cal_layout)

        rf_gain_layout = QtWidgets.QHBoxLayout()
        self.rf_gain_spin = QtWidgets.QDoubleSpinBox()
        self.rf_gain_spin.setRange(0.0, 60.0)
        self.rf_gain_spin.setDecimals(1)
        self.rf_gain_spin.setSingleStep(0.5)
        self.rf_gain_spin.setSuffix(" dB")
        self.rf_gain_max_cb = QtWidgets.QCheckBox("max")
        gain_setting = _normalize_gain_setting(self.config.get("gain", "max"))
        self.rf_gain_max_cb.setChecked(gain_setting == "max")
        self.rf_gain_spin.setEnabled(gain_setting != "max")
        self.rf_gain_spin.setValue(_resolve_gain_value(gain_setting))
        rf_gain_layout.addWidget(self.rf_gain_spin)
        rf_gain_layout.addWidget(self.rf_gain_max_cb)
        f_rechts.addRow("RF-Gain:", rf_gain_layout)

        agc_layout = QtWidgets.QHBoxLayout()
        agc_layout.addWidget(self.agc_slider)
        agc_layout.addWidget(self.agc_value)
        f_rechts.addRow("Audio-AGC-Ziel:", agc_layout)

        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("Hell", "light")
        self.theme_combo.addItem("Dunkel", "dark")
        theme_value = self.config.get("theme", "light")
        theme_index = 0 if theme_value == "light" else 1
        self.theme_combo.setCurrentIndex(theme_index)
        f_rechts.addRow("Design:", self.theme_combo)

        self.scheduler_enable_cb = QtWidgets.QCheckBox("Scheduler aktiv")
        self.scheduler_enable_cb.setChecked(self.config.get("scheduler_enabled", False))
        self.scheduler_interval_spin = QtWidgets.QSpinBox()
        self.scheduler_interval_spin.setRange(1, 1440)
        self.scheduler_interval_spin.setValue(self.config.get("scheduler_interval", 15))
        sch_lay = QtWidgets.QHBoxLayout()
        sch_lay.addWidget(self.scheduler_enable_cb)
        sch_lay.addWidget(QtWidgets.QLabel("Intervall (min):"))
        sch_lay.addWidget(self.scheduler_interval_spin)
        f_rechts.addRow("Scheduler:", sch_lay)

        self.token_edit = QtWidgets.QLineEdit(self.config.get("telegram_token", ""))
        self.chat_edit = QtWidgets.QLineEdit(self.config.get("telegram_chat", ""))
        f_rechts.addRow("Telegram Token:", self.token_edit)
        f_rechts.addRow("Chat-ID:", self.chat_edit)
        settings_split.addWidget(links)
        settings_split.addWidget(rechts)
        settings_split.setSizes([520, 520])
        settings_layout.addWidget(settings_split)

        tab_log = QtWidgets.QWidget()
        log_layout = standard_layout(tab_log)
        self.log.setMaximumBlockCount(5000)
        log_layout.addWidget(self.log)

        self.tabs.addTab(tab_overview, "Übersicht")
        self.tabs.addTab(tab_channels, "Kanäle")
        self.tabs.addTab(tab_talkgroups, "Sprechgruppen")
        self.tabs.addTab(tab_audio_data, "Audio & Daten")
        self.tabs.addTab(tab_network, "Netz")
        self.tabs.addTab(tab_spectrum, "Spektrum")
        self.tabs.addTab(tab_settings, "Einstellungen")
        self.tabs.addTab(tab_log, "Log")

    def _build_tabs(self):
        """Erstellt die Haupt-Tabs inklusive TETRA-Dekodierung."""
        # Tab 1: Spektrum & Steuerung
        tab1 = QtWidgets.QWidget()
        ctl_layout = QtWidgets.QHBoxLayout()
        ctl_layout.addWidget(self.start_btn)
        ctl_layout.addWidget(self.stop_btn)
        ctl_layout.addWidget(self.freq_label)
        self.save_png_btn = QtWidgets.QPushButton("Spektrum als PNG speichern")
        ctl_layout.addWidget(self.save_png_btn)
        self.manual_lock_btn = QtWidgets.QPushButton("Modus: Automatisch")
        self.manual_lock_btn.setCheckable(True)
        ctl_layout.addWidget(self.manual_lock_btn)

        v1 = QtWidgets.QVBoxLayout(tab1)
        v1.addLayout(ctl_layout)
        v1.addWidget(self.canvas)
        v1.addWidget(self.log)
        v1.addWidget(QtWidgets.QLabel("Letzte Frequenzen:"))
        v1.addWidget(self.freq_list)
        self.save_png_btn.clicked.connect(self.save_spectrum_png)
        self.manual_lock_btn.toggled.connect(self._toggle_manual_lock)

        # Tab 2: Audio & Aktivität
        tab2 = QtWidgets.QWidget()
        v2 = QtWidgets.QVBoxLayout(tab2)
        h_led = QtWidgets.QHBoxLayout()
        h_led.addWidget(QtWidgets.QLabel("Aktivit\u00e4t:"))
        h_led.addWidget(self.activity_led)
        h_led.addStretch()
        v2.addLayout(h_led)
        self.play_audio_cb = QtWidgets.QCheckBox("Dekodiertes Audio wiedergeben")
        self.record_audio_cb = QtWidgets.QCheckBox("als WAV speichern")
        self.audio_status_label = QtWidgets.QLabel("Audio-Status: wartet")
        v2.addWidget(self.play_audio_cb)
        v2.addWidget(self.record_audio_cb)
        v2.addWidget(self.audio_status_label)

        # Tab 3: Einstellungen
        tab3 = QtWidgets.QWidget()
        f3 = QtWidgets.QFormLayout(tab3)
        dev_layout = QtWidgets.QHBoxLayout()
        dev_layout.addWidget(self.device_box)
        refresh = QtWidgets.QPushButton("Neu suchen")
        refresh.clicked.connect(self.refresh_devices)
        dev_layout.addWidget(refresh)
        f3.addRow("Ger\u00e4t:", dev_layout)
        f3.addRow("Frequenzbereich:", self.freq_range_box)
        self.ppm_spin = QtWidgets.QSpinBox()
        self.ppm_spin.setRange(-100, 100)
        self.ppm_spin.setValue(self.config.get("ppm", 0))
        f3.addRow("PPM:", self.ppm_spin)

        self.ref_freq_spin = QtWidgets.QDoubleSpinBox()
        self.ref_freq_spin.setRange(24.0, 1800.0)
        self.ref_freq_spin.setDecimals(4)
        self.ref_freq_spin.setSingleStep(0.0125)
        self.ref_freq_spin.setValue(float(self.config.get("calibration_ref_mhz", 99.2)))
        self.ref_freq_spin.setSuffix(" MHz")
        f3.addRow("Referenzfrequenz:", self.ref_freq_spin)

        self.cal_span_spin = QtWidgets.QSpinBox()
        self.cal_span_spin.setRange(5, 500)
        self.cal_span_spin.setValue(int(self.config.get("calibration_search_khz", 180)))
        self.cal_span_spin.setSuffix(" kHz")
        f3.addRow("Suchbreite ±:", self.cal_span_spin)

        kal_layout = QtWidgets.QHBoxLayout()
        self.ppm_cal_btn = QtWidgets.QPushButton("PPM berechnen")
        self.gain_cal_btn = QtWidgets.QPushButton("RF-Gain automatisch")
        self.full_cal_btn = QtWidgets.QPushButton("Start-Kalibrierung")
        kal_layout.addWidget(self.ppm_cal_btn)
        kal_layout.addWidget(self.gain_cal_btn)
        kal_layout.addWidget(self.full_cal_btn)
        f3.addRow("Kalibrierung:", kal_layout)

        self.calibrate_on_start_cb = QtWidgets.QCheckBox("beim Programmstart")
        self.calibrate_on_start_cb.setChecked(
            bool(self.config.get("calibrate_on_start", False))
        )
        self.calibration_status_label = QtWidgets.QLabel(
            "Referenz: WDR 2 Essen 99,200 MHz"
        )
        start_cal_layout = QtWidgets.QHBoxLayout()
        start_cal_layout.addWidget(self.calibrate_on_start_cb)
        start_cal_layout.addWidget(self.calibration_status_label)
        f3.addRow("Auto-Kalibrierung:", start_cal_layout)

        rf_gain_layout = QtWidgets.QHBoxLayout()
        self.rf_gain_spin = QtWidgets.QDoubleSpinBox()
        self.rf_gain_spin.setRange(0.0, 60.0)
        self.rf_gain_spin.setDecimals(1)
        self.rf_gain_spin.setSingleStep(0.5)
        self.rf_gain_spin.setSuffix(" dB")
        self.rf_gain_max_cb = QtWidgets.QCheckBox("max")
        gain_setting = _normalize_gain_setting(self.config.get("gain", "max"))
        self.rf_gain_max_cb.setChecked(gain_setting == "max")
        self.rf_gain_spin.setEnabled(gain_setting != "max")
        self.rf_gain_spin.setValue(_resolve_gain_value(gain_setting))
        rf_gain_layout.addWidget(self.rf_gain_spin)
        rf_gain_layout.addWidget(self.rf_gain_max_cb)
        f3.addRow("RF-Gain:", rf_gain_layout)

        agc_layout = QtWidgets.QHBoxLayout()
        agc_layout.addWidget(self.agc_slider)
        agc_layout.addWidget(self.agc_value)
        f3.addRow("Audio-AGC-Ziel:", agc_layout)

        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("Hell", "light")
        self.theme_combo.addItem("Dunkel", "dark")
        theme_value = self.config.get("theme", "light")
        theme_index = 0 if theme_value == "light" else 1
        self.theme_combo.setCurrentIndex(theme_index)
        f3.addRow("Design:", self.theme_combo)

        self.scheduler_enable_cb = QtWidgets.QCheckBox("Scheduler aktiv")
        self.scheduler_enable_cb.setChecked(self.config.get("scheduler_enabled", False))
        self.scheduler_interval_spin = QtWidgets.QSpinBox()
        self.scheduler_interval_spin.setRange(1, 1440)
        self.scheduler_interval_spin.setValue(self.config.get("scheduler_interval", 15))
        sch_lay = QtWidgets.QHBoxLayout()
        sch_lay.addWidget(self.scheduler_enable_cb)
        sch_lay.addWidget(QtWidgets.QLabel("Intervall (min):"))
        sch_lay.addWidget(self.scheduler_interval_spin)
        f3.addRow("Scheduler:", sch_lay)

        self.token_edit = QtWidgets.QLineEdit(self.config.get("telegram_token", ""))
        self.chat_edit = QtWidgets.QLineEdit(self.config.get("telegram_chat", ""))
        f3.addRow("Telegram Token:", self.token_edit)
        f3.addRow("Chat-ID:", self.chat_edit)

        # Tab 4: TETRA-Dekodierung
        tab4 = QtWidgets.QWidget()
        v4 = QtWidgets.QVBoxLayout(tab4)
        ctl4 = QtWidgets.QHBoxLayout()
        self.tetra_start_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay),
            "Dekodierung starten",
        )
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn = QtWidgets.QPushButton(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MediaStop),
            "Stopp",
        )
        self.tetra_stop_btn.setEnabled(False)
        self.tetra_auto_cb = QtWidgets.QCheckBox("Automatisch nach Scan")
        self.tetra_search_btn = QtWidgets.QPushButton("TETRA-Signale suchen")
        self.tetra_search_stop_btn = QtWidgets.QPushButton("Suche stoppen")
        self.tetra_search_stop_btn.setEnabled(False)
        self.decode_selected_signal_btn = QtWidgets.QPushButton(
            "Ausgewählte Frequenz dekodieren"
        )
        ctl4.addWidget(self.tetra_start_btn)
        ctl4.addWidget(self.tetra_stop_btn)
        ctl4.addWidget(self.tetra_auto_cb)
        ctl4.addWidget(self.tetra_search_btn)
        ctl4.addWidget(self.tetra_search_stop_btn)
        ctl4.addWidget(self.decode_selected_signal_btn)
        ctl4.addStretch()
        v4.addLayout(ctl4)

        suchoptionen_layout = QtWidgets.QHBoxLayout()
        self.probe_all_candidates_cb = QtWidgets.QCheckBox("Alle gefundenen Kandidaten prüfen")
        self.probe_all_candidates_cb.setChecked(
            bool(self.config.get("tetra_probe_all_candidates", True))
        )
        self.max_candidates_spin = QtWidgets.QSpinBox()
        self.max_candidates_spin.setRange(1, 500)
        self.max_candidates_spin.setValue(
            max(1, int(self.config.get("tetra_max_candidates", 10) or 10))
        )
        self.max_candidates_spin.setEnabled(not self.probe_all_candidates_cb.isChecked())
        suchoptionen_layout.addWidget(self.probe_all_candidates_cb)
        suchoptionen_layout.addWidget(QtWidgets.QLabel("Max. Kandidaten:"))
        suchoptionen_layout.addWidget(self.max_candidates_spin)
        suchoptionen_layout.addStretch()
        v4.addLayout(suchoptionen_layout)

        self.signal_search_table = QtWidgets.QTableWidget(0, 5)
        self.signal_search_table.setHorizontalHeaderLabels(
            ["Frequenz", "Pegel", "Status", "Details", "Audio"]
        )
        self.signal_search_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.signal_search_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.signal_search_table.horizontalHeader().setStretchLastSection(False)
        self.signal_search_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents
        )
        self.signal_search_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )
        self.signal_search_table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents
        )
        self.signal_search_table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.Stretch
        )
        self.signal_search_table.horizontalHeader().setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeToContents
        )
        v4.addWidget(self.signal_search_table)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Regex-Filter")
        v4.addWidget(self.filter_edit)
        self.tetra_output = QtWidgets.QPlainTextEdit()
        self.tetra_output.setReadOnly(True)
        v4.addWidget(self.tetra_output)

        # Tab 5: Zellen
        tab5 = QtWidgets.QWidget()
        v5 = QtWidgets.QVBoxLayout(tab5)
        self.cell_table = QtWidgets.QTableWidget(0, 5)
        self.cell_table.setHorizontalHeaderLabels(
            ["Zell-ID", "LAC", "MCC", "MNC", "Frequenz"]
        )
        v5.addWidget(self.cell_table)
        self.export_cells_btn = QtWidgets.QPushButton("CSV-Export")
        v5.addWidget(self.export_cells_btn)

        # Tab 6: Paketstatistik
        tab6 = QtWidgets.QWidget()
        v6 = QtWidgets.QVBoxLayout(tab6)
        self.stats_canvas = FigureCanvas(Figure(figsize=(4,3)))
        self.stats_ax = self.stats_canvas.figure.add_subplot(111)
        v6.addWidget(self.stats_canvas)

        # Tab 7: Daten
        tab7 = QtWidgets.QWidget()
        v7 = QtWidgets.QVBoxLayout(tab7)
        self.decoder_data_table = QtWidgets.QTableWidget(0, 4)
        self.decoder_data_table.setHorizontalHeaderLabels(
            ["Zeit", "Frequenz", "Typ", "Inhalt"]
        )
        self.decoder_data_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents
        )
        self.decoder_data_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )
        self.decoder_data_table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents
        )
        self.decoder_data_table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.Stretch
        )
        v7.addWidget(self.decoder_data_table)

        # Tab 8: Sprechgruppen
        tab8 = QtWidgets.QWidget()
        v8 = QtWidgets.QVBoxLayout(tab8)
        self.talkgroup_table = QtWidgets.QTableWidget(0, 5)
        self.talkgroup_table.setHorizontalHeaderLabels(
            ["Auswahl", "TG-ID/Adresse", "Frequenz", "Treffer", "Letzte Aktivität"]
        )
        self.talkgroup_table.horizontalHeader().setStretchLastSection(True)
        self.talkgroup_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents
        )
        self.talkgroup_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )
        self.talkgroup_table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents
        )
        self.talkgroup_table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeToContents
        )
        auswahl_layout = QtWidgets.QHBoxLayout()
        self.talkgroup_filter_cb = QtWidgets.QCheckBox("Nur ausgewählte anzeigen")
        self.talkgroup_filter_cb.setChecked(
            bool(self.config.get("talkgroup_filter_enabled", False))
        )
        self.talkgroup_select_all_btn = QtWidgets.QPushButton("Alle auswählen")
        self.talkgroup_select_none_btn = QtWidgets.QPushButton("Auswahl löschen")
        auswahl_layout.addWidget(self.talkgroup_filter_cb)
        auswahl_layout.addWidget(self.talkgroup_select_all_btn)
        auswahl_layout.addWidget(self.talkgroup_select_none_btn)
        auswahl_layout.addStretch()
        v8.addLayout(auswahl_layout)
        v8.addWidget(self.talkgroup_table)

        self.tabs.addTab(tab1, "Spektrum & Steuerung")
        self.tabs.addTab(tab2, "Audio & Aktivit\u00e4t")
        self.tabs.addTab(tab3, "Einstellungen")
        self.tabs.addTab(tab4, "TETRA-Dekodierung")
        self.tabs.addTab(tab5, "Zellen")
        self.tabs.addTab(tab6, "Statistik")
        self.tabs.addTab(tab7, "Daten")
        self.tabs.addTab(tab8, "Sprechgruppen")

    def refresh_devices(self):
        """Füllt die Geräteauswahl mit erkannten SDR-Geräten."""
        self.device_box.clear()
        for label, device_id in list_sdr_devices():
            self.device_box.addItem(label, device_id)
        self._refresh_dashboard_status()

    def _audio_mode(self):
        if not hasattr(self, "audio_mode_combo"):
            return str(self.config.get("audio_mode", "safe"))
        return str(self.audio_mode_combo.currentData() or "safe")

    def _audio_mode_text(self):
        modus = self._audio_mode()
        if modus == "always":
            return "immer versuchen"
        if modus == "off":
            return "aus"
        return "nur unverschlüsselt"

    def _on_audio_mode_change(self, _index: int):
        modus = self._audio_mode()
        self.config["audio_mode"] = modus
        if hasattr(self, "play_audio_cb"):
            aktiv = modus != "off"
            if self.play_audio_cb.isChecked() != aktiv:
                self.play_audio_cb.blockSignals(True)
                self.play_audio_cb.setChecked(aktiv)
                self.play_audio_cb.blockSignals(False)
        self._refresh_dashboard_status()

    def _set_audio_mode(self, modus: str):
        if not hasattr(self, "audio_mode_combo"):
            self.config["audio_mode"] = modus
            return
        index = self.audio_mode_combo.findData(modus)
        if index < 0:
            index = 0
        self.audio_mode_combo.setCurrentIndex(index)

    def _refresh_dashboard_status(self):
        if not hasattr(self, "dashboard_device_value"):
            return
        name, device_id = self._current_device_info()
        if name:
            self.dashboard_device_value.setText(name)
            detail = f"Index {device_id}" if device_id is not None else "ohne festen Index"
            self.dashboard_device_detail.setText(detail)
        else:
            self.dashboard_device_value.setText("kein Gerät")
            self.dashboard_device_detail.setText("RTL-SDR nicht erkannt")

        ppm_text = f"PPM {self.config.get('ppm', 0)}"
        gain_text = _normalize_gain_setting(self.config.get("gain", "max"))
        if gain_text == "max":
            gain_text = "Gain max"
        else:
            gain_text = f"Gain {float(gain_text):.1f} dB"
        self.dashboard_calibration_value.setText(ppm_text)
        self.dashboard_calibration_detail.setText(gain_text)

        suche_laeuft = bool(
            self.tetra_signal_search and self.tetra_signal_search.isRunning()
        )
        if self.monitoring_active:
            scan_text = "läuft dauerhaft"
        elif suche_laeuft:
            scan_text = "Suche läuft"
        elif hasattr(self, "scanner") and self.scanner._running.is_set():
            scan_text = "Spektrum läuft"
        else:
            scan_text = "gestoppt"
        self.dashboard_scan_value.setText(scan_text)
        self.dashboard_scan_detail.setText(self.freq_range_box.currentText())

        bestaetigt = 0
        if hasattr(self, "overview_channel_table"):
            for row in range(self.overview_channel_table.rowCount()):
                status_item = self.overview_channel_table.item(row, 1)
                if status_item and "bestätigt" in status_item.text():
                    bestaetigt += 1
        self.dashboard_tetra_value.setText(f"{bestaetigt} bestätigt")
        if hasattr(self, "current_frequency") and self.current_frequency is not None:
            self.dashboard_tetra_detail.setText(f"{self.current_frequency/1e6:.4f} MHz")
        else:
            self.dashboard_tetra_detail.setText("keine aktive Frequenz")

        status = self.audio_status_label.text().replace("Audio-Status:", "").strip()
        self.dashboard_audio_value.setText(status or "wartet")
        self.dashboard_audio_detail.setText(f"Modus: {self._audio_mode_text()}")

        talkgroups = getattr(self, "talkgroups", {})
        selected_talkgroups = getattr(self, "selected_talkgroups", set())
        self.dashboard_talkgroup_value.setText(str(len(talkgroups)))
        if selected_talkgroups:
            self.dashboard_talkgroup_detail.setText(
                f"{len(selected_talkgroups)} ausgewählt"
            )
        else:
            self.dashboard_talkgroup_detail.setText("alle anzeigen")

    def _upsert_overview_candidate(self, info: dict):
        if not hasattr(self, "overview_channel_table"):
            return
        freq = float(info.get("frequency_hz") or 0)
        if freq <= 0:
            return
        key = int(round(freq))
        row = self._overview_signal_rows.get(key)
        if row is None:
            row = self.overview_channel_table.rowCount()
            self.overview_channel_table.insertRow(row)
            self._overview_signal_rows[key] = row

        status = str(info.get("status", ""))
        werte = [
            f"{freq/1e6:.4f} MHz",
            status,
            f"{float(info.get('power', 0.0)):.1f} dB",
            str(info.get("audio", "")),
            datetime.now().strftime("%H:%M:%S"),
        ]
        farbe = None
        if status == "bestätigt":
            farbe = QtGui.QColor("#d9f7df")
        elif status in ("unklar", "möglich"):
            farbe = QtGui.QColor("#fff4c4")
        elif status in ("Fehler", "kein TETRA"):
            farbe = QtGui.QColor("#f8d7da")
        for spalte, wert in enumerate(werte):
            item = QtWidgets.QTableWidgetItem(wert)
            if spalte == 0:
                item.setData(QtCore.Qt.UserRole, freq)
            if farbe is not None:
                item.setBackground(farbe)
            self.overview_channel_table.setItem(row, spalte, item)
        self._refresh_dashboard_status()

    def _toggle_monitoring(self, enabled: bool):
        if enabled:
            self.start_monitoring()
        else:
            self.stop_monitoring()

    def start_monitoring(self):
        if self.monitoring_active:
            return
        self.monitoring_active = True
        self.overview_monitor_btn.setText("Überwachung stoppen")
        self.log.appendPlainText("Dauerhafte TETRA-Überwachung gestartet.")
        self._refresh_dashboard_status()
        self._run_monitoring_cycle()

    def stop_monitoring(self):
        if not self.monitoring_active and not self.monitor_timer.isActive():
            return
        self.monitoring_active = False
        self.monitor_timer.stop()
        if hasattr(self, "overview_monitor_btn"):
            self.overview_monitor_btn.blockSignals(True)
            self.overview_monitor_btn.setChecked(False)
            self.overview_monitor_btn.setText("Überwachung starten")
            self.overview_monitor_btn.blockSignals(False)
        self.stop_tetra_signal_search(wait=False)
        self.log.appendPlainText("Dauerhafte TETRA-Überwachung gestoppt.")
        self._refresh_dashboard_status()

    def _run_monitoring_cycle(self):
        if not self.monitoring_active:
            return
        if self.calibration_worker and self.calibration_worker.isRunning():
            self.monitor_timer.start(2000)
            return
        if self.tetra_signal_search and self.tetra_signal_search.isRunning():
            return
        self.start_tetra_signal_search()

    def _current_device_info(self):
        name = self.device_box.currentText()
        device_id = self.device_box.currentData()
        if isinstance(device_id, str) and device_id.strip().isdigit():
            device_id = int(device_id)
        if isinstance(device_id, int):
            return name, device_id
        return name, None

    def _update_agc(self, value):
        """Aktualisiert den AGC-Pegel aus dem Schieberegler."""
        self.agc_value.setText(str(value))
        self.player.agc_level = value
        self.config["audio_agc_level"] = int(value)

    def _update_ppm(self, value: int):
        """Aktualisiert die PPM-Korrektur für alle SDR-Befehle."""
        self.config["ppm"] = value
        self.scanner.ppm = value
        self.player.ppm = value
        self.decoder.ppm = value
        self._refresh_dashboard_status()

    def _on_freq_range_change(self, _index: int):
        self.config["freq_range_label"] = self.freq_range_box.currentText()
        self._refresh_dashboard_status()

    def _on_probe_all_candidates_change(self, enabled: bool):
        self.max_candidates_spin.setEnabled(not enabled)
        self.config["tetra_probe_all_candidates"] = bool(enabled)
        self.config["tetra_max_candidates"] = int(self.max_candidates_spin.value())

    def _apply_gain_setting(self, setting):
        gain_setting = _normalize_gain_setting(setting)
        self.config["gain"] = gain_setting
        if hasattr(self, "scanner"):
            self.scanner.gain = gain_setting
        if hasattr(self, "player"):
            self.player.gain = gain_setting
        if hasattr(self, "decoder"):
            self.decoder.gain = gain_setting
        self._refresh_dashboard_status()

    def _update_rf_gain(self, value: float):
        if self.rf_gain_max_cb.isChecked():
            return
        self._apply_gain_setting(float(value))

    def _toggle_rf_gain_max(self, enabled: bool):
        self.rf_gain_spin.setEnabled(not enabled)
        if enabled:
            self._apply_gain_setting("max")
        else:
            self._apply_gain_setting(float(self.rf_gain_spin.value()))

    def start_calibration(self, mode: str = "both"):
        """Startet PPM- und/oder RF-Gain-Kalibrierung auf der Referenzfrequenz."""
        if self.calibration_worker and self.calibration_worker.isRunning():
            self.log.appendPlainText("Kalibrierung läuft bereits.")
            return
        self.scanner.stop()
        self.player.stop()
        self.stop_decoding()
        name, device_id = self._current_device_info()
        reference_hz = float(self.ref_freq_spin.value()) * 1e6
        search_span_hz = float(self.cal_span_spin.value()) * 1e3
        self.calibration_status_label.setText("Kalibrierung läuft...")
        self._refresh_dashboard_status()
        self.log.appendPlainText(
            f"Kalibrierung mit Gerät {name} auf {reference_hz/1e6:.4f} MHz."
        )
        worker = CalibrationWorker(
            mode=mode,
            reference_hz=reference_hz,
            search_span_hz=search_span_hz,
            device_id=device_id,
            ppm=int(self.ppm_spin.value()),
            gain=self.config.get("gain", "max"),
            parent=self,
        )
        worker.log.connect(self.log.appendPlainText)
        worker.log.connect(logger.info)
        worker.ppm_ready.connect(self._apply_ppm_calibration)
        worker.gain_ready.connect(self._apply_gain_calibration)
        worker.finished.connect(self._calibration_finished)
        self.calibration_worker = worker
        worker.start()

    def stop_calibration(self, wait=False):
        worker = self.calibration_worker
        if not worker or not worker.isRunning():
            return
        worker.stop()
        if wait:
            worker.wait(2000)

    @QtCore.pyqtSlot(dict)
    def _apply_ppm_calibration(self, result: dict):
        new_ppm = int(result.get("new_ppm", self.ppm_spin.value()))
        self.ppm_spin.setValue(new_ppm)
        warnung = f" ({result['warning']})" if result.get("warning") else ""
        text = (
            f"PPM {result['old_ppm']} -> {new_ppm} "
            f"(Restfehler {result['residual_hz']:+.1f} Hz, "
            f"SNR {result['snr_db']:.1f} dB){warnung}"
        )
        self.calibration_status_label.setText(text)
        self.log.appendPlainText(text)
        self._refresh_dashboard_status()

    @QtCore.pyqtSlot(dict)
    def _apply_gain_calibration(self, result: dict):
        gain = float(result.get("gain", _resolve_gain_value(self.config.get("gain", "max"))))
        self.rf_gain_max_cb.blockSignals(True)
        self.rf_gain_max_cb.setChecked(False)
        self.rf_gain_max_cb.blockSignals(False)
        self.rf_gain_spin.setEnabled(True)
        self.rf_gain_spin.blockSignals(True)
        self.rf_gain_spin.setValue(gain)
        self.rf_gain_spin.blockSignals(False)
        self._apply_gain_setting(gain)
        text = (
            f"RF-Gain automatisch: {gain:.1f} dB "
            f"(SNR {result.get('snr_db', 0.0):.1f} dB, "
            f"Clipping {result.get('clipped', 0.0)*100:.2f}%)"
        )
        self.calibration_status_label.setText(text)
        self.log.appendPlainText(text)
        self._refresh_dashboard_status()

    @QtCore.pyqtSlot()
    def _calibration_finished(self):
        if self.calibration_status_label.text() == "Kalibrierung läuft...":
            self.calibration_status_label.setText("Kalibrierung beendet.")
        self.calibration_worker = None
        self._refresh_dashboard_status()

    @QtCore.pyqtSlot(np.ndarray, np.ndarray)
    def _update_scan_results(self, freqs, powers):
        """Aggregiert Scan-Peaks und aktualisiert die Frequenzliste."""
        if freqs is None or powers is None or len(freqs) == 0 or len(powers) == 0:
            return

        bin_hz = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0
        if bin_hz <= 0:
            return

        bin_indices = np.rint(freqs / bin_hz).astype(int)
        for idx, freq, power in zip(bin_indices, freqs, powers):
            current = self.scan_results.get(idx)
            if current is None or power > current["power"]:
                self.scan_results[idx] = {"freq": freq, "power": power}

        if len(self.scan_results) > 200:
            top_items = sorted(
                self.scan_results.items(),
                key=lambda item: item[1]["power"],
                reverse=True,
            )[:200]
            self.scan_results = dict(top_items)

        top_peaks = sorted(
            self.scan_results.values(),
            key=lambda item: item["power"],
            reverse=True,
        )[:20]

        self.freq_list.clear()
        for entry in top_peaks:
            freq_mhz = entry["freq"] / 1e6
            text = f"{freq_mhz:.3f} MHz \u2013 {entry['power']:.1f} dB"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, entry["freq"])
            self.freq_list.addItem(item)

    @QtCore.pyqtSlot(float)
    def update_frequency(self, freq):
        """Neue Frequenzauswahl verarbeiten."""
        if self.manual_lock:
            self.log.appendPlainText(
                f"Automatische Frequenz ignoriert (Manuell aktiv): {freq/1e6:.3f} MHz"
            )
            self.freq_history.appendleft(freq / 1e6)
            return
        self._set_frequency_and_process(freq, source="scan")

    @QtCore.pyqtSlot(QtWidgets.QListWidgetItem)
    def _select_frequency_from_list(self, item):
        """Frequenz aus der Liste ausw\u00e4hlen und manuell tunen."""
        freq = item.data(QtCore.Qt.UserRole)
        if not freq:
            return
        self._set_manual_lock(True)
        self._set_frequency_and_process(freq, source="manual")

    def _set_frequency_and_process(self, freq, source="manual"):
        """Gemeinsamer Einstieg zum Setzen der Frequenz und Starten des Players."""
        self.freq_label.setText(f"Frequenz: {freq/1e6:.3f} MHz")
        if source == "manual":
            self.log.appendPlainText(f"Manuell ausgew\u00e4hlt: {freq/1e6:.3f} MHz")
        else:
            self.log.appendPlainText(f"Gew\u00e4hlte Frequenz: {freq/1e6:.3f} MHz")
        self.freq_history.appendleft(freq / 1e6)
        self.current_frequency = freq
        self.player.start(freq)
        self.tetra_start_btn.setEnabled(True)
        if self.tetra_auto_cb.isChecked():
            self.start_decoding()
        self._refresh_dashboard_status()

    def _set_manual_lock(self, enabled: bool):
        self.manual_lock = enabled
        if self.manual_lock_btn.isChecked() != enabled:
            self.manual_lock_btn.blockSignals(True)
            self.manual_lock_btn.setChecked(enabled)
            self.manual_lock_btn.blockSignals(False)
        status = "Manuell" if enabled else "Automatisch"
        self.manual_lock_btn.setText(f"Modus: {status}")
        self.log.appendPlainText(f"Modus gewechselt: {status}")

    def _toggle_manual_lock(self, enabled: bool):
        self._set_manual_lock(enabled)

    @QtCore.pyqtSlot()
    def notify_activity(self):
        """Visuelle Anzeige, wenn Aktivität erkannt wird."""
        self.activity_led.set_color("red")
        QtCore.QTimer.singleShot(500, lambda: self.activity_led.set_color("green"))

    def start_decoding(self):
        """Startet die TETRA-Dekodierkette."""
        if self.current_frequency is None:
            return
        name, device_id = self._current_device_info()
        self.stop_calibration(wait=True)
        self.stop_tetra_signal_search(wait=True)
        self._update_ppm(self.ppm_spin.value())
        self.decoder.device_id = device_id
        self.decoder.gain = _normalize_gain_setting(self.config.get("gain", "max"))
        self.scanner.stop()
        self.player.stop()
        self.tetra_start_btn.setEnabled(False)
        self.tetra_stop_btn.setEnabled(True)
        self.tetra_output.clear()
        rec = self.record_audio_cb.isChecked()
        audio_mode = self._audio_mode()
        audio_requested = audio_mode != "off" and self.play_audio_cb.isChecked()
        if audio_requested and self.decoder.audio_output_supported():
            self.dec_audio_player.start(record=rec)
            if audio_mode == "always":
                self.audio_status_label.setText("Audio-Status: Wiedergabe aktiv")
            else:
                self.audio_status_label.setText("Audio-Status: wartet auf unverschlüsselte Sprache")
        elif audio_requested:
            self.audio_status_label.setText(
                "Audio-Status: keine audiofähige Decoder-Kette verfügbar"
            )
            self.tetra_output.appendPlainText(
                "Audioausgabe ist nur bei unverschlüsselter Sprache und "
                "audiofähiger Decoder-Kette möglich."
            )
        else:
            self.audio_status_label.setText("Audio-Status: ausgeschaltet")
        self._refresh_dashboard_status()
        if device_id is None:
            device_text = "ohne Index"
        else:
            device_text = f"Index {device_id}"
        self.log.appendPlainText(
            f"Dekodierung gestartet mit Gerät {device_text} ({name}) "
            f"bei {self.current_frequency/1e6:.3f} MHz"
        )
        self.decoder.start(self.current_frequency)

    def stop_decoding(self):
        """Stoppt die TETRA-Dekodierung."""
        self.decoder.stop()
        self.dec_audio_player.stop()
        self.audio_status_label.setText("Audio-Status: gestoppt")
        self._refresh_dashboard_status()

    def start_tetra_signal_search(self):
        """Sucht echte TETRA-Signale und prüft Kandidaten mit dem Dekoder."""
        if self.tetra_signal_search and self.tetra_signal_search.isRunning():
            return

        name, device_id = self._current_device_info()
        self.stop_calibration(wait=True)
        self.stop_decoding()
        self.scanner.stop()
        self.player.stop()
        self._update_ppm(self.ppm_spin.value())
        gain_setting = _normalize_gain_setting(self.config.get("gain", "max"))
        self.config["gain"] = gain_setting

        ranges = []
        for index in range(self.freq_range_box.count()):
            data = self.freq_range_box.itemData(index)
            if not data:
                continue
            ranges.append((self.freq_range_box.itemText(index), data[0], data[1]))
        if not ranges:
            ranges = TETRA_DEFAULT_RANGES

        if self.probe_all_candidates_cb.isChecked():
            max_candidates = None
            limit_text = "alle gefundenen Kandidaten"
        else:
            max_candidates = int(self.max_candidates_spin.value())
            limit_text = f"maximal {max_candidates} Kandidaten"

        self.signal_search_table.setRowCount(0)
        self._signal_search_rows = {}
        self._set_signal_search_buttons(True)
        self.log.appendPlainText(
            f"TETRA-Signalsuche gestartet mit Gerät {name}, PPM {self.ppm_spin.value()}, "
            f"Gain {_resolve_gain_value(gain_setting):.1f} dB, {limit_text}."
        )
        self.tetra_output.appendPlainText("TETRA-Signalsuche gestartet.")

        worker = TetraSignalSearchWorker(
            ranges=ranges,
            device_id=device_id,
            ppm=self.ppm_spin.value(),
            gain=gain_setting,
            scan_seconds=5,
            probe_seconds=6,
            max_candidates=max_candidates,
            parent=self,
        )
        worker.log.connect(self._append_signal_search_log)
        worker.candidate.connect(self._upsert_signal_candidate)
        worker.finished.connect(self._tetra_signal_search_finished)
        self.tetra_signal_search = worker
        worker.start()

    def stop_tetra_signal_search(self, wait=False):
        """Stoppt die laufende TETRA-Signalsuche."""
        worker = self.tetra_signal_search
        if not worker or not worker.isRunning():
            return
        worker.stop()
        if wait:
            worker.wait(2000)
        self._set_signal_search_buttons(False)

    def _set_signal_search_buttons(self, running: bool):
        self.tetra_search_btn.setEnabled(not running)
        self.tetra_search_stop_btn.setEnabled(running)
        if hasattr(self, "overview_search_btn"):
            self.overview_search_btn.setEnabled(not running)
        if hasattr(self, "overview_stop_search_btn"):
            self.overview_stop_search_btn.setEnabled(running)
        self._refresh_dashboard_status()

    @QtCore.pyqtSlot(str)
    def _append_signal_search_log(self, text: str):
        self.log.appendPlainText(text)
        self.tetra_output.appendPlainText(f"[Signalsuche] {text}")
        logger.info(text)

    @QtCore.pyqtSlot(dict)
    def _upsert_signal_candidate(self, info: dict):
        self._upsert_overview_candidate(info)
        freq = float(info.get("frequency_hz") or 0)
        if freq <= 0:
            return
        key = int(round(freq))
        row = self._signal_search_rows.get(key)
        if row is None:
            row = self.signal_search_table.rowCount()
            self.signal_search_table.insertRow(row)
            self._signal_search_rows[key] = row

        status = str(info.get("status", ""))
        values = [
            f"{freq/1e6:.4f} MHz",
            f"{float(info.get('power', 0.0)):.1f} dB",
            status,
            str(info.get("details", "")),
            str(info.get("audio", "")),
        ]
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            if column == 0:
                item.setData(QtCore.Qt.UserRole, freq)
            if status == "bestätigt":
                item.setBackground(QtGui.QColor("#c8f7c5"))
            elif status in ("unklar", "möglich"):
                item.setBackground(QtGui.QColor("#fff4bf"))
            elif status in ("Fehler", "kein TETRA"):
                item.setBackground(QtGui.QColor("#f5d0d0"))
            self.signal_search_table.setItem(row, column, item)

        lines = info.get("lines") or []
        if lines and status in ("bestätigt", "unklar"):
            for line in lines[:80]:
                self.tetra_output.appendPlainText(f"[{freq/1e6:.4f} MHz] {line}")
                self._append_decoder_data(line)
                if status == "bestätigt":
                    self.current_frequency = freq
                    self.parse_cell_info(line)
                    self.parse_network_info(line)
                    self.parse_packet_type(line)
                    self.parse_talkgroups(line)
            if status == "bestätigt":
                self.freq_label.setText(f"Frequenz: {freq/1e6:.3f} MHz")
                self.tetra_start_btn.setEnabled(True)
                self.signal_search_table.selectRow(row)
                self.log.appendPlainText(
                    f"TETRA-Signal bestätigt auf {freq/1e6:.4f} MHz."
                )
        self._refresh_dashboard_status()

    @QtCore.pyqtSlot()
    def _tetra_signal_search_finished(self):
        self._set_signal_search_buttons(False)
        self.log.appendPlainText("TETRA-Signalsuche beendet.")
        self.tetra_output.appendPlainText("TETRA-Signalsuche beendet.")
        self.tetra_signal_search = None
        if self.monitoring_active:
            delay_ms = int(self.config.get("monitor_cycle_delay_sec", 5)) * 1000
            self.monitor_timer.start(max(1000, delay_ms))
        self._refresh_dashboard_status()

    def _selected_signal_candidate(self):
        row = self.signal_search_table.currentRow()
        tabelle = self.signal_search_table
        status_spalte = 2
        if row < 0 and hasattr(self, "overview_channel_table"):
            row = self.overview_channel_table.currentRow()
            tabelle = self.overview_channel_table
            status_spalte = 1
        if row < 0:
            return None
        freq_item = tabelle.item(row, 0)
        status_item = tabelle.item(row, status_spalte)
        if not freq_item:
            return None
        freq = freq_item.data(QtCore.Qt.UserRole)
        if not freq:
            try:
                freq = float(freq_item.text().split()[0].replace(",", ".")) * 1e6
            except (ValueError, IndexError):
                return None
        status = status_item.text() if status_item else ""
        return float(freq), status

    @QtCore.pyqtSlot(QtWidgets.QTableWidgetItem)
    def _decode_signal_candidate_from_item(self, item):
        if hasattr(self, "overview_channel_table") and item.tableWidget() is self.overview_channel_table:
            self.signal_search_table.clearSelection()
            self.signal_search_table.setCurrentCell(-1, -1)
        elif item.tableWidget() is self.signal_search_table and hasattr(self, "overview_channel_table"):
            self.overview_channel_table.clearSelection()
            self.overview_channel_table.setCurrentCell(-1, -1)
        self.decode_selected_signal_candidate()

    def decode_selected_signal_candidate(self):
        """Übernimmt die markierte Suchfrequenz und startet die TETRA-Dekodierung."""
        selected = self._selected_signal_candidate()
        if not selected:
            self.log.appendPlainText("Bitte zuerst eine Frequenz aus der Signalsuche markieren.")
            return
        freq, status = selected
        self.stop_monitoring()
        self.stop_tetra_signal_search(wait=True)
        self._set_manual_lock(True)
        self.freq_label.setText(f"Frequenz: {freq/1e6:.3f} MHz")
        self.freq_history.appendleft(freq / 1e6)
        self.current_frequency = freq
        self.tetra_start_btn.setEnabled(True)
        if status != "bestätigt":
            self.log.appendPlainText(
                f"Frequenz {freq/1e6:.4f} MHz ist nicht bestätigt ({status}); "
                "Dekodierung wird trotzdem gestartet."
            )
        else:
            self.log.appendPlainText(
                f"Bestätigte TETRA-Frequenz übernommen: {freq/1e6:.4f} MHz."
            )
        self._refresh_dashboard_status()
        self.start_decoding()

    def _toggle_dec_audio(self, enabled: bool):
        if enabled and self._audio_mode() == "off":
            self._set_audio_mode("safe")
        elif not enabled and self._audio_mode() != "off":
            self._set_audio_mode("off")
        if enabled and self.decoder._running.is_set():
            self.dec_audio_player.start(record=self.record_audio_cb.isChecked())
        else:
            self.dec_audio_player.stop()
        self._refresh_dashboard_status()

    def _encrypted_signal(self):
        self.dec_audio_player.stop()
        self.audio_status_label.setText("Audio-Status: Signal verschlüsselt")
        self._refresh_dashboard_status()
        QtWidgets.QMessageBox.information(self, "Info", "Verschl\u00fcsseltes Signal erkannt")

    def _append_tetra(self, line: str):
        if not self._line_matches_selected_talkgroup(line):
            return
        flt = self.filter_edit.text()
        if flt:
            try:
                if not re.search(flt, line):
                    return
            except re.error:
                pass
        self.tetra_output.appendPlainText(line)
        logger.info(line)
        self._append_decoder_data(line)
        if line.startswith("Audioausgabe:"):
            self.audio_status_label.setText(f"Audio-Status: {line.split(':', 1)[1].strip()}")
            self._refresh_dashboard_status()
        self.parse_cell_info(line)
        self.parse_network_info(line)
        self.parse_packet_type(line)
        self.parse_talkgroups(line)

    def _decoder_finished(self):
        self.tetra_start_btn.setEnabled(True)
        self.tetra_stop_btn.setEnabled(False)
        self.dec_audio_player.stop()
        self.audio_status_label.setText("Audio-Status: Dekoder gestoppt")
        self._refresh_dashboard_status()

    def start(self):
        self.stop_calibration(wait=True)
        self.stop_tetra_signal_search(wait=True)
        name, device_id = self._current_device_info()
        self.scanner.device = name
        self.player.device = name
        self.scanner.device_id = device_id
        self.player.device_id = device_id
        gain_setting = _normalize_gain_setting(self.config.get("gain", "max"))
        self.config["gain"] = gain_setting
        self.scanner.gain = gain_setting
        self.player.gain = gain_setting
        self.decoder.gain = gain_setting
        self.decoder.device_id = device_id
        self._update_ppm(self.ppm_spin.value())
        rng = self.freq_range_box.currentData()
        f_start, f_end = rng if rng else (380e6, 430e6)
        if device_id is None:
            device_text = "ohne Index"
        else:
            device_text = f"Index {device_id}"
        self.log.appendPlainText(
            f"Scan gestartet mit Gerät {device_text} ({name}) "
            f"({f_start/1e6:.0f}-{f_end/1e6:.0f} MHz)"
        )
        self.scanner.start(f_start, f_end)
        self._refresh_dashboard_status()

    def stop(self):
        self.log.appendPlainText("Stoppe")
        self.stop_monitoring()
        self.stop_calibration(wait=True)
        self.stop_tetra_signal_search(wait=True)
        self.scanner.stop()
        self.player.stop()
        self.stop_decoding()
        self._refresh_dashboard_status()

    def closeEvent(self, event):
        self.stop_calibration(wait=True)
        self.stop_tetra_signal_search(wait=True)
        self.stop()
        self._store_current_settings()
        self._persist_talkgroups_to_config()
        self._persist_selected_talkgroups_to_config()
        save_config(self.config)
        super().closeEvent(event)

    # ----- Hilfsmethoden -----
    def _store_current_settings(self):
        self.config["ppm"] = int(self.ppm_spin.value())
        self.config["audio_agc_level"] = int(self.agc_slider.value())
        self.config["freq_range_label"] = self.freq_range_box.currentText()
        self.config["calibration_ref_mhz"] = float(self.ref_freq_spin.value())
        self.config["calibration_search_khz"] = int(self.cal_span_spin.value())
        self.config["calibrate_on_start"] = bool(self.calibrate_on_start_cb.isChecked())
        self.config["audio_mode"] = self._audio_mode()
        self.config["record_audio"] = bool(self.record_audio_cb.isChecked())
        self.config["ui_profile_version"] = 2
        self.config["tetra_probe_all_candidates"] = bool(
            self.probe_all_candidates_cb.isChecked()
        )
        self.config["tetra_max_candidates"] = int(self.max_candidates_spin.value())
        if self.rf_gain_max_cb.isChecked():
            self.config["gain"] = "max"
        else:
            self.config["gain"] = float(self.rf_gain_spin.value())

    def _modern_light_stylesheet(self):
        return """
        QMainWindow, QWidget {
            background: #f5f7fa;
            color: #17202a;
            font-size: 10.5pt;
        }
        QTabWidget::pane {
            border: 1px solid #ccd5df;
            background: #ffffff;
            top: -1px;
        }
        QTabBar::tab {
            background: #e8edf2;
            color: #243447;
            border: 1px solid #ccd5df;
            padding: 8px 14px;
            margin-right: 2px;
            min-width: 92px;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            border-bottom-color: #ffffff;
            color: #0b5cad;
        }
        QLabel#appTitle {
            font-size: 22pt;
            font-weight: 700;
            color: #0f2437;
        }
        QLabel#appSubtitle {
            color: #607080;
            font-size: 10pt;
        }
        QFrame#statusCard {
            background: #ffffff;
            border: 1px solid #d9e1ea;
            border-radius: 8px;
        }
        QLabel#statusTitle {
            color: #607080;
            font-size: 9pt;
        }
        QLabel#statusValue {
            color: #102030;
            font-size: 16pt;
            font-weight: 700;
        }
        QLabel#statusDetail {
            color: #607080;
            font-size: 9pt;
        }
        QPushButton {
            background: #ffffff;
            border: 1px solid #b7c2cf;
            border-radius: 6px;
            padding: 7px 11px;
        }
        QPushButton:hover {
            border-color: #3c7dc4;
            background: #f2f7fd;
        }
        QPushButton:pressed {
            background: #dceafa;
        }
        QPushButton:disabled {
            color: #8b98a8;
            background: #edf1f5;
        }
        QPushButton[klasse="primaer"] {
            color: #ffffff;
            background: #0b5cad;
            border-color: #0b5cad;
            font-weight: 700;
        }
        QPushButton[klasse="primaer"]:checked {
            background: #b73d2f;
            border-color: #b73d2f;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
            background: #ffffff;
            border: 1px solid #c5cfda;
            border-radius: 5px;
            padding: 5px;
        }
        QTableWidget {
            background: #ffffff;
            alternate-background-color: #f7f9fb;
            border: 1px solid #d3dce6;
            selection-background-color: #cfe5ff;
            selection-color: #102030;
        }
        QHeaderView::section {
            background: #edf2f7;
            border: 0;
            border-right: 1px solid #d3dce6;
            border-bottom: 1px solid #d3dce6;
            padding: 7px;
            font-weight: 700;
        }
        QLabel#audioStatus {
            color: #0b5cad;
            font-weight: 700;
        }
        QLabel#footerLabel {
            color: #7a8795;
            font-size: 8.5pt;
        }
        """

    def apply_theme(self, theme: str):
        if theme == "dark" and qdarkstyle:
            self.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        else:
            self.setStyleSheet(self._modern_light_stylesheet())
        self.config["theme"] = theme

    def _on_theme_change(self, index: int):
        theme_value = self.theme_combo.itemData(index) or "light"
        self.apply_theme(theme_value)

    def save_spectrum_png(self):
        path = os.path.expanduser("~/TetraScans")
        os.makedirs(path, exist_ok=True)
        fname = datetime.now().strftime("scan_%Y%m%d_%H%M%S.png")
        self.canvas.fig.savefig(os.path.join(path, fname))
        self.log.appendPlainText(f"Spektrum gespeichert: {fname}")

    def run_scheduled_cycle(self):
        self.start()
        QtCore.QTimer.singleShot(5000, self._run_decode_phase)

    def _run_decode_phase(self):
        self.scanner.stop()
        if self.current_frequency:
            self.start_decoding()
        QtCore.QTimer.singleShot(60000, self.stop)

    def send_telegram(self, text: str):
        token = self.token_edit.text().strip()
        chat = self.chat_edit.text().strip()
        if not token or not chat or not requests:
            return
        threading.Thread(
            target=requests.post,
            args=(f"https://api.telegram.org/bot{token}/sendMessage",),
            kwargs={"data": {"chat_id": chat, "text": text}},
            daemon=True,
        ).start()

    def _append_decoder_data(self, line: str):
        if not hasattr(self, "decoder_data_table"):
            return
        zeit = datetime.now().strftime("%H:%M:%S")
        freq_text = ""
        if self.current_frequency is not None:
            freq_text = f"{self.current_frequency/1e6:.4f} MHz"
        typ = _decoder_line_type(line)
        self.decoder_data.append({
            "zeit": zeit,
            "freq": freq_text,
            "typ": typ,
            "line": line,
        })
        row = self.decoder_data_table.rowCount()
        self.decoder_data_table.insertRow(row)
        werte = [zeit, freq_text, typ, line]
        for column, value in enumerate(werte):
            item = QtWidgets.QTableWidgetItem(value)
            if typ in ("CRC OK", "Netzinfo"):
                item.setBackground(QtGui.QColor("#c8f7c5"))
            elif typ in ("Verschlüsselung", "Status"):
                item.setBackground(QtGui.QColor("#fff4bf"))
            self.decoder_data_table.setItem(row, column, item)
        if self.decoder_data_table.rowCount() > self.decoder_data.maxlen:
            self.decoder_data_table.removeRow(0)
        self.decoder_data_table.scrollToBottom()

    def parse_network_info(self, line: str):
        info = _extract_sysinfo(line)
        if not info:
            return
        freq_text = ""
        if self.current_frequency is not None:
            freq_text = f"{self.current_frequency/1e6:.4f} MHz"
        key = info.get("dl_hz", freq_text)
        self.network_infos[key] = info
        details = (
            f"DL {info['dl_hz']/1e6:.4f} MHz, "
            f"UL {info['ul_hz']/1e6:.4f} MHz, "
            f"Service {info['service_details']}"
        )
        if info.get("cck_id"):
            details += f", CCK ID {info['cck_id']}"
        if info.get("hyperframe"):
            details += f", Hyperframe {info['hyperframe']}"
        self.log.appendPlainText(f"TETRA-Netzinfo: {details}")

    def update_cells(self, cell):
        cid = cell.get("cell")
        if not cid:
            return
        self.cells[cid] = cell
        self.cell_table.setRowCount(len(self.cells))
        for row, info in enumerate(self.cells.values()):
            self.cell_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(info.get("cell", ""))))
            self.cell_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(info.get("lac", ""))))
            self.cell_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(info.get("mcc", ""))))
            self.cell_table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(info.get("mnc", ""))))
            self.cell_table.setItem(row, 4, QtWidgets.QTableWidgetItem(str(info.get("freq", ""))))

    def update_stats(self):
        self.stats_ax.clear()
        types = list(self.packet_counts.keys())
        vals = [self.packet_counts[t] for t in types]
        self.stats_ax.bar(types, vals)
        self.stats_canvas.draw()

    def export_cells_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "CSV speichern",
            "cells.csv",
            "CSV-Dateien (*.csv)",
        )
        if not path:
            return
        with open(path, "w") as fh:
            fh.write("Zelle,LAC,MCC,MNC,Frequenz\n")
            for c in self.cells.values():
                fh.write(
                    f"{c.get('cell','')},{c.get('lac','')},"
                    f"{c.get('mcc','')},{c.get('mnc','')},{c.get('freq','')}\n"
                )

    def update_scheduler(self):
        enabled = self.scheduler_enable_cb.isChecked()
        interval = self.scheduler_interval_spin.value()
        self.config["scheduler_enabled"] = enabled
        self.config["scheduler_interval"] = interval
        if enabled:
            self.scheduler_timer.start(interval * 60 * 1000)
        else:
            self.scheduler_timer.stop()

    def parse_cell_info(self, line: str):
        m = re.search(r"Cell\s*ID[:=]\s*(\w+).*LAC[:=]\s*(\w+).*MCC[:=]\s*(\d+).*MNC[:=]\s*(\d+)", line, re.I)
        if not m:
            return
        cell = {
            "cell": m.group(1),
            "lac": m.group(2),
            "mcc": m.group(3),
            "mnc": m.group(4),
            "freq": f"{self.current_frequency/1e6:.3f}"
        }
        self.update_cells(cell)

    def parse_packet_type(self, line: str):
        types = ["SDS", "MM", "CM"]
        for t in types:
            if t in line:
                self.packet_counts[t] = self.packet_counts.get(t, 0) + 1
                self.update_stats()
                self.send_telegram(
                    f"TETRA-Aktivit\u00e4t auf {self.current_frequency/1e6:.4f} MHz: {t} empfangen"
                )
                break

    def parse_talkgroups(self, line: str):
        ids = self._extract_talkgroup_ids(line)
        if not ids:
            return
        now = datetime.now()
        for tg_id in ids:
            info = self.talkgroups.get(tg_id, {"count": 0, "last_seen": now})
            info["count"] = info.get("count", 0) + 1
            info["last_seen"] = now
            if self.current_frequency is not None:
                info["freq"] = f"{self.current_frequency/1e6:.4f} MHz"
            self.talkgroups[tg_id] = info
        self._update_talkgroups_table()
        self._refresh_dashboard_status()

    def _extract_talkgroup_ids(self, line: str):
        return extract_talkgroup_ids(line)

    def _update_talkgroups_table(self):
        if not hasattr(self, "talkgroup_table"):
            return
        sortiert = sorted(
            self.talkgroups.items(),
            key=lambda item: item[1].get("last_seen") or datetime.min,
            reverse=True,
        )
        self.talkgroup_table.blockSignals(True)
        self.talkgroup_table.setRowCount(len(sortiert))
        for row, (tg_id, info) in enumerate(sortiert):
            count = info.get("count", 0)
            last_seen = info.get("last_seen")
            last_text = last_seen.strftime("%Y-%m-%d %H:%M:%S") if last_seen else ""
            freq_text = str(info.get("freq", ""))
            auswahl_item = QtWidgets.QTableWidgetItem("")
            auswahl_item.setFlags(
                auswahl_item.flags() | QtCore.Qt.ItemIsUserCheckable
            )
            auswahl_item.setCheckState(
                QtCore.Qt.Checked
                if str(tg_id) in self.selected_talkgroups
                else QtCore.Qt.Unchecked
            )
            self.talkgroup_table.setItem(row, 0, auswahl_item)
            self.talkgroup_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(tg_id)))
            self.talkgroup_table.setItem(row, 2, QtWidgets.QTableWidgetItem(freq_text))
            self.talkgroup_table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(count)))
            self.talkgroup_table.setItem(row, 4, QtWidgets.QTableWidgetItem(last_text))
        self.talkgroup_table.blockSignals(False)

    def _handle_talkgroup_selection_change(self, item: QtWidgets.QTableWidgetItem):
        if item.column() != 0:
            return
        tg_item = self.talkgroup_table.item(item.row(), 1)
        if not tg_item:
            return
        tg_id = str(tg_item.text()).strip()
        if not tg_id:
            return
        if item.checkState() == QtCore.Qt.Checked:
            self.selected_talkgroups.add(tg_id)
        else:
            self.selected_talkgroups.discard(tg_id)
        self._persist_selected_talkgroups_to_config()
        self._refresh_dashboard_status()

    def _set_all_talkgroup_selection(self, selected: bool):
        ids = {str(tg_id) for tg_id in self.talkgroups.keys()}
        if selected:
            self.selected_talkgroups = ids
        else:
            self.selected_talkgroups = set()
        self._persist_selected_talkgroups_to_config()
        self._update_talkgroups_table()
        self._refresh_dashboard_status()

    def _on_talkgroup_filter_change(self, enabled: bool):
        self.config["talkgroup_filter_enabled"] = bool(enabled)
        status = "aktiv" if enabled else "aus"
        self.log.appendPlainText(f"Sprechgruppen-Filter {status}.")
        self._refresh_dashboard_status()

    def _line_matches_selected_talkgroup(self, line: str) -> bool:
        filter_enabled = (
            hasattr(self, "talkgroup_filter_cb")
            and self.talkgroup_filter_cb.isChecked()
        )
        if not filter_enabled or not self.selected_talkgroups:
            return True
        ids = self._extract_talkgroup_ids(line)
        if not ids:
            return True
        return any(tg_id in self.selected_talkgroups for tg_id in ids)

    def _load_talkgroups_from_config(self):
        gespeicherte = self.config.get("talkgroups", {})
        if not isinstance(gespeicherte, dict):
            return
        for tg_id, info in gespeicherte.items():
            if not isinstance(info, dict):
                continue
            last_seen = info.get("last_seen")
            parsed_last = None
            if isinstance(last_seen, str):
                try:
                    parsed_last = datetime.fromisoformat(last_seen)
                except ValueError:
                    parsed_last = None
            self.talkgroups[str(tg_id)] = {
                "count": int(info.get("count", 0)),
                "last_seen": parsed_last,
                "freq": str(info.get("freq", "")),
            }

    def _load_selected_talkgroups_from_config(self):
        gespeicherte = self.config.get("selected_talkgroups", [])
        if isinstance(gespeicherte, list):
            self.selected_talkgroups = {str(tg_id) for tg_id in gespeicherte}
        else:
            self.selected_talkgroups = set()

    def _persist_talkgroups_to_config(self):
        gespeicherte = {}
        for tg_id, info in self.talkgroups.items():
            last_seen = info.get("last_seen")
            gespeicherte[str(tg_id)] = {
                "count": int(info.get("count", 0)),
                "last_seen": last_seen.isoformat() if last_seen else "",
                "freq": str(info.get("freq", "")),
            }
        self.config["talkgroups"] = gespeicherte

    def _persist_selected_talkgroups_to_config(self):
        self.config["selected_talkgroups"] = sorted(self.selected_talkgroups)


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(add_help=False)
    cli_parser.add_argument("--cli", action="store_true")
    cli_args, rest_args = cli_parser.parse_known_args()
    if cli_args.cli:
        sys.argv = [sys.argv[0]] + rest_args
        _starte_cli_modus("CLI-Modus wurde per --cli angefordert.")
        raise SystemExit(0)

    if not _qt_xcb_verfuegbar():
        _starte_cli_modus(
            "Qt-Plugin 'xcb' nicht gefunden. Bitte installiere die fehlenden "
            "System-Pakete für X11/Qt-xcb (z. B. libxcb, libxkbcommon-x11) oder "
            "starte das Programm in einer Umgebung mit grafischer Oberfläche. "
            "Alternativ kannst du 'QT_QPA_PLATFORM=offscreen' setzen, wenn eine "
            "headless Ausführung gewünscht ist."
        )
        raise SystemExit(0)

    try:
        app = QtWidgets.QApplication(sys.argv)
    except Exception as exc:
        _starte_cli_modus(
            "Qt konnte nicht gestartet werden. Bitte prüfe, ob die X11/Qt-xcb "
            "System-Pakete installiert sind oder ob du dich in einer headless "
            "Umgebung befindest. Fehlerdetails: "
            f"{exc}"
        )
        raise SystemExit(0)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

# © 2026 Erik Schauer, do1ffe@darc.de
