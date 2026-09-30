"""Przechwytywanie dźwięku JEDNEGO procesu (i jego procesów potomnych) na Windows 10 2004+/11.

Czysta implementacja przez ctypes/comtypes (API: ActivateAudioInterfaceAsync +
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK). Używana jako zapasowa, gdy
biblioteka `proc-tap` nie jest dostępna.

Zwraca bloki float32 o kształcie (n, 2) z częstotliwością `self.sample_rate`.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import POINTER, Structure, byref, c_int, c_int64, c_long, c_ubyte, c_uint32, c_uint64, c_ushort, c_void_p, wintypes
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)

import comtypes  # noqa: E402
from comtypes import COMMETHOD, COMObject, GUID, HRESULT, IUnknown  # noqa: E402

VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
VT_BLOB = 65

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
WAVE_FORMAT_PCM = 1


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(Structure):
    _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_int)]


class AUDIOCLIENT_ACTIVATION_PARAMS(Structure):
    _fields_ = [("ActivationType", c_int), ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS)]


class BLOB(Structure):
    _fields_ = [("cbSize", wintypes.ULONG), ("pBlobData", c_void_p)]


class PROPVARIANT(Structure):
    _fields_ = [("vt", c_ushort), ("wReserved1", c_ushort), ("wReserved2", c_ushort),
                ("wReserved3", c_ushort), ("blob", BLOB)]


class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetActivateResult",
                  (["out"], POINTER(c_long), "activateResult"),
                  (["out"], POINTER(POINTER(IUnknown)), "activatedInterface")),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ActivateCompleted",
                  (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation")),
    ]


class IAgileObject(IUnknown):
    _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
    _methods_ = []


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["out"], POINTER(POINTER(c_ubyte)), "ppData"),
                  (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                  (["out"], POINTER(wintypes.DWORD), "pdwFlags"),
                  (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                  (["out"], POINTER(c_uint64), "pu64QPCPosition")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
    ]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize",
                  (["in"], c_int, "ShareMode"), (["in"], wintypes.DWORD, "StreamFlags"),
                  (["in"], c_int64, "hnsBufferDuration"), (["in"], c_int64, "hnsPeriodicity"),
                  (["in"], POINTER(WAVEFORMATEX), "pFormat"), (["in"], POINTER(GUID), "AudioSessionGuid")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "pNumBufferFrames")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_int64), "phnsLatency")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "pNumPaddingFrames")),
        COMMETHOD([], HRESULT, "IsFormatSupported",
                  (["in"], c_int, "ShareMode"), (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                  (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch")),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
        COMMETHOD([], HRESULT, "GetDevicePeriod",
                  (["out"], POINTER(c_int64), "phnsDefaultDevicePeriod"),
                  (["out"], POINTER(c_int64), "phnsMinimumDevicePeriod")),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE, "eventHandle")),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "riid"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppv")),
    ]


class _CompletionHandler(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self):
        super().__init__()
        self.done = threading.Event()

    def ActivateCompleted(self, activateOperation):  # noqa: N802 (nazwa z COM)
        self.done.set()
        return 0


def _activate(pid: int) -> POINTER(IAudioClient):
    mmdevapi = ctypes.WinDLL("Mmdevapi.dll")
    fn = mmdevapi.ActivateAudioInterfaceAsync
    fn.argtypes = [wintypes.LPCWSTR, POINTER(GUID), POINTER(PROPVARIANT),
                   POINTER(IActivateAudioInterfaceCompletionHandler),
                   POINTER(POINTER(IActivateAudioInterfaceAsyncOperation))]
    fn.restype = HRESULT

    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE

    pv = PROPVARIANT()
    pv.vt = VT_BLOB
    pv.blob.cbSize = ctypes.sizeof(params)
    pv.blob.pBlobData = ctypes.cast(ctypes.pointer(params), c_void_p)

    handler = _CompletionHandler()
    handler_ptr = handler.QueryInterface(IActivateAudioInterfaceCompletionHandler)
    op = POINTER(IActivateAudioInterfaceAsyncOperation)()
    iid = IAudioClient._iid_
    fn(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, byref(iid), byref(pv), handler_ptr, byref(op))
    if not handler.done.wait(10):
        raise RuntimeError("Przekroczono czas aktywacji przechwytywania dźwięku procesu")
    hr, unk = op.GetActivateResult()
    if hr < 0:
        raise OSError(f"Aktywacja przechwytywania nie powiodła się (HRESULT 0x{hr & 0xFFFFFFFF:08X}). "
                      "Wymagany Windows 10 w wersji 2004 lub nowszej.")
    return unk.QueryInterface(IAudioClient)


class NativeProcessLoopback:
    """Przechwytuje dźwięk procesu `pid` w osobnym wątku i wywołuje on_data(np.ndarray (n,2) float32)."""

    def __init__(self, pid: int, on_data: Callable[[np.ndarray], None]):
        self.pid = pid
        self.on_data = on_data
        self.sample_rate = 48000
        self.channels = 2
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ProcessLoopback", daemon=True)
        self._thread.start()
        self._ready.wait(12)
        if self._error:
            raise self._error

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(3)

    def _run(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        client = cap = unk = None
        event = None
        try:
            client = _activate(self.pid)
            fmt = None
            last_exc = None
            flags = (AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
                     AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
            for rate in (48000, 44100):
                f = WAVEFORMATEX(WAVE_FORMAT_PCM, 2, rate, rate * 4, 4, 16, 0)
                try:
                    client.Initialize(AUDCLNT_SHAREMODE_SHARED, flags, 2_000_000, 0, byref(f), None)
                    fmt = f
                    break
                except Exception as e:  # spróbuj innej częstotliwości (wymaga nowego klienta)
                    last_exc = e
                    client = _activate(self.pid)
            if fmt is None:
                raise OSError(f"Nie udało się zainicjalizować przechwytywania: {last_exc}")
            self.sample_rate = fmt.nSamplesPerSec
            event = kernel32.CreateEventW(None, False, False, None)
            client.SetEventHandle(event)
            unk = client.GetService(byref(IAudioCaptureClient._iid_))
            cap = unk.QueryInterface(IAudioCaptureClient)
            client.Start()
            self._ready.set()
            block = fmt.nBlockAlign
            while not self._stop.is_set():
                kernel32.WaitForSingleObject(event, 100)
                while True:
                    n = cap.GetNextPacketSize()
                    if not n:
                        break
                    data, frames, bflags, _, _ = cap.GetBuffer()
                    if frames:
                        if bflags & AUDCLNT_BUFFERFLAGS_SILENT:
                            arr = np.zeros((frames, 2), dtype=np.float32)
                        else:
                            raw = ctypes.string_at(data, frames * block)
                            arr = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0
                        try:
                            self.on_data(arr)
                        except Exception:
                            log.exception("on_data")
                    cap.ReleaseBuffer(frames)
            client.Stop()
        except BaseException as e:  # noqa: BLE001
            log.exception("NativeProcessLoopback")
            self._error = e
            self._ready.set()
        finally:
            if event:
                kernel32.CloseHandle(event)
            client = cap = unk = None  # zwolnij obiekty COM przed CoUninitialize
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
