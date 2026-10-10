"""Różnice między systemami w jednym miejscu (bez zewnętrznych bibliotek – działa, zanim są biblioteki).
Nowe w wersji 2.2.0.

Windows: Wykłady.exe + _internal, Python i biblioteki w _internal/runtime, ustawienia w %APPDATA%/WykladyAI.
macOS:   Wykłady.app/Contents/Resources/_internal, Python i biblioteki w ~/Library/Application Support/WykladyAI/runtime
         (paczka aplikacji zostaje mała i da się ją podmienić przy aktualizacji), ustawienia w tym samym folderze.

Moduły tylko na Windows (WASAPI, pycaw, proc-tap, Windows OCR, CUDA, skróty .lnk, rejestr) importuj dopiero po
sprawdzeniu IS_WIN / LIVE_RECORDING."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
APP_ID = "WykladyAI"
MAC_LIVE_MIN = (14, 4)          # Core Audio process taps (dźwięk aplikacji) i SCScreenshotManager


def mac_version() -> tuple[int, ...]:
    """(14, 4, 1) na macOS, () gdzie indziej."""
    if not IS_MAC:
        return ()
    import platform
    try:
        return tuple(int(x) for x in platform.mac_ver()[0].split(".") if x.isdigit())
    except ValueError:
        return ()


# nagrywanie na żywo (dźwięk z aplikacji / mikrofonu, zrzuty ekranu): Windows i macOS 14.4+;
# na starszym macOS wykład dodaje się z plików
LIVE_RECORDING = IS_WIN or (IS_MAC and mac_version() >= MAC_LIVE_MIN)

INTERNAL = Path(__file__).resolve().parents[1]          # folder _internal


def data_dir() -> Path:
    """Ustawienia, log (i na Macu runtime): %APPDATA%/WykladyAI albo ~/Library/Application Support/WykladyAI."""
    if IS_MAC:
        p = Path.home() / "Library" / "Application Support" / APP_ID
    else:
        base = os.environ.get("APPDATA")
        p = Path(base) / APP_ID if base else Path.home() / f".{APP_ID.lower()}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def runtime_dir() -> Path:
    """Wbudowany Python z bibliotekami (tworzony przy pierwszym uruchomieniu)."""
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_ID / "runtime"
    return INTERNAL / "runtime"


def app_bundle() -> Optional[Path]:
    """Wykłady.app, gdy aplikacja działa z paczki na Macu (…/Wykłady.app/Contents/Resources/_internal)."""
    if not IS_MAC:
        return None
    p = INTERNAL.parents[2] if len(INTERNAL.parents) > 2 else None
    return p if p is not None and p.suffix == ".app" and (p / "Contents" / "Info.plist").exists() else None


def requirements_files() -> tuple[str, ...]:
    """Pliki z listą bibliotek dla tego systemu (zmiana pliku → ekran doinstalowania przy starcie)."""
    if IS_MAC:
        return ("requirements-mac.txt",)
    return ("requirements.txt", "requirements-ocr.txt")


def mac_ssl_certs() -> None:
    """Python z python-build-standalone nie zna certyfikatów macOS – urllib bierze je z certifi (jest z requests).
    Wywołać przed pobieraniem; bez certifi (pierwsze sekundy instalacji) nic nie robi."""
    if not IS_MAC or os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except Exception:  # noqa: BLE001
        pass


def system_name() -> str:
    return "macOS" if IS_MAC else ("Windows" if IS_WIN else "Linux")
