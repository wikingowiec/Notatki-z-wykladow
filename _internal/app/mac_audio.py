"""Dźwięk na macOS (14.4+, Apple Silicon): to samo co audio_capture.py na Windows, innymi narzędziami.
Nowe w wersji 2.2.0.

Źródła (AudioSourceInfo jak na Windows):
  * process – dźwięk jednej aplikacji: Core Audio process tap (CATapDescription + prywatne urządzenie zbiorcze),
              zapas: ScreenCaptureKit (dźwięk wybranej aplikacji)
  * system  – cały dźwięk systemu: globalny tap bez własnego procesu, zapas: ScreenCaptureKit
  * mic     – mikrofon: wejście urządzenia Core Audio (device_index = AudioObjectID)

Funkcje C z Core Audio wołamy przez ctypes (IOProc to zwykły wskaźnik na funkcję – prościej i pewniej niż bloki
w pyobjc). pyobjc tylko do klasy CATapDescription, słownika urządzenia zbiorczego i nazw aplikacji.
Uprawnienia: mikrofon (TCC Microphone), dźwięk aplikacji / systemu („Nagrywanie dźwięku systemu”) – patrz
mac_permissions.py. Bez zgody macOS daje ciszę, a nie błąd."""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
import uuid
from ctypes import POINTER, Structure, byref, c_bool, c_double, c_int32, c_long, c_uint32, c_void_p
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

_CA = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
_CF = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")


def fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


SYSTEM_OBJECT = 1
SCOPE_GLOBAL, SCOPE_INPUT = fourcc("glob"), fourcc("inpt")
ELEMENT_MAIN = 0
P_DEVICES = fourcc("dev#")
P_DEFAULT_INPUT = fourcc("dIn ")
P_DEFAULT_OUTPUT = fourcc("dOut")
P_PROCESSES = fourcc("prs#")
P_PID_TO_PROCESS = fourcc("id2p")
P_PROCESS_PID = fourcc("ppid")
P_PROCESS_RUNNING_OUTPUT = fourcc("piro")
P_DEVICE_UID = fourcc("uid ")
P_NAME = fourcc("lnam")
P_STREAM_CONFIG = fourcc("slay")
P_SAMPLE_RATE = fourcc("nsrt")
P_TRANSPORT = fourcc("tran")
P_TAP_FORMAT = fourcc("tfmt")
TRANSPORT_VIRTUAL, TRANSPORT_AGGREGATE = fourcc("virt"), fourcc("grup")
UTF8 = 0x08000100

PLAYING = 0.002
OWN_NAME = "Wykłady"            # nazwa naszych prywatnych urządzeń zbiorczych (nie pokazujemy ich jako mikrofonów)

# procesy systemowe z obiektem dźwięku – nie ma sensu ich nagrywać
_SYSTEM_NAMES = {"coreaudiod", "systemsoundserverd", "audiomxd", "callservicesd", "avconferenced", "corespeechd",
                 "heard", "assistantd", "universalaccessd", "windowserver", "loginwindow", "controlcenter",
                 "notificationcenter", "siri", "accessibilityuiserver", "python", "python3", "python3.12"}
_SYSTEM_DIRS = ("/System/", "/usr/libexec/", "/usr/sbin/", "/usr/bin/", "/Library/Apple/")
_VIRTUAL_HINTS = ("blackhole", "loopback", "soundflower", "zoomaudiodevice", "teams audio", "ms teams", "virtual",
                  "cadefaultdeviceaggregate", "krisp", "rogue amoeba")


class PropAddr(Structure):
    _fields_ = [("mSelector", c_uint32), ("mScope", c_uint32), ("mElement", c_uint32)]


class ASBD(Structure):
    _fields_ = [("mSampleRate", c_double), ("mFormatID", c_uint32), ("mFormatFlags", c_uint32),
                ("mBytesPerPacket", c_uint32), ("mFramesPerPacket", c_uint32), ("mBytesPerFrame", c_uint32),
                ("mChannelsPerFrame", c_uint32), ("mBitsPerChannel", c_uint32), ("mReserved", c_uint32)]


class AudioBuffer(Structure):
    _fields_ = [("mNumberChannels", c_uint32), ("mDataByteSize", c_uint32), ("mData", c_void_p)]


# AudioBufferList = UInt32 mNumberBuffers + (wyrównanie do 8) + AudioBuffer[n] po 16 bajtów
_ABL_HEAD, _AB_SIZE = 8, ctypes.sizeof(AudioBuffer)

