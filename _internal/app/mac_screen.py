"""Zrzuty ekranu na macOS: ScreenCaptureKit (ekran albo pojedyncze okno – także zasłonięte), zapas: mss.
Nowe w wersji 2.2.0.

Lista ekranów nie wymaga zgody (CGGetActiveDisplayList), lista okien i zrzuty – tak („Nagrywanie ekranu”).
Bez zgody nie wołamy ScreenCaptureKit, żeby sam podgląd ekranu nagrywania nie wywoływał prośby systemu."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

MAX_SIDE = 2880                 # dłuższy bok zrzutu w pikselach – więcej nie pomaga ani OCR, ani wykrywaniu slajdów
SKIP_BUNDLES = {"com.apple.dock", "com.apple.WindowManager", "com.apple.controlcenter",
                "com.apple.notificationcenterui", "com.apple.Spotlight", "com.apple.systemuiserver"}
NO_PERMISSION = "Brak zgody na nagrywanie ekranu – zezwól w Ustawieniach systemowych i uruchom Wykłady ponownie"


def _allowed() -> bool:
    from . import mac_permissions as mp
    return mp.status(mp.SCREEN) == mp.GRANTED


def _wait(call, timeout: float = 5.0):
    ev = threading.Event()
    box: list = []

    def handler(*args):
        box.append(args)
        ev.set()
    call(handler)
    if not ev.wait(timeout):
        raise TimeoutError("ScreenCaptureKit nie odpowiedział")
    return box[0]


def _content(on_screen_only: bool = True):
    from ScreenCaptureKit import SCShareableContent
    content, err = _wait(lambda h: SCShareableContent
                         .getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
                             True, on_screen_only, h))
    if content is None:
        raise RuntimeError(str(err.localizedDescription()) if err is not None else "brak listy okien")
    return content


# ---------------------------------------------------------------------------
def _display_ids() -> list[int]:
    import Quartz
    err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
    return [int(x) for x in (ids or [])[:count]] if not err else []


def _screen_names() -> dict[int, str]:
    try:
        from AppKit import NSScreen
        return {int(s.deviceDescription()["NSScreenNumber"]): str(s.localizedName()) for s in NSScreen.screens()}
    except Exception:  # noqa: BLE001
        return {}


def list_monitors():
    from .screen_capture import VideoSourceInfo
    out = []
    try:
        import Quartz
        names = _screen_names()
        for i, did in enumerate(_display_ids(), start=1):
            b = Quartz.CGDisplayBounds(did)
            name = names.get(did, "")
            label = f"🖥 Monitor {i}" + (f" – {name}" if name else "") + f"  ({int(b.size.width)}×{int(b.size.height)})"
            out.append(VideoSourceInfo("monitor", label, index=i, display_id=did))
    except Exception:  # noqa: BLE001
        log.exception("lista ekranów")
    return out


def list_windows():
    from .screen_capture import VideoSourceInfo
    if not _allowed():
        return []
    out = []
    try:
        own = os.getpid()
        for w in _content(True).windows() or []:
            app = w.owningApplication()
            if app is None or int(app.processID()) == own or str(app.bundleIdentifier() or "") in SKIP_BUNDLES:
                continue
            title = str(w.title() or "")
            f = w.frame()
            if not title or int(w.windowLayer()) != 0 or f.size.width < 200 or f.size.height < 150:
                continue
            app_name = str(app.applicationName() or "")
            full = f"{app_name} – {title}" if app_name and app_name not in title else title
            short = full if len(full) < 70 else full[:67] + "…"
            out.append(VideoSourceInfo("window", f"🪟 {short}", hwnd=int(w.windowID()), pid=int(app.processID()),
                                       title=full))
    except Exception:  # noqa: BLE001
        log.exception("lista okien")
    return out


# ---------------------------------------------------------------------------
def _cgimage_to_bgr(img) -> Optional[np.ndarray]:
    import Quartz
    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    if not w or not h or Quartz.CGImageGetBitsPerPixel(img) != 32:
        return None
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    arr = np.frombuffer(bytes(data), dtype=np.uint8)[: h * bpr].reshape(h, bpr)[:, : w * 4].reshape(h, w, 4)
    info = int(Quartz.CGImageGetBitmapInfo(img))
    little = (info & 0x7000) == 0x2000              # kCGBitmapByteOrder32Little → w pamięci B, G, R, A
    alpha = int(Quartz.CGImageGetAlphaInfo(img))
    alpha_first = alpha in (2, 4, 6)                # PremultipliedFirst, First, NoneSkipFirst
    if little:
        bgr = arr[:, :, 0:3] if alpha_first else arr[:, :, 1:4]          # BGRA / ABGR
    else:
        rgb = arr[:, :, 1:4] if alpha_first else arr[:, :, 0:3]          # ARGB / RGBA
        bgr = rgb[:, :, ::-1]
    return np.ascontiguousarray(bgr)


class SCKGrabber:
    """Zrzut ekranu albo okna przez SCScreenshotManager (macOS 14+). Okno łapie się nawet zasłonięte.
    Własne okna Wykładów nie trafiają do zrzutu całego ekranu."""

    REFRESH_S = 4.0         # co tyle sekund odśwież filtr (okno mogło zmienić rozmiar albo ekran)

    def __init__(self, info):
        self.info = info
        self.last_error = ""
        self._filter = None
        self._size = (0, 0)
        self._at = 0.0
        self._mss = None
        self._sck_failed = 0

    def _build(self):
        from ScreenCaptureKit import SCContentFilter, SCShareableContent
        content = _content(on_screen_only=False)
        if self.info.kind == "window":
            win = next((w for w in content.windows() or [] if int(w.windowID()) == self.info.hwnd), None)
            if win is None:
                self._filter = None
                self.last_error = "Okno zostało zamknięte"
                return False
            flt = SCContentFilter.alloc().initWithDesktopIndependentWindow_(win)
            rect = win.frame()
        else:
            disp = next((d for d in content.displays() or [] if int(d.displayID()) == self.info.display_id), None)
            if disp is None:
                self._filter = None
                self.last_error = "Ekran został odłączony"
                return False
            own = [a for a in content.applications() or [] if int(a.processID()) == os.getpid()]
            flt = SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(disp, own, [])
            rect = disp.frame()
        scale = 2.0
        try:
            fi = SCShareableContent.infoForFilter_(flt)
            scale = float(fi.pointPixelScale()) or scale
            rect = fi.contentRect()
        except Exception:  # noqa: BLE001
            pass
        w, h = rect.size.width * scale, rect.size.height * scale
        k = min(1.0, MAX_SIDE / max(w, h, 1))
        self._size = (max(2, int(w * k)), max(2, int(h * k)))
        self._filter = flt
        self._at = time.monotonic()
        return True

    def _grab_sck(self) -> Optional[np.ndarray]:
        from ScreenCaptureKit import SCScreenshotManager, SCStreamConfiguration
        if self._filter is None or time.monotonic() - self._at > self.REFRESH_S:
            if not self._build():
                return None
        cfg = SCStreamConfiguration.alloc().init()
        cfg.setWidth_(self._size[0])
        cfg.setHeight_(self._size[1])
        cfg.setShowsCursor_(False)
        try:
            cfg.setIgnoreShadowsSingleWindow_(True)
        except Exception:  # noqa: BLE001
            pass
        img, err = _wait(lambda h: SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            self._filter, cfg, h))
        if img is None:
            self._filter = None              # następnym razem zbuduj filtr od nowa
            if self.info.kind == "window":
                self.last_error = "Okno jest zminimalizowane albo niedostępne"
                return None
            raise RuntimeError(str(err.localizedDescription()) if err is not None else "pusty zrzut")
        out = _cgimage_to_bgr(img)
        if out is not None:
            self.last_error = ""
        return out

    def _grab_mss(self) -> Optional[np.ndarray]:
        import mss
        if self._mss is None:
            self._mss = mss.mss()
        mons = self._mss.monitors
        mon = mons[self.info.index] if self.info.index < len(mons) else mons[1]
        img = np.asarray(self._mss.grab(mon))
        self.last_error = ""
        return img[:, :, :3].copy()

    def grab(self) -> Optional[np.ndarray]:
        if not _allowed():
            self.last_error = NO_PERMISSION
            return None
        if self.info.kind == "window" or self._sck_failed < 3:      # cały ekran: po 3 błędach już tylko mss
            try:
                img = self._grab_sck()
                self._sck_failed = 0
                return img
            except Exception as e:  # noqa: BLE001
                self._sck_failed += 1
                log.warning("ScreenCaptureKit: %s", e)
                if self.info.kind == "window":
                    self.last_error = f"Nie udało się złapać okna: {e}"
                    return None
        if self.info.kind == "monitor":       # zapas dla całego ekranu
            try:
                return self._grab_mss()
            except Exception as e:  # noqa: BLE001
                self.last_error = f"Nie udało się zrobić zrzutu ekranu: {e}"
        return None

    def close(self):
        self._filter = None
        if self._mss is not None:
            try:
                self._mss.close()
            except Exception:  # noqa: BLE001
                pass
            self._mss = None
