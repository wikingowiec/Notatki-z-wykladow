"""Czy trzeba coś doinstalować? (bez ciężkich importów – działa, zanim są biblioteki)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]          # folder _internal
RUNTIME = BASE / "runtime"
PYTHON_DIR = RUNTIME / "python"
MARKER = RUNTIME / "setup.json"
REQ_FILES = ("requirements.txt", "requirements-ocr.txt")


def embedded() -> bool:
    """Aplikacja działa na własnym Pythonie z _internal/runtime (a nie np. z .venv programisty)."""
    try:
        return Path(sys.executable).resolve().is_relative_to(RUNTIME.resolve())
    except Exception:  # noqa: BLE001
        return False


def req_hash() -> str:
    h = hashlib.sha1()
    for f in REQ_FILES:
        try:
            h.update((BASE / f).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:16]


def load_marker() -> dict:
    try:
        return json.loads(MARKER.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def setup_needed() -> bool:
    if not embedded():
        return False
    m = load_marker()
    return not m.get("complete") or m.get("req_hash") != req_hash()


def save_marker(**extra) -> None:
    m = load_marker()
    m.update(extra)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def python_console() -> str:
    """python.exe obok pythonw.exe (pip z przechwyconym wyjściem)."""
    exe = Path(sys.executable)
    cand = exe.with_name("python.exe")
    return str(cand if cand.exists() else exe)


def launcher_exe() -> Path:
    return BASE.parent / "Wykłady.exe"