IOProc = ctypes.CFUNCTYPE(c_int32, c_uint32, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)

_CA.AudioObjectGetPropertyDataSize.argtypes = [c_uint32, POINTER(PropAddr), c_uint32, c_void_p, POINTER(c_uint32)]
_CA.AudioObjectGetPropertyData.argtypes = [c_uint32, POINTER(PropAddr), c_uint32, c_void_p, POINTER(c_uint32), c_void_p]
_CA.AudioHardwareCreateAggregateDevice.argtypes = [c_void_p, POINTER(c_uint32)]
_CA.AudioHardwareDestroyAggregateDevice.argtypes = [c_uint32]
_CA.AudioDeviceCreateIOProcID.argtypes = [c_uint32, IOProc, c_void_p, POINTER(c_void_p)]
_CA.AudioDeviceDestroyIOProcID.argtypes = [c_uint32, c_void_p]
_CA.AudioDeviceStart.argtypes = [c_uint32, c_void_p]
_CA.AudioDeviceStop.argtypes = [c_uint32, c_void_p]
_CF.CFStringGetLength.argtypes = [c_void_p]
_CF.CFStringGetLength.restype = c_long
_CF.CFStringGetMaximumSizeForEncoding.argtypes = [c_long, c_uint32]
_CF.CFStringGetMaximumSizeForEncoding.restype = c_long
_CF.CFStringGetCString.argtypes = [c_void_p, ctypes.c_char_p, c_long, c_uint32]
_CF.CFStringGetCString.restype = c_bool
_CF.CFRelease.argtypes = [c_void_p]


def has_process_taps() -> bool:
    """Process taps są od macOS 14.2 (stabilnie od 14.4)."""
    return hasattr(_CA, "AudioHardwareCreateProcessTap")


if has_process_taps():
    _CA.AudioHardwareCreateProcessTap.argtypes = [c_void_p, POINTER(c_uint32)]
    _CA.AudioHardwareDestroyProcessTap.argtypes = [c_uint32]


class CoreAudioError(RuntimeError):
    pass


def _check(status: int, what: str):
    if status:
        code = status.to_bytes(4, "big", signed=True)
        txt = code.decode("ascii") if all(32 <= b < 127 for b in code) else str(status)
        raise CoreAudioError(f"{what}: błąd Core Audio {txt}")


def _addr(sel: int, scope: int = SCOPE_GLOBAL) -> PropAddr:
    return PropAddr(sel, scope, ELEMENT_MAIN)


def _get_raw(obj: int, sel: int, scope: int = SCOPE_GLOBAL, qual: Optional[ctypes._SimpleCData] = None) -> bytes:
    a = _addr(sel, scope)
    qsize = ctypes.sizeof(qual) if qual is not None else 0
    qptr = c_void_p(ctypes.addressof(qual)) if qual is not None else None
    size = c_uint32(0)
    _check(_CA.AudioObjectGetPropertyDataSize(obj, byref(a), qsize, qptr, byref(size)), "rozmiar właściwości")
    if not size.value:
        return b""
    buf = ctypes.create_string_buffer(size.value)
    _check(_CA.AudioObjectGetPropertyData(obj, byref(a), qsize, qptr, byref(size), buf), "właściwość")
    return buf.raw[:size.value]


def _get_u32(obj: int, sel: int, scope: int = SCOPE_GLOBAL, qual=None) -> int:
    raw = _get_raw(obj, sel, scope, qual)
    return int.from_bytes(raw[:4], "little") if len(raw) >= 4 else 0


def _get_ids(obj: int, sel: int) -> list[int]:
    raw = _get_raw(obj, sel)
    return list(np.frombuffer(raw, dtype=np.uint32)) if raw else []


def _get_f64(obj: int, sel: int) -> float:
    raw = _get_raw(obj, sel)
    return float(np.frombuffer(raw[:8], dtype=np.float64)[0]) if len(raw) >= 8 else 0.0


def _get_str(obj: int, sel: int, scope: int = SCOPE_GLOBAL) -> str:
    """Właściwość typu CFStringRef (właściciel – my, więc CFRelease)."""
    a = _addr(sel, scope)
    ref = c_void_p(0)
    size = c_uint32(ctypes.sizeof(c_void_p))
    if _CA.AudioObjectGetPropertyData(obj, byref(a), 0, None, byref(size), byref(ref)) or not ref.value:
        return ""
    try:
        n = _CF.CFStringGetLength(ref)
        cap = _CF.CFStringGetMaximumSizeForEncoding(n, UTF8) + 1
        buf = ctypes.create_string_buffer(cap)
        return buf.value.decode("utf-8", "replace") if _CF.CFStringGetCString(ref, buf, cap, UTF8) else ""
    finally:
        _CF.CFRelease(ref)


