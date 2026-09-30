"""Zrzuty ekranu: cały monitor (mss) albo pojedyncze okno (PrintWindow – działa też, gdy okno jest zasłonięte)."""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np

IS_WIN = sys.platform == "win32"


@dataclass
class VideoSourceInfo:
    kind: str           # "monitor" / "window" / "none"
    label: str
    index: int = 0      # numer monitora (1..n) w mss
    hwnd: int = 0
    pid: int = 0
    title: str = ""


def list_monitors() -> list[VideoSourceInfo]:
    out = []
    try:
        import mss
        with mss.mss() as sct:
            for i, m in enumerate(sct.monitors[1:], start=1):
                out.append(VideoSourceInfo("monitor", f"🖥 Monitor {i}  ({m['width']}×{m['height']})", index=i))
    except Exception:
        pass
    return out


def list_windows() -> list[VideoSourceInfo]:
    if not IS_WIN:
        return []
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    own_pid = os.getpid()
    result: list[VideoSourceInfo] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x80

    user32.GetWindowLongW.restype = ctypes.c_long

    def cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            cloaked = ctypes.c_int(0)
            dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if cloaked.value:
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if (rect.right - rect.left) < 200 or (rect.bottom - rect.top) < 150:
                if not user32.IsIconic(hwnd):
                    return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own_pid:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if title in ("Program Manager", "Settings", "Ustawienia"):
                return True
            short = title if len(title) < 70 else title[:67] + "…"
            result.append(VideoSourceInfo("window", f"🪟 {short}", hwnd=int(hwnd), pid=pid.value, title=title))
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return result


# ---------------------------------------------------------------------------
class MonitorGrabber:
    def __init__(self, index: int):
        self.index = index
        self._sct = None

    def grab(self) -> Optional[np.ndarray]:
        import mss
        if self._sct is None:            # mss musi być utworzone w wątku, który go używa
            self._sct = mss.mss()
        mons = self._sct.monitors
        mon = mons[self.index] if self.index < len(mons) else mons[1]
        img = np.asarray(self._sct.grab(mon))   # BGRA
        return img[:, :, :3].copy()

    def close(self):
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


class WindowGrabber:
    """PrintWindow(PW_RENDERFULLCONTENT) – przechwytuje okno nawet zasłonięte innym (nie zminimalizowane)."""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.last_error = ""

    def is_minimized(self) -> bool:
        return bool(ctypes.windll.user32.IsIconic(self.hwnd))

    def exists(self) -> bool:
        return bool(ctypes.windll.user32.IsWindow(self.hwnd))

    def grab(self) -> Optional[np.ndarray]:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        if not self.exists():
            self.last_error = "Okno zostało zamknięte"
            return None
        if self.is_minimized():
            self.last_error = "Okno jest zminimalizowane"
            return None
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        user32.GetWindowDC.restype = wintypes.HDC
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        hwnd_dc = user32.GetWindowDC(wintypes.HWND(self.hwnd))
        mem_dc = gdi32.CreateCompatibleDC(wintypes.HDC(hwnd_dc))
        bmp = gdi32.CreateCompatibleBitmap(wintypes.HDC(hwnd_dc), w, h)
        old = gdi32.SelectObject(wintypes.HDC(mem_dc), wintypes.HGDIOBJ(bmp))
        try:
            ok = user32.PrintWindow(wintypes.HWND(self.hwnd), wintypes.HDC(mem_dc), 2)  # PW_RENDERFULLCONTENT
            if not ok:
                self.last_error = "PrintWindow nie powiodło się"
                return None

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                            ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                            ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                            ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = w
            bmi.biHeight = -h  # top-down
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            buf = (ctypes.c_ubyte * (w * h * 4))()
            gdi32.GetDIBits(wintypes.HDC(mem_dc), wintypes.HBITMAP(bmp), 0, h, buf, ctypes.byref(bmi), 0)
            img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3].copy()
            self.last_error = ""
            return img
        finally:
            gdi32.SelectObject(wintypes.HDC(mem_dc), wintypes.HGDIOBJ(old))
            gdi32.DeleteObject(wintypes.HGDIOBJ(bmp))
            gdi32.DeleteDC(wintypes.HDC(mem_dc))
            user32.ReleaseDC(wintypes.HWND(self.hwnd), wintypes.HDC(hwnd_dc))

    def close(self):
        pass


def make_grabber(info: VideoSourceInfo):
    if info.kind == "monitor":
        return MonitorGrabber(info.index)
    if info.kind == "window":
        return WindowGrabber(info.hwnd)
    return None


def crop_roi(img: np.ndarray, roi: Optional[tuple]) -> np.ndarray:
    """roi = (x, y, w, h) jako ułamki 0..1 rozmiaru obrazu."""
    if img is None or not roi:
        return img
    H, W = img.shape[:2]
    x, y, w, h = roi
    x0, y0 = int(max(0, x) * W), int(max(0, y) * H)
    x1, y1 = int(min(1, x + w) * W), int(min(1, y + h) * H)
    if x1 - x0 < 20 or y1 - y0 < 20:
        return img
    return img[y0:y1, x0:x1].copy()
