"""Zgody macOS potrzebne do nagrywania na żywo: mikrofon, dźwięk aplikacji / systemu, nagrywanie ekranu.
Nowe w wersji 2.2.0.

status() nigdy nie wywołuje prośby systemu – tylko sprawdza. request() pokazuje prośbę macOS (gdy jeszcze nie
pytano), open_settings() otwiera właściwe miejsce w Ustawieniach systemowych.

Dźwięk systemu (process taps) nie ma publicznej funkcji do sprawdzenia zgody – używamy TCCAccessPreflight
(tak samo robi przykład AudioCap); gdy jej zabraknie, stan jest „nieznany” i prośba pojawi się przy nagrywaniu."""
from __future__ import annotations

import ctypes
import logging
import subprocess
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

MIC, AUDIO, SCREEN = "mic", "audio", "screen"
GRANTED, DENIED, UNKNOWN = "granted", "denied", "unknown"      # UNKNOWN = jeszcze nie pytano (albo nie wiadomo)

_PANE = "x-apple.systempreferences:com.apple.preference.security?"
SETTINGS_URL = {
    MIC: _PANE + "Privacy_Microphone",
    AUDIO: _PANE + "Privacy_ScreenCapture",     # „Nagrywanie ekranu i dźwięku systemu” › „Tylko dźwięk systemu”
    SCREEN: _PANE + "Privacy_ScreenCapture",
}

TITLE = {
    MIC: "Dostęp do mikrofonu",
    AUDIO: "Nagrywanie dźwięku aplikacji",
    SCREEN: "Nagrywanie ekranu (slajdy)",
}
WHY = {
    MIC: "Wykłady nagrywają mikrofon tylko w trakcie nagrywania, a dźwięk zostaje na tym Macu.",
    AUDIO: "Żeby nagrać wykład z Teams, Zooma albo przeglądarki, macOS musi pozwolić Wykładom słuchać dźwięku "
           "wybranej aplikacji. Nic nie wychodzi poza tego Maca.",
    SCREEN: "Slajdy są łapane ze zrzutów wybranego ekranu albo okna. macOS wymaga na to zgody na nagrywanie ekranu.",
}
WHERE = {
    MIC: "Ustawienia systemowe › Prywatność i ochrona › Mikrofon › włącz „Wykłady”.",
    AUDIO: "Ustawienia systemowe › Prywatność i ochrona › Nagrywanie ekranu i dźwięku systemu › w części "
           "„Tylko nagrywanie dźwięku systemu” włącz „Wykłady”.",
    SCREEN: "Ustawienia systemowe › Prywatność i ochrona › Nagrywanie ekranu i dźwięku systemu › włącz „Wykłady”, "
            "potem uruchom Wykłady ponownie.",
}

_cg = None
_tcc = None
_cf = None


def _coregraphics():
    global _cg
    if _cg is None:
        _cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        _cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        _cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
    return _cg


_cfstrings: dict[str, int] = {}


def _cfstring(text: str):
    """CFStringRef dla nazwy usługi (tworzony raz, żyje do końca programu)."""
    global _cf
    if _cf is None:
        _cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        _cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        _cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    if text not in _cfstrings:
        _cfstrings[text] = _cf.CFStringCreateWithCString(None, text.encode("utf-8"), 0x08000100)
    return _cfstrings[text]


def _tcc_preflight(service: str) -> Optional[int]:
    """0 = zgoda, 1 = odmowa, inne = nie pytano. None, gdy funkcji nie ma."""
    global _tcc
    if _tcc is None:
        try:
            lib = ctypes.CDLL("/System/Library/PrivateFrameworks/TCC.framework/Versions/A/TCC")
            fn = lib.TCCAccessPreflight
            fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_long
            _tcc = fn
        except (OSError, AttributeError):
            _tcc = False
    if not _tcc:
        return None
    try:
        return int(_tcc(_cfstring(service), None))
    except Exception:  # noqa: BLE001
        return None


def _mic_status() -> str:
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        st = int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio))
    except Exception:  # noqa: BLE001
        r = _tcc_preflight("kTCCServiceMicrophone")
        return UNKNOWN if r is None else {0: GRANTED, 1: DENIED}.get(r, UNKNOWN)
    return {3: GRANTED, 1: DENIED, 2: DENIED}.get(st, UNKNOWN)


def status(kind: str) -> str:
    try:
        if kind == MIC:
            return _mic_status()
        if kind == SCREEN:
            # bez zgody nie da się odróżnić „odmówiono” od „nie pytano” – oba traktujemy jako brak zgody
            return GRANTED if _coregraphics().CGPreflightScreenCaptureAccess() else DENIED
        if kind == AUDIO:
            r = _tcc_preflight("kTCCServiceAudioCapture")
            return UNKNOWN if r is None else {0: GRANTED, 1: DENIED}.get(r, UNKNOWN)
    except Exception:  # noqa: BLE001
        log.exception("zgoda %s", kind)
    return UNKNOWN


def request(kind: str, done: Optional[Callable[[], None]] = None) -> None:
    """Pokazuje prośbę macOS o zgodę (gdy już odmówiono – system nie zapyta drugi raz, zostają Ustawienia).
    done() może przyjść z innego wątku – w UI przekazuj przez sygnał albo sprawdzaj status timerem."""
    def finish(*_a):
        if done:
            try:
                done()
            except Exception:  # noqa: BLE001
                log.exception("zgoda: done")

    if kind == MIC:
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, finish)
            return
        except Exception:  # noqa: BLE001
            log.exception("prośba o mikrofon")
    elif kind == SCREEN:
        try:
            _coregraphics().CGRequestScreenCaptureAccess()
        except Exception:  # noqa: BLE001
            log.exception("prośba o nagrywanie ekranu")
    elif kind == AUDIO:
        def work():           # prośba pojawia się przy pierwszym włączeniu tapu
            try:
                from .mac_audio import probe_system_audio
                probe_system_audio()
            except Exception:  # noqa: BLE001
                log.exception("prośba o dźwięk systemu")
            finish()
        threading.Thread(target=work, name="ProsbaDzwiek", daemon=True).start()
        return
    finish()


def open_settings(kind: str) -> None:
    try:
        subprocess.Popen(["/usr/bin/open", SETTINGS_URL.get(kind, _PANE)])
    except OSError:
        log.exception("Ustawienia systemowe")


def needed(mode: str, audio_kind: Optional[str]) -> list[str]:
    """Zgody potrzebne do rodzaju notatki: av / audio / slides i wybranego źródła dźwięku."""
    out = []
    if mode in ("av", "audio") and audio_kind:
        out.append(MIC if audio_kind == "mic" else AUDIO)
    if mode in ("av", "slides"):
        out.append(SCREEN)
    return out