def _input_channels(dev: int) -> int:
    try:
        raw = _get_raw(dev, P_STREAM_CONFIG, SCOPE_INPUT)
    except CoreAudioError:
        return 0
    if len(raw) < 4:
        return 0
    n = int.from_bytes(raw[:4], "little")
    total = 0
    for i in range(n):
        off = _ABL_HEAD + i * _AB_SIZE
        if off + 4 <= len(raw):
            total += int.from_bytes(raw[off:off + 4], "little")
    return total


# ---------------------------------------------------------------------------
# Procesy i aplikacje
# ---------------------------------------------------------------------------
_responsible = None


def _responsible_pid(pid: int) -> int:
    """Aplikacja odpowiedzialna za proces (np. Safari dla com.apple.WebKit.GPU, Chrome dla Helpera)."""
    global _responsible
    if _responsible is None:
        try:
            lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            fn = lib.responsibility_get_pid_responsible_for_pid
            fn.argtypes, fn.restype = [c_int32], c_int32
            _responsible = fn
        except (OSError, AttributeError):
            _responsible = False
    if _responsible:
        try:
            r = int(_responsible(pid))
            if r > 0:
                return r
        except Exception:  # noqa: BLE001
            pass
    return pid


def _root_pid(pid: int) -> int:
    root = _responsible_pid(pid)
    if root != pid:
        return root
    try:                     # zapas: rodzic z tą samą aplikacją (…/X.app/…)
        import psutil
        p = psutil.Process(pid)
        exe = p.exe()
        app = exe.split(".app/")[0] if ".app/" in exe else ""
        while app:
            parent = p.parent()
            if parent is None or parent.pid <= 1:
                break
            pexe = parent.exe()
            if not pexe.startswith(app):
                break
            p = parent
        return p.pid
    except Exception:  # noqa: BLE001
        return pid


def _app_info(pid: int) -> tuple[str, str, bool]:
    """(nazwa, identyfikator do zapamiętania, zwykła aplikacja z Docka)."""
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            name = str(app.localizedName() or "")
            bid = str(app.bundleIdentifier() or "")
            if name:
                return name, bid or name, int(app.activationPolicy()) == 0
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil
        p = psutil.Process(pid)
        exe = p.exe()
        if exe.startswith(_SYSTEM_DIRS) or p.name().lower() in _SYSTEM_NAMES:
            return "", "", False
        return p.name(), p.name(), False
    except Exception:  # noqa: BLE001
        return "", "", False


def audio_processes() -> list[tuple[int, int, bool]]:
    """[(AudioObjectID procesu, pid, czy właśnie gra)] – procesy, które używają dźwięku."""
    out = []
    try:
        objs = _get_ids(SYSTEM_OBJECT, P_PROCESSES)
    except CoreAudioError:
        return out
    for o in objs:
        try:
            pid = int(np.int32(_get_u32(o, P_PROCESS_PID)))
            running = bool(_get_u32(o, P_PROCESS_RUNNING_OUTPUT))
        except CoreAudioError:
            continue
        if pid > 0:
            out.append((int(o), pid, running))
    return out


def process_objects_for(root: int) -> list[int]:
    """Obiekty dźwięku wszystkich procesów aplikacji (także pomocniczych)."""
    return [o for o, pid, _r in audio_processes() if pid == root or _root_pid(pid) == root]


def _own_process_object() -> int:
    try:
        return _get_u32(SYSTEM_OBJECT, P_PID_TO_PROCESS, qual=c_int32(os.getpid()))
    except CoreAudioError:
        return 0


def _running_apps() -> list[tuple[int, str, str]]:
    """Zwykłe aplikacje (z Docka): [(pid, nazwa, identyfikator)]."""
    out = []
    try:
        from AppKit import NSWorkspace
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if int(app.activationPolicy()) != 0:
                continue
            name = str(app.localizedName() or "")
            if name:
                out.append((int(app.processIdentifier()), name, str(app.bundleIdentifier() or name)))
    except Exception:  # noqa: BLE001
        log.exception("lista aplikacji")
    return out


