"""Nagrywanie dźwięku: wybór źródła, konwersja do 16 kHz mono, zapis FLAC i przekazanie do transkrypcji.

Źródła:
  * process  – dźwięk tylko jednej aplikacji (Windows 10 2004+/11) – proc-tap albo własna implementacja WASAPI
  * system   – cały dźwięk systemowy (WASAPI loopback domyślnego wyjścia)
  * mic      – mikrofon (np. wykład stacjonarny)

Na macOS listę źródeł, mierniki i przechwytywanie robi mac_audio.py (Core Audio process taps, zapas
ScreenCaptureKit) – AudioRecorder, resampling i zapis pliku są wspólne.
"""
from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)

TARGET_SR = 16000
IS_MAC = sys.platform == "darwin"


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
    active: bool = False     # właśnie słychać dźwięk (miernik Windows > 0)
    detail: str = ""         # druga linijka na liście: „gra na: Słuchawki …”, „domyślny” …
    hidden: bool = False     # pod „Pokaż wszystkie” (uśpione aplikacje, okna bez dźwięku, wirtualne mikrofony)


PLAYING = 0.002              # szczyt miernika (0–1), od którego uznajemy, że źródło gra

# procesy systemowe – nie ma sensu ich nagrywać, nie pokazujemy ich nawet pod „Pokaż wszystkie”
_SYSTEM_EXES = {
    "audiodg.exe", "svchost.exe", "explorer.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "lsass.exe", "services.exe",
    "sihost.exe", "ctfmon.exe", "runtimebroker.exe", "taskhostw.exe", "textinputhost.exe", "searchhost.exe",
    "searchapp.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "applicationframehost.exe",
    "systemsettings.exe", "lockapp.exe", "smartscreen.exe", "securityhealthsystray.exe", "rtkauduservice64.exe",
    "nvcontainer.exe", "nvidia share.exe", "widgets.exe", "phoneexperiencehost.exe", "gamebar.exe",
    "wykłady.exe",
}
# wirtualne urządzenia (Steam, kable audio) – schowane pod „Pokaż wszystkie”
_VIRTUAL_DEVICES = ("steam streaming", "vb-audio", "cable output", "voicemeeter", "virtual")


def source_key(info: AudioSourceInfo) -> str:
    """Klucz źródła w słowniku poziomów (LevelMonitor.levels)."""
    if info.kind == "process":
        return f"process:{info.pid}"
    if info.kind == "mic":
        return f"mic:{info.device_index}"
    return "system"


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


def _exe(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return ""


def _pretty(exe: str) -> str:
    names = {
        "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge", "firefox.exe": "Firefox",
        "opera.exe": "Opera", "brave.exe": "Brave", "ms-teams.exe": "Microsoft Teams", "teams.exe": "Microsoft Teams",
        "zoom.exe": "Zoom", "discord.exe": "Discord", "vlc.exe": "VLC", "spotify.exe": "Spotify",
        "webex.exe": "Webex", "ciscocollabhost.exe": "Webex", "obs64.exe": "OBS", "slack.exe": "Slack",
        "vivaldi.exe": "Vivaldi", "mpc-hc64.exe": "MPC-HC", "potplayermini64.exe": "PotPlayer",
    }
    return names.get(exe.lower(), exe[:-4] if exe.lower().endswith(".exe") else exe)


def _clean_device(name: str) -> str:
    """„Mikrofon (9 — Arctis Nova Pro Wireless)” → „Arctis Nova Pro Wireless”."""
    import re
    m = re.match(r"^[^()]*\((.+)\)\s*$", name or "")
    inner = m.group(1) if m else (name or "")
    return re.sub(r"^\d+\s*[—–-]\s*", "", inner).strip() or name


def _peak(meter) -> float:
    try:
        return float(meter.GetPeakValue())
    except Exception:
        return 0.0


def _device_enumerator():
    import comtypes
    from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
    from pycaw.constants import CLSID_MMDeviceEnumerator
    return comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)


