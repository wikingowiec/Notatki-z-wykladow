"""Nagrywanie dźwięku: wybór źródła, konwersja do 16 kHz mono, zapis FLAC i przekazanie do transkrypcji.

Źródła:
  * process  – dźwięk tylko jednej aplikacji (Windows 10 2004+/11) – proc-tap albo własna implementacja WASAPI
  * system   – cały dźwięk systemowy (WASAPI loopback domyślnego wyjścia)
  * mic      – mikrofon (np. wykład stacjonarny)
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)

TARGET_SR = 16000


# ---------------------------------------------------------------------------
# Opis źródeł
# ---------------------------------------------------------------------------
@dataclass
class AudioSourceInfo:
    kind: str            # "process" / "system" / "mic"
    label: str
    pid: int = 0
    device_index: int = -1
    exe: str = ""
    active: bool = False


def _root_pid(pid: int) -> int:
    """Dla aplikacji wieloprocesowych (Chrome, Edge, Teams) zwraca główny proces o tej samej nazwie."""
    try:
        import psutil
        p = psutil.Process(pid)
        name = p.name().lower()
        while True:
            parent = p.parent()
            if parent is None:
                return p.pid
            pname = parent.name().lower()
            # WebView2 (np. nowy Teams) – przechodzimy do aplikacji-gospodarza
            if pname == name or name == "msedgewebview2.exe" and pname not in ("explorer.exe", "svchost.exe", "services.exe"):
                p, name = parent, pname
                continue
            return p.pid
    except Exception:
        return pid


def _pretty(exe: str) -> str:
    names = {
        "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge", "firefox.exe": "Firefox",
        "opera.exe": "Opera", "brave.exe": "Brave", "ms-teams.exe": "Microsoft Teams", "teams.exe": "Microsoft Teams",
        "zoom.exe": "Zoom", "discord.exe": "Discord", "vlc.exe": "VLC", "spotify.exe": "Spotify",
        "webex.exe": "Webex", "ciscocollabhost.exe": "Webex", "obs64.exe": "OBS", "slack.exe": "Slack",
        "vivaldi.exe": "Vivaldi", "mpc-hc64.exe": "MPC-HC", "potplayermini64.exe": "PotPlayer",
    }
    return names.get(exe.lower(), exe[:-4] if exe.lower().endswith(".exe") else exe)


def list_audio_sources() -> list[AudioSourceInfo]:
    """Zwraca listę: aplikacje z dźwiękiem, inne aplikacje z oknami, dźwięk systemowy, mikrofony."""
    out: list[AudioSourceInfo] = []
    seen_roots: set[int] = set()
    seen_exes: set[str] = set()

    # 1) aplikacje, które mają sesję audio (pycaw)
    try:
        from pycaw.pycaw import AudioUtilities
        sessions = AudioUtilities.GetAllSessions()
        items = []
        for s in sessions:
            try:
                if not s.Process:
                    continue
                root = _root_pid(s.Process.pid)
                try:
                    import psutil
                    exe = psutil.Process(root).name()
                except Exception:
                    exe = s.Process.name()
                try:
                    active = (s.State == 1)
                except Exception:
                    active = False
                items.append((exe, root, active))
            except Exception:
                continue
        # aktywne na górze
        items.sort(key=lambda x: (not x[2], _pretty(x[0]).lower()))
        for exe, root, active in items:
            if root in seen_roots:
                continue
            seen_roots.add(root)
            seen_exes.add(exe.lower())
            label = f"🔊 {_pretty(exe)}" + ("  (gra teraz)" if active else "") + f"  [PID {root}]"
            out.append(AudioSourceInfo("process", label, pid=root, exe=exe, active=active))
    except Exception:
        log.exception("pycaw")

    # 2) pozostałe aplikacje z widocznymi oknami (mogą zacząć grać później)
    try:
        from .screen_capture import list_windows
        import psutil
        for w in list_windows():
            try:
                exe = psutil.Process(w.pid).name()
            except Exception:
                continue
            if exe.lower() in seen_exes or exe.lower() in ("explorer.exe", "textinputhost.exe", "python.exe", "pythonw.exe"):
                continue
            root = _root_pid(w.pid)
            if root in seen_roots:
                continue
            seen_roots.add(root)
            seen_exes.add(exe.lower())
            out.append(AudioSourceInfo("process", f"{_pretty(exe)}  [PID {root}]", pid=root, exe=exe))
    except Exception:
        log.exception("okna")

    # 3) cały dźwięk systemowy + mikrofony
    out.append(AudioSourceInfo("system", "🖥 Cały dźwięk systemowy (wszystko co słychać)"))
    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_in = wasapi.get("defaultInputDevice", -1)
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d.get("hostApi") != wasapi["index"] or d.get("isLoopbackDevice") or d.get("maxInputChannels", 0) < 1:
                    continue
                star = " (domyślny)" if i == default_in else ""
                out.append(AudioSourceInfo("mic", f"🎤 Mikrofon: {d['name']}{star}", device_index=i))
        finally:
            p.terminate()
    except Exception:
        log.exception("mikrofony")
    return out


# ---------------------------------------------------------------------------
# Backendy przechwytywania – każdy wywołuje cb(np.ndarray (n, ch) float32, sample_rate)
# ---------------------------------------------------------------------------
class _ProcTapSource:
    def __init__(self, pid: int, cb):
        from proctap import ProcessAudioCapture
        self.cb = cb
        self.cap = ProcessAudioCapture(pid, on_data=self._on)
        self.name = "proc-tap"

    def _on(self, pcm: bytes, _frames: int):
        arr = np.frombuffer(pcm, dtype=np.float32)
        if arr.size % 2:
            arr = arr[:-1]
        self.cb(arr.reshape(-1, 2), 48000)

    def start(self):
        self.cap.start()

    def stop(self):
        try:
            self.cap.close()
        except Exception:
            log.exception("proctap close")


class _NativeSource:
    def __init__(self, pid: int, cb):
        from .wasapi_process_loopback import NativeProcessLoopback
        self.cb = cb
        self.cap = NativeProcessLoopback(pid, self._on)
        self.name = "WASAPI (natywny)"

    def _on(self, arr: np.ndarray):
        self.cb(arr, self.cap.sample_rate)

    def start(self):
        self.cap.start()

    def stop(self):
        self.cap.stop()


class _PyAudioSource:
    """Loopback całego systemu albo mikrofon przez PyAudioWPatch (WASAPI)."""

    def __init__(self, cb, device_index: int = -1, loopback: bool = True):
        import pyaudiowpatch as pyaudio
        self.pyaudio = pyaudio
        self.cb = cb
        self.p = pyaudio.PyAudio()
        if loopback:
            dev = self.p.get_default_wasapi_loopback()
        elif device_index >= 0:
            dev = self.p.get_device_info_by_index(device_index)
        else:
            dev = self.p.get_default_input_device_info()
        self.dev = dev
        self.channels = max(1, int(dev["maxInputChannels"]))
        self.rate = int(dev["defaultSampleRate"])
        self.name = f"WASAPI: {dev['name']}"
        self.stream = None

    def _callback(self, in_data, frame_count, time_info, status):
        arr = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
        self.cb(arr.reshape(-1, self.channels), self.rate)
        return (None, self.pyaudio.paContinue)

    def start(self):
        self.stream = self.p.open(format=self.pyaudio.paInt16, channels=self.channels, rate=self.rate,
                                  input=True, input_device_index=self.dev["index"],
                                  frames_per_buffer=1024, stream_callback=self._callback)
        self.stream.start_stream()

    def stop(self):
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
        finally:
            self.p.terminate()


def open_source(info: AudioSourceInfo, cb, backend: str = "auto"):
    if info.kind == "process":
        errors = []
        order = {"auto": ["proctap", "native"], "proctap": ["proctap", "native"], "native": ["native", "proctap"]}.get(backend, ["proctap", "native"])
        for name in order:
            try:
                src = _ProcTapSource(info.pid, cb) if name == "proctap" else _NativeSource(info.pid, cb)
                src.start()
                return src
            except Exception as e:  # noqa: BLE001
                log.exception("backend %s", name)
                errors.append(f"{name}: {e}")
        raise RuntimeError("Nie udało się przechwycić dźwięku aplikacji.\n" + "\n".join(errors) +
                           "\n\nSpróbuj opcji „Cały dźwięk systemowy”.")
    src = _PyAudioSource(cb, loopback=(info.kind == "system"), device_index=info.device_index)
    src.start()
    return src


# ---------------------------------------------------------------------------
# Resampling strumieniowy
# ---------------------------------------------------------------------------
class _Resampler:
    def __init__(self, in_rate: int):
        self.in_rate = in_rate
        self._soxr = None
        if in_rate != TARGET_SR:
            try:
                import soxr
                self._soxr = soxr.ResampleStream(in_rate, TARGET_SR, 1, dtype="float32", quality="HQ")
            except Exception:
                self._soxr = None

    def __call__(self, mono: np.ndarray, last: bool = False) -> np.ndarray:
        if self.in_rate == TARGET_SR:
            return mono
        if self._soxr is not None:
            return self._soxr.resample_chunk(mono, last=last)
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(self.in_rate, TARGET_SR)
        return resample_poly(mono, TARGET_SR // g, self.in_rate // g).astype(np.float32)


# ---------------------------------------------------------------------------
# Rejestrator
# ---------------------------------------------------------------------------
class AudioRecorder:
    """Zbiera dźwięk ze źródła, zapisuje audio.flac i przekazuje 16 kHz mono do słuchaczy.

    Uzupełnia ciszę zerami, gdy źródło nic nie wysyła (WASAPI milczy, gdy aplikacja nie gra),
    dzięki czemu oś czasu nagrania zgadza się z zegarem i ze slajdami.
    """

    def __init__(self, info: AudioSourceInfo, out_path: Path, backend: str = "auto"):
        self.info = info
        self.out_path = Path(out_path)
        self.backend = backend
        self.listeners: list[Callable[[np.ndarray], None]] = []
        self._q: "queue.Queue[tuple[np.ndarray, int]]" = queue.Queue(maxsize=2000)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._src = None
        self._resampler: Optional[_Resampler] = None
        self.samples_written = 0
        self.level_db = -90.0
        self.t0 = 0.0
        self.source_name = ""
        self.error: Optional[str] = None

    def _on_audio(self, arr: np.ndarray, rate: int):
        try:
            self._q.put_nowait((arr.copy(), rate))
        except queue.Full:
            pass

    def start(self, t0: Optional[float] = None):
        import soundfile as sf
        if self.out_path.suffix.lower() == ".opus":     # Opus: ~6× mniej miejsca niż FLAC, ta sama jakość mowy
            self._sf = sf.SoundFile(str(self.out_path), mode="w", samplerate=TARGET_SR, channels=1,
                                    format="OGG", subtype="OPUS")
        else:
            self._sf = sf.SoundFile(str(self.out_path), mode="w", samplerate=TARGET_SR, channels=1,
                                    format="FLAC", subtype="PCM_16")
        self.t0 = t0 or time.monotonic()
        self._src = open_source(self.info, self._on_audio, self.backend)
        self.source_name = getattr(self._src, "name", "")
        self._thread = threading.Thread(target=self._run, name="AudioRecorder", daemon=True)
        self._thread.start()

    def elapsed(self) -> float:
        return self.samples_written / TARGET_SR

    def _emit(self, x: np.ndarray):
        if x.size == 0:
            return
        x = np.clip(x, -1.0, 1.0).astype(np.float32)
        self._sf.write(x)
        self.samples_written += len(x)
        for fn in self.listeners:
            try:
                fn(x)
            except Exception:
                log.exception("listener")

    def _run(self):
        try:
            while not self._stop.is_set():
                try:
                    arr, rate = self._q.get(timeout=0.1)
                except queue.Empty:
                    arr = None
                if arr is not None:
                    if self._resampler is None or self._resampler.in_rate != rate:
                        self._resampler = _Resampler(rate)
                    mono = arr.mean(axis=1) if arr.ndim == 2 else arr
                    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                    self.level_db = 20 * np.log10(max(rms, 1e-5))
                    self._emit(self._resampler(mono.astype(np.float32)))
                # uzupełnianie ciszy
                expected = (time.monotonic() - self.t0) * TARGET_SR
                lag = expected - self.samples_written
                if lag > 0.5 * TARGET_SR:
                    self._emit(np.zeros(int(lag - 0.1 * TARGET_SR), dtype=np.float32))
                    self.level_db = -90.0
        except Exception as e:  # noqa: BLE001
            log.exception("AudioRecorder")
            self.error = str(e)

    def stop(self):
        try:
            if self._src:
                self._src.stop()
        except Exception:
            log.exception("stop source")
        self._stop.set()
        if self._thread:
            self._thread.join(5)
        # dopisz resztę z kolejki
        try:
            while True:
                arr, rate = self._q.get_nowait()
                if self._resampler is None or self._resampler.in_rate != rate:
                    self._resampler = _Resampler(rate)
                mono = arr.mean(axis=1) if arr.ndim == 2 else arr
                self._emit(self._resampler(mono.astype(np.float32)))
        except queue.Empty:
            pass
        try:
            self._sf.close()
        except Exception:
            pass