# ---------------------------------------------------------------------------
# Urządzenia
# ---------------------------------------------------------------------------
def input_devices() -> list[tuple[int, str, bool, bool]]:
    """[(AudioObjectID, nazwa, domyślny, wirtualny)] – urządzenia z wejściem (mikrofony)."""
    out = []
    try:
        default_in = _get_u32(SYSTEM_OBJECT, P_DEFAULT_INPUT)
        devs = _get_ids(SYSTEM_OBJECT, P_DEVICES)
    except CoreAudioError:
        return out
    for d in devs:
        d = int(d)
        if _input_channels(d) < 1:
            continue
        name = _get_str(d, P_NAME) or f"Urządzenie {d}"
        if name.startswith(OWN_NAME):
            continue
        try:
            tr = _get_u32(d, P_TRANSPORT)
        except CoreAudioError:
            tr = 0
        virtual = tr in (TRANSPORT_VIRTUAL, TRANSPORT_AGGREGATE) or any(h in name.lower() for h in _VIRTUAL_HINTS)
        out.append((d, name, d == default_in, virtual))
    return out


def default_output_name() -> str:
    try:
        return _get_str(_get_u32(SYSTEM_OBJECT, P_DEFAULT_OUTPUT), P_NAME)
    except CoreAudioError:
        return ""


def list_audio_sources():
    """Ta sama lista co na Windows: grające aplikacje, urządzenia (dźwięk systemu, mikrofony), reszta schowana."""
    from .audio_capture import AudioSourceInfo
    own = os.getpid()
    apps: dict[int, dict] = {}
    for _obj, pid, running in audio_processes():
        root = _root_pid(pid)
        if own in (pid, root):
            continue
        a = apps.get(root)
        if a is None:
            name, ident, _regular = _app_info(root)
            if not name or name.lower() in _SYSTEM_NAMES:
                continue
            a = apps[root] = {"name": name, "id": ident, "on": False}
        a["on"] = a["on"] or running
    playing, idle = [], []
    names: dict[str, int] = {}
    for a in apps.values():
        names[a["name"].lower()] = names.get(a["name"].lower(), 0) + 1
    for root, a in sorted(apps.items(), key=lambda x: x[1]["name"].lower()):
        detail = "gra teraz" if a["on"] else "teraz cisza"
        if names[a["name"].lower()] > 1:
            detail += f" · PID {root}"
        info = AudioSourceInfo("process", a["name"], pid=root, exe=a["id"], active=a["on"], detail=detail,
                               hidden=not a["on"])
        (playing if a["on"] else idle).append(info)

    # aplikacje z Docka, które jeszcze nic nie grały – schowane (dźwięk złapie wtedy ScreenCaptureKit)
    windows = []
    seen = {a["id"].lower() for a in apps.values()}
    for pid, name, ident in _running_apps():
        if pid == own or pid in apps or ident.lower() in seen:
            continue
        seen.add(ident.lower())
        windows.append(AudioSourceInfo("process", name, pid=pid, exe=ident, detail="jeszcze nic nie grała",
                                       hidden=True))
    windows.sort(key=lambda s: s.label.lower())

    devices = []
    out_name = default_output_name()
    sys_on = any(r for _o, p, r in audio_processes() if p != own)
    devices.append(AudioSourceInfo("system", "Cały dźwięk systemowy", active=sys_on,
                                   detail="wszystko, co słychać" + (f" · {out_name}" if out_name else "")))
    seen_mics: set[str] = set()
    for dev, name, default, virtual in input_devices():
        dup = name.lower() in seen_mics
        seen_mics.add(name.lower())
        detail = "domyślny" if default else ("urządzenie wirtualne" if virtual else "")
        devices.append(AudioSourceInfo("mic", f"Mikrofon: {name}", device_index=dev, detail=detail,
                                       hidden=(virtual or dup) and not default))
    devices.sort(key=lambda s: (s.kind != "system", s.hidden, s.detail != "domyślny"))
    return playing + devices + idle + windows