def _render_sessions(names: bool = True) -> list[tuple[int, str, object]]:
    """Sesje audio aplikacji ze WSZYSTKICH aktywnych wyjść: [(pid, nazwa wyjścia, miernik)].

    pycaw.GetAllSessions patrzy tylko na domyślne wyjście – aplikacja grająca np. na monitor albo
    na drugie słuchawki by zniknęła. Pomija sesję „Dźwięki systemowe”. Wymaga CoInitialize w wątku."""
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation, IAudioSessionControl2, IAudioSessionManager2
    out = []
    coll = _device_enumerator().EnumAudioEndpoints(0, 1)        # wyjścia, tylko aktywne
    for i in range(coll.GetCount()):
        try:
            dev = coll.Item(i)
            name = (AudioUtilities.CreateDevice(dev).FriendlyName or "") if names else ""
            mgr = dev.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None).QueryInterface(IAudioSessionManager2)
            se = mgr.GetSessionEnumerator()
            for j in range(se.GetCount()):
                c = se.GetSession(j).QueryInterface(IAudioSessionControl2)
                pid = c.GetProcessId()
                if not pid or c.IsSystemSoundsSession() == 0:    # 0 (S_OK) = „Dźwięki systemowe”
                    continue
                out.append((pid, name, c.QueryInterface(IAudioMeterInformation)))
        except Exception:
            log.exception("sesje audio wyjścia %d", i)
    return out


def _default_output() -> tuple[str, object]:
    """(nazwa, miernik) domyślnego wyjścia – poziom „całego dźwięku systemowego” bez nagrywania."""
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    dev = _device_enumerator().GetDefaultAudioEndpoint(0, 1)    # eRender, eMultimedia
    meter = dev.Activate(IAudioMeterInformation._iid_, comtypes.CLSCTX_ALL, None).QueryInterface(IAudioMeterInformation)
    try:
        name = AudioUtilities.CreateDevice(dev).FriendlyName or ""
    except Exception:
        name = ""
    return name, meter


def list_audio_sources() -> list[AudioSourceInfo]:
    """Najpierw aplikacje, które właśnie grają, potem urządzenia (dźwięk systemu, mikrofony).
    Reszta (uśpione aplikacje, okna bez dźwięku, wirtualne mikrofony) ma hidden=True. Wymaga CoInitialize w wątku."""
    if IS_MAC:
        from .mac_audio import list_audio_sources as mac_sources
        return mac_sources()
    own = os.getpid()
    apps: dict[int, dict] = {}            # pid główny → exe, wyjścia, szczyt

    # 1) aplikacje z sesją audio – kilka odczytów miernika, bo mowa ma przerwy
    try:
        sessions = _render_sessions()
        peaks = [0.0] * len(sessions)
        for _ in range(6):
            for k, (_pid, _dev, meter) in enumerate(sessions):
                peaks[k] = max(peaks[k], _peak(meter))
            time.sleep(0.05)
        for (pid, dev, _m), pk in zip(sessions, peaks):
            root = _root_pid(pid)
            exe = _exe(root) or _exe(pid)
            if not exe or own in (pid, root) or exe.lower() in _SYSTEM_EXES:
                continue
            a = apps.setdefault(root, {"exe": exe, "devs": [], "peak": 0.0})
            if dev and dev not in a["devs"]:
                a["devs"].append(dev)
            a["peak"] = max(a["peak"], pk)
    except Exception:
        log.exception("pycaw")

    playing, idle = [], []
    exe_count: dict[str, int] = {}
    for a in apps.values():
        exe_count[a["exe"].lower()] = exe_count.get(a["exe"].lower(), 0) + 1
    for root, a in sorted(apps.items(), key=lambda x: _pretty(x[1]["exe"]).lower()):
        on = a["peak"] >= PLAYING
        where = ", ".join(_clean_device(d) for d in a["devs"])
        detail = ("gra teraz" if on else "teraz cisza") + (f" · {where}" if where else "")
        if exe_count[a["exe"].lower()] > 1:           # dwa osobne okna tej samej aplikacji
            detail += f" · PID {root}"
        info = AudioSourceInfo("process", _pretty(a["exe"]), pid=root, exe=a["exe"], active=on,
                               detail=detail, hidden=not on)
        (playing if on else idle).append(info)

    # 2) aplikacje z oknami, bez sesji audio (mogą zacząć grać później) – schowane
    windows = []
    try:
        from .screen_capture import list_windows
        seen_exes = {a["exe"].lower() for a in apps.values()}
        for w in list_windows():
            exe = _exe(w.pid)
            if not exe or exe.lower() in seen_exes or exe.lower() in _SYSTEM_EXES:
                continue
            root = _root_pid(w.pid)
            if root in apps or root == own:
                continue
            seen_exes.add(exe.lower())
            windows.append(AudioSourceInfo("process", _pretty(exe), pid=root, exe=exe,
                                           detail="jeszcze nic nie grała", hidden=True))
    except Exception:
        log.exception("okna")
    windows.sort(key=lambda s: s.label.lower())

    # 3) cały dźwięk systemowy + mikrofony
    devices: list[AudioSourceInfo] = []
    try:
        out_name, meter = _default_output()
        sys_on = max(_peak(meter) for _ in range(3)) >= PLAYING
    except Exception:
        out_name, sys_on = "", False
    devices.append(AudioSourceInfo("system", "Cały dźwięk systemowy", active=sys_on,
                                   detail="wszystko, co słychać" + (f" · {_clean_device(out_name)}" if out_name else "")))
    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_in = wasapi.get("defaultInputDevice", -1)
            seen_mics: set[str] = set()
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d.get("hostApi") != wasapi["index"] or d.get("isLoopbackDevice") or d.get("maxInputChannels", 0) < 1:
                    continue
                name = _clean_device(d["name"])
                virtual = any(v in d["name"].lower() for v in _VIRTUAL_DEVICES)
                dup = name.lower() in seen_mics
                seen_mics.add(name.lower())
                detail = "domyślny" if i == default_in else ("urządzenie wirtualne" if virtual else "")
                devices.append(AudioSourceInfo("mic", f"Mikrofon: {name}", device_index=i, detail=detail,
                                               hidden=(virtual or dup) and i != default_in))
        finally:
            p.terminate()
    except Exception:
        log.exception("mikrofony")
    devices.sort(key=lambda s: (s.kind != "system", s.hidden, s.detail != "domyślny"))
    return playing + devices + idle + windows