# ---------------------------------------------------------------------------
# Przechwytywanie: IOProc na urządzeniu (mikrofon albo urządzenie zbiorcze z tapem)
# ---------------------------------------------------------------------------
class _IOProcSource:
    """Woła cb((n, kanały) float32, częstotliwość) z wątku Core Audio. Bufory IOProc są zawsze Float32.

    take_last – ile ostatnich kanałów brać (urządzenie zbiorcze: wejścia głównego podurządzenia, np. mikrofon
    słuchawek, są przed kanałami tapu)."""

    def __init__(self, device: int, cb, take_last: int = 0):
        self.device = device
        self.cb = cb
        self.take_last = take_last
        self.rate = int(_get_f64(device, P_SAMPLE_RATE) or 48000)
        self._proc = IOProc(self._io)       # referencja musi żyć do końca
        self._proc_id = c_void_p(0)
        self._started = False

    def _io(self, _dev, _now, in_data, _in_time, _out, _out_time, _client):
        try:
            if not in_data:
                return 0
            n = c_uint32.from_address(in_data).value
            bufs = [AudioBuffer.from_address(in_data + _ABL_HEAD + i * _AB_SIZE) for i in range(n)]
            if self.take_last:
                pick, ch = [], 0
                for b in reversed(bufs):
                    if ch >= self.take_last:
                        break
                    pick.insert(0, b)
                    ch += max(1, b.mNumberChannels)
                bufs = pick
            arrays = []
            for b in bufs:
                count = b.mDataByteSize // 4
                if not b.mData or not count:
                    continue
                a = np.frombuffer((ctypes.c_float * count).from_address(b.mData), dtype=np.float32).copy()
                ch = max(1, b.mNumberChannels)
                arrays.append(a[: count - count % ch].reshape(-1, ch))
            if arrays:
                frames = min(a.shape[0] for a in arrays)
                arr = arrays[0][:frames] if len(arrays) == 1 else np.concatenate([a[:frames] for a in arrays], axis=1)
                self.cb(arr, self.rate)
        except Exception:  # noqa: BLE001 – wyjątek w wątku Core Audio nie może wyjść dalej
            pass
        return 0

    def start(self):
        _check(_CA.AudioDeviceCreateIOProcID(self.device, self._proc, None, byref(self._proc_id)), "IOProc")
        try:
            _check(_CA.AudioDeviceStart(self.device, self._proc_id), "start urządzenia")
        except CoreAudioError:
            _CA.AudioDeviceDestroyIOProcID(self.device, self._proc_id)
            raise
        self._started = True

    def stop(self):
        if self._started:
            self._started = False
            try:
                _CA.AudioDeviceStop(self.device, self._proc_id)
            finally:
                _CA.AudioDeviceDestroyIOProcID(self.device, self._proc_id)


class _MicSource(_IOProcSource):
    def __init__(self, device: int, cb):
        if device < 0:
            device = _get_u32(SYSTEM_OBJECT, P_DEFAULT_INPUT)
        super().__init__(device, cb)
        self.name = f"Core Audio: {_get_str(device, P_NAME)}"


class _TapSource:
    """Core Audio process tap: dźwięk wybranych procesów (albo całego systemu bez nas) → urządzenie zbiorcze."""

    def __init__(self, cb, process_objects: Optional[list[int]] = None):
        if not has_process_taps():
            raise CoreAudioError("Ten macOS nie ma process taps (potrzebny macOS 14.4 lub nowszy)")
        import objc
        from Foundation import NSDictionary, NSUUID
        self.cb = cb
        self.tap = c_uint32(0)
        self.agg = c_uint32(0)
        self.io: Optional[_IOProcSource] = None
        cls = objc.lookUpClass("CATapDescription")
        if process_objects is not None:
            if not process_objects:
                raise CoreAudioError("Ta aplikacja jeszcze nic nie grała")
            desc = cls.alloc().initStereoMixdownOfProcesses_(list(process_objects))
            self.name = "Core Audio (aplikacja)"
        else:
            own = _own_process_object()
            desc = cls.alloc().initStereoGlobalTapButExcludeProcesses_([own] if own else [])
            self.name = "Core Audio (cały system)"
        desc.setUUID_(NSUUID.UUID())
        desc.setName_(OWN_NAME)
        try:
            desc.setPrivateTap_(True)           # tap widoczny tylko dla nas
        except AttributeError:
            desc.setPrivate_(True)
        desc.setMuteBehavior_(0)              # CATapUnmuted – dalej słychać w głośnikach
        try:
            _check(_CA.AudioHardwareCreateProcessTap(c_void_p(objc.pyobjc_id(desc)), byref(self.tap)), "tap")
            tap_uid = str(desc.UUID().UUIDString())
            fmt = ASBD()
            size = c_uint32(ctypes.sizeof(ASBD))
            a = _addr(P_TAP_FORMAT)
            _CA.AudioObjectGetPropertyData(self.tap.value, byref(a), 0, None, byref(size), byref(fmt))
            channels = int(fmt.mChannelsPerFrame or 2)
            out_dev = _get_u32(SYSTEM_OBJECT, P_DEFAULT_OUTPUT)
            out_uid = _get_str(out_dev, P_DEVICE_UID)
            spec = {
                "name": f"{OWN_NAME} – nagrywanie", "uid": f"pl.wystrychowski.wyklady.{uuid.uuid4()}",
                "private": True, "stacked": False, "tapautostart": True,
                "taps": [{"uid": tap_uid, "drift": True}],
            }
            if out_uid:            # zegar z głównego wyjścia (jak w przykładzie Apple)
                spec["master"] = out_uid
                spec["subdevices"] = [{"uid": out_uid}]
            d = NSDictionary.dictionaryWithDictionary_(spec)
            _check(_CA.AudioHardwareCreateAggregateDevice(c_void_p(objc.pyobjc_id(d)), byref(self.agg)),
                   "urządzenie zbiorcze")
            self.io = _IOProcSource(self.agg.value, cb, take_last=channels)
            if fmt.mSampleRate and not _get_f64(self.agg.value, P_SAMPLE_RATE):
                self.io.rate = int(fmt.mSampleRate)
        except Exception:
            self._destroy()
            raise

    def start(self):
        try:
            self.io.start()
        except Exception:
            self._destroy()
            raise

    def _destroy(self):
        if self.agg.value:
            try:
                _CA.AudioHardwareDestroyAggregateDevice(self.agg.value)
            except Exception:  # noqa: BLE001
                log.exception("usuwanie urządzenia zbiorczego")
            self.agg = c_uint32(0)
        if self.tap.value:
            try:
                _CA.AudioHardwareDestroyProcessTap(self.tap.value)
            except Exception:  # noqa: BLE001
                log.exception("usuwanie tapu")
            self.tap = c_uint32(0)

    def stop(self):
        try:
            if self.io is not None:
                self.io.stop()
        finally:
            self._destroy()


# ---------------------------------------------------------------------------
# Zapas: ScreenCaptureKit (dźwięk aplikacji / systemu; wymaga zgody „Nagrywanie ekranu”)
# ---------------------------------------------------------------------------
_CM = None
_sck_output_cls = None


def _coremedia():
    global _CM
    if _CM is None:
        cm = ctypes.CDLL("/System/Library/Frameworks/CoreMedia.framework/CoreMedia")
        cm.CMSampleBufferGetDataBuffer.argtypes = [c_void_p]
        cm.CMSampleBufferGetDataBuffer.restype = c_void_p
        cm.CMSampleBufferGetNumSamples.argtypes = [c_void_p]
        cm.CMSampleBufferGetNumSamples.restype = c_long
        cm.CMSampleBufferGetFormatDescription.argtypes = [c_void_p]
        cm.CMSampleBufferGetFormatDescription.restype = c_void_p
        cm.CMAudioFormatDescriptionGetStreamBasicDescription.argtypes = [c_void_p]
        cm.CMAudioFormatDescriptionGetStreamBasicDescription.restype = POINTER(ASBD)
        cm.CMBlockBufferGetDataLength.argtypes = [c_void_p]
        cm.CMBlockBufferGetDataLength.restype = ctypes.c_size_t
        cm.CMBlockBufferCopyDataBytes.argtypes = [c_void_p, ctypes.c_size_t, ctypes.c_size_t, c_void_p]
        cm.CMBlockBufferCopyDataBytes.restype = c_int32
        _CM = cm
    return _CM


def _sck_output_class():
    """Klasa Objective-C odbierająca dźwięk ze SCStream (definiowana raz na proces)."""
    global _sck_output_cls
    if _sck_output_cls is None:
        import importlib

        import objc
        from Foundation import NSObject
        importlib.import_module("ScreenCaptureKit")      # metadane protokołu SCStreamOutput

        class WykladySCKAudioOutput(NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]):
            def stream_didOutputSampleBuffer_ofType_(self, _stream, sbuf, kind):
                if kind != 1:              # SCStreamOutputTypeAudio
                    return
                fn = getattr(self, "pyCallback", None)
                if fn is not None:
                    fn(sbuf)

        _sck_output_cls = WykladySCKAudioOutput
    return _sck_output_cls


def _wait_handler(call, timeout: float = 6.0):
    """Woła metodę z completion handlerem i czeka na wynik (handler przychodzi z innej kolejki)."""
    ev = threading.Event()
    box: list = []

    def handler(*args):
        box.append(args)
        ev.set()
    call(handler)
    if not ev.wait(timeout):
        raise TimeoutError("ScreenCaptureKit nie odpowiedział")
    return box[0]