class _WinLevelMonitor:
    """Poziomy dźwięku na żywo dla listy źródeł – bez nagrywania, z mierników Windows (wątek w tle).

    Mikrofon mierzy się tylko jeden – wybrany: odczyt wymaga otwarcia strumienia, a Windows pokazuje wtedy
    „aplikacja używa mikrofonu”. `new_playing` – aplikacje, które zaczęły grać, a nie ma ich na liście."""

    def __init__(self):
        self.levels: dict[str, float] = {}
        self.new_playing: set[int] = set()
        self._known: set[int] = set()
        self._mic = -1
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def set_known(self, pids):
        self._known = set(pids)
        self.new_playing = set()

    def set_mic(self, device_index: int):
        self._mic = device_index

    def set_source(self, info: Optional[AudioSourceInfo]):
        """Wybrane źródło – mierzymy tylko wybrany mikrofon (aplikacje i system mają mierniki Windows)."""
        self.set_mic(info.device_index if info is not None and info.kind == "mic" else -1)

    def measurable(self, info: AudioSourceInfo, current: Optional[AudioSourceInfo]) -> bool:
        """Mikrofon mierzymy tylko wybrany (inaczej Windows pokazywałby, że wszystkie są w użyciu)."""
        return self.running and (info.kind != "mic" or info is current)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="LevelMonitor", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1.5)
        self._thread = None
        self.levels = {}

    def _run(self, stop: threading.Event):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        own = os.getpid()
        sessions: list = []
        roots: dict[int, int] = {}
        system_exe: dict[int, bool] = {}
        speakers = None
        next_scan = 0.0
        mic_src, mic_dev, mic_peak = None, -1, [0.0]

        def on_mic(arr, _rate):
            mic_peak[0] = max(mic_peak[0], float(np.abs(arr).max()) if arr.size else 0.0)

        try:
            while not stop.is_set():
                now = time.monotonic()
                if now >= next_scan:               # nowe aplikacje / zmiana wyjścia – co 1,5 s
                    try:
                        sessions = _render_sessions(names=False)
                        speakers = _default_output()[1]
                    except Exception:
                        log.exception("LevelMonitor: sesje")
                    next_scan = now + 1.5
                lv: dict[str, float] = {}
                for pid, _d, meter in sessions:
                    root = roots.get(pid)
                    if root is None:
                        root = roots[pid] = _root_pid(pid)
                    k = f"process:{root}"
                    pk = _peak(meter)
                    lv[k] = max(lv.get(k, 0.0), pk)
                    if pk >= PLAYING and root not in self._known and root != own:
                        if root not in system_exe:
                            system_exe[root] = (_exe(root) or "").lower() in _SYSTEM_EXES
                        if not system_exe[root]:
                            self.new_playing.add(root)
                if speakers is not None:
                    lv["system"] = _peak(speakers)
                if self._mic != mic_dev:           # zmiana wybranego mikrofonu
                    if mic_src is not None:
                        mic_src.stop()
                        mic_src = None
                    mic_dev = self._mic
                    if mic_dev >= 0:
                        try:
                            mic_src = _PyAudioSource(on_mic, device_index=mic_dev, loopback=False)
                            mic_src.start()
                        except Exception:
                            log.exception("LevelMonitor: mikrofon %d", mic_dev)
                            mic_src = None
                if mic_src is not None:
                    lv[f"mic:{mic_dev}"] = mic_peak[0]
                    mic_peak[0] = 0.0
                self.levels = lv
                stop.wait(0.06)
        finally:
            if mic_src is not None:
                try:
                    mic_src.stop()
                except Exception:
                    log.exception("LevelMonitor: zamykanie mikrofonu")