class _SCKAudioSource:
    def __init__(self, info, cb):
        import objc
        from CoreMedia import CMTimeMake
        from ScreenCaptureKit import SCContentFilter, SCShareableContent, SCStream, SCStreamConfiguration
        self.cb = cb
        self._objc = objc
        content, err = _wait_handler(
            lambda h: SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
                True, True, h))
        if content is None:
            raise RuntimeError(f"ScreenCaptureKit: {err}")
        displays = list(content.displays() or [])
        if not displays:
            raise RuntimeError("ScreenCaptureKit: brak ekranu")
        apps = list(content.applications() or [])
        if info.kind == "process":
            chosen = [a for a in apps if int(a.processID()) == info.pid or _root_pid(int(a.processID())) == info.pid]
            if not chosen:
                raise RuntimeError("ScreenCaptureKit nie widzi tej aplikacji")
            flt = SCContentFilter.alloc().initWithDisplay_includingApplications_exceptingWindows_(displays[0], chosen, [])
            self.name = "ScreenCaptureKit (aplikacja)"
        else:
            own = [a for a in apps if int(a.processID()) == os.getpid()]
            flt = SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(displays[0], own, [])
            self.name = "ScreenCaptureKit (cały system)"
        cfg = SCStreamConfiguration.alloc().init()
        cfg.setCapturesAudio_(True)
        cfg.setExcludesCurrentProcessAudio_(True)
        cfg.setSampleRate_(48000)
        cfg.setChannelCount_(2)
        cfg.setWidth_(2)
        cfg.setHeight_(2)
        cfg.setMinimumFrameInterval_(CMTimeMake(1, 1))
        self.stream = SCStream.alloc().initWithFilter_configuration_delegate_(flt, cfg, None)
        self.output = _sck_output_class().alloc().init()
        self.output.pyCallback = self._on_sample
        res = self.stream.addStreamOutput_type_sampleHandlerQueue_error_(self.output, 1, None, None)
        ok = res[0] if isinstance(res, tuple) else res
        if not ok:
            raise RuntimeError(f"ScreenCaptureKit: {res[1] if isinstance(res, tuple) else 'błąd'}")

    def _on_sample(self, sbuf):
        try:
            cm = _coremedia()
            ref = self._objc.pyobjc_id(sbuf)
            fd = cm.CMSampleBufferGetFormatDescription(ref)
            bb = cm.CMSampleBufferGetDataBuffer(ref)
            if not fd or not bb:
                return
            asbd = cm.CMAudioFormatDescriptionGetStreamBasicDescription(fd).contents
            frames = cm.CMSampleBufferGetNumSamples(ref)
            n = cm.CMBlockBufferGetDataLength(bb)
            if not frames or not n:
                return
            buf = ctypes.create_string_buffer(n)
            if cm.CMBlockBufferCopyDataBytes(bb, 0, n, buf):
                return
            arr = np.frombuffer(buf.raw, dtype=np.float32)
            ch = max(1, int(asbd.mChannelsPerFrame))
            if asbd.mFormatFlags & 0x20:           # kAudioFormatFlagIsNonInterleaved – kanały jeden po drugim
                arr = arr[: frames * ch].reshape(ch, -1).T
            else:
                arr = arr[: frames * ch].reshape(-1, ch)
            self.cb(np.ascontiguousarray(arr), int(asbd.mSampleRate or 48000))
        except Exception:  # noqa: BLE001
            pass

    def start(self):
        (err,) = _wait_handler(lambda h: self.stream.startCaptureWithCompletionHandler_(h))
        if err is not None:
            raise RuntimeError(f"ScreenCaptureKit: {err.localizedDescription()}")

    def stop(self):
        try:
            _wait_handler(lambda h: self.stream.stopCaptureWithCompletionHandler_(h), 3.0)
        except Exception:  # noqa: BLE001
            log.exception("SCStream stop")
        self.output.pyCallback = None


# ---------------------------------------------------------------------------
def open_source(info, cb, backend: str = "auto", fallback: bool = True):
    """Otwiera i uruchamia źródło. backend: auto / tap / sck (ustawienia „Przechwytywanie aplikacji”).
    fallback=False – tylko wybrany sposób (miernik poziomu: bez ScreenCaptureKit, który pyta o zgodę na ekran)."""
    if info.kind == "mic":
        src = _MicSource(info.device_index, cb)
        src.start()
        return src
    order = ["sck", "tap"] if backend == "sck" else ["tap", "sck"]
    if not fallback:
        order = order[:1]
    errors = []
    for name in order:
        try:
            if name == "tap":
                src = _TapSource(cb, process_objects_for(info.pid) if info.kind == "process" else None)
            else:
                src = _SCKAudioSource(info, cb)
            src.start()
            return src
        except Exception as e:  # noqa: BLE001
            log.exception("backend %s", name)
            errors.append(f"{'Core Audio' if name == 'tap' else 'ScreenCaptureKit'}: {e}")
    what = "aplikacji" if info.kind == "process" else "systemu"
    raise RuntimeError(f"Nie udało się przechwycić dźwięku {what}.\n" + "\n".join(errors) +
                       "\n\nSprawdź zgody w Ustawieniach systemowych → Prywatność i ochrona → Nagrywanie ekranu "
                       "i dźwięku systemu." + ("\nMożesz też spróbować opcji „Cały dźwięk systemowy”."
                                               if info.kind == "process" else ""))


def probe_system_audio(seconds: float = 0.6) -> None:
    """Na chwilę włącza tap całego systemu – macOS pokazuje wtedy prośbę o zgodę (przycisk „Zezwól”)."""
    src = _TapSource(lambda _a, _r: None, None)
    src.start()
    try:
        time.sleep(seconds)
    finally:
        src.stop()


def play_file(path: str) -> None:
    import subprocess
    subprocess.run(["/usr/bin/afplay", path], check=False, timeout=60)


# ---------------------------------------------------------------------------
class LevelMonitor:
    """Poziom na żywo dla wybranego źródła (otwiera je naprawdę – macOS nie ma mierników bez nagrywania)
    i wykrywanie aplikacji, które zaczęły grać. Źródło mierzy się tylko, gdy jest już zgoda – sam podgląd listy
    nie wywołuje próśb systemu."""

    def __init__(self):
        self.levels: dict[str, float] = {}
        self.new_playing: set[int] = set()
        self.measuring = ""
        self._known: set[int] = set()
        self._sel = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def set_known(self, pids):
        self._known = set(pids)
        self.new_playing = set()

    def set_source(self, info):
        self._sel = info

    def set_mic(self, _device_index: int):      # zgodność z wersją Windows
        pass

    def measurable(self, info, current) -> bool:
        from .audio_capture import source_key
        return self.running and info is current and self.measuring == source_key(info)

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
            self._thread.join(2.0)
        self._thread = None
        self.levels = {}
        self.measuring = ""

    @staticmethod
    def _allowed(info) -> bool:
        from . import mac_permissions as mp
        return mp.status(mp.MIC if info.kind == "mic" else mp.AUDIO) == mp.GRANTED

    def _run(self, stop: threading.Event):
        from .audio_capture import source_key
        own = os.getpid()
        src, src_info, peak = None, None, [0.0]
        blocked = False                 # wybrane źródło czeka na zgodę – sprawdzaj ponownie co 1,5 s
        was_playing: dict[int, bool] = {}
        next_scan = 0.0

        def on_audio(arr, _rate):
            if arr.size:
                peak[0] = max(peak[0], float(np.abs(arr).max()))

        try:
            while not stop.is_set():
                now = time.monotonic()
                if now >= next_scan:            # aplikacje, które zaczęły grać – co 1,5 s
                    playing: dict[int, bool] = {}
                    for _o, pid, running in audio_processes():
                        root = _root_pid(pid)
                        if root != own:
                            playing[root] = playing.get(root, False) or running
                    for root, on in playing.items():
                        if on and not was_playing.get(root, False) and was_playing:
                            self.new_playing.add(root)
                    was_playing = playing
                    next_scan = now + 1.5
                    if blocked:
                        src_info = None
                sel = self._sel
                if sel is not src_info:          # zmiana wybranego źródła
                    if src is not None:
                        try:
                            src.stop()
                        except Exception:  # noqa: BLE001
                            log.exception("LevelMonitor: zamykanie")
                        src = None
                    src_info, self.measuring = sel, ""
                    blocked = sel is not None and not self._allowed(sel)
                    if sel is not None and not blocked:
                        try:
                            src = open_source(sel, on_audio, "tap", fallback=False)
                            self.measuring = source_key(sel)
                        except Exception:  # noqa: BLE001
                            log.info("LevelMonitor: nie da się zmierzyć %s", sel.label, exc_info=True)
                if src is not None:
                    self.levels = {self.measuring: peak[0]}
                    peak[0] = 0.0
                else:
                    self.levels = {}
                stop.wait(0.06)
        finally:
            if src is not None:
                try:
                    src.stop()
                except Exception:  # noqa: BLE001
                    log.exception("LevelMonitor: zamykanie")