if IS_MAC:
    from .mac_audio import LevelMonitor
else:
    LevelMonitor = _WinLevelMonitor


def record_preview(info: AudioSourceInfo, seconds: float = 4.0, backend: str = "auto") -> tuple[np.ndarray, int]:
    """Nagrywa kilka sekund z wybranego źródła (przycisk „Odsłuchaj”). Zwraca ((n, kanały) float32, częstotliwość).
    Odtwarzanie jest dopiero PO nagraniu – dzięki temu nie ma sprzężenia nawet przy „całym dźwięku systemowym”."""
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    chunks: list[np.ndarray] = []
    rate = [48000]

    def cb(arr, r):
        chunks.append(np.asarray(arr, dtype=np.float32).copy())
        rate[0] = r

    src = open_source(info, cb, backend)
    try:
        time.sleep(seconds)
    finally:
        src.stop()
    if not chunks:
        return np.zeros((0, 1), dtype=np.float32), rate[0]
    width = chunks[0].shape[1] if chunks[0].ndim == 2 else 1
    chunks = [c.reshape(-1, width) for c in chunks if c.size % width == 0]
    return np.concatenate(chunks), rate[0]


def play_preview(audio: np.ndarray, rate: int):
    """Odtwarza nagrany podgląd na domyślnym wyjściu (czeka do końca)."""
    import tempfile

    import soundfile as sf
    path = Path(tempfile.gettempdir()) / "wyklady_odsluch.wav"
    sf.write(str(path), np.clip(audio, -1.0, 1.0), rate, subtype="PCM_16")
    if IS_MAC:
        from .mac_audio import play_file
        play_file(str(path))
        return
    import winsound
    winsound.PlaySound(str(path), winsound.SND_FILENAME)


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
    if IS_MAC:
        from .mac_audio import open_source as mac_open
        return mac_open(info, cb, backend)
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

    # pauza: dźwięk z tego czasu jest pomijany (nie trafia do pliku ani do transkrypcji)
    def pause(self):
        if not getattr(self, "paused", False):
            self._pause_at = time.monotonic()
            self.paused = True

    def resume(self):
        if getattr(self, "paused", False):
            self.t0 += time.monotonic() - self._pause_at
            self.paused = False

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
                if getattr(self, "paused", False):
                    self.level_db = -90.0
                    continue
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
