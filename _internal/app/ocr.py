"""OCR slajdów wbudowanym silnikiem Windows (Windows.Media.Ocr). Opcjonalny – gdy brak, zwraca pusty tekst."""
from __future__ import annotations

import asyncio
import logging
import threading

import numpy as np

log = logging.getLogger(__name__)
_engine = None
_failed = False


def _get_engine():
    global _engine, _failed
    if _engine is not None or _failed:
        return _engine
    try:
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        for lang in ("pl", "pl-PL"):
            try:
                if OcrEngine.is_language_supported(Language(lang)):
                    _engine = OcrEngine.try_create_from_language(Language(lang))
                    break
            except Exception:
                pass
        if _engine is None:
            _engine = OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            _failed = True
    except Exception:
        log.info("Windows OCR niedostępny", exc_info=True)
        _failed = True
    return _engine


async def _await(x):
    return await x


_tls = threading.local()


def _com_init():
    """WinRT wymaga zainicjalizowanego COM w wątku, który z niego korzysta."""
    if getattr(_tls, "ok", False):
        return
    try:
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    except Exception:
        pass
    _tls.ok = True


def ocr_image(img_bgr: np.ndarray) -> str:
    _com_init()
    engine = _get_engine()
    if engine is None or img_bgr is None:
        return ""
    try:
        import cv2
        from winrt.windows.storage.streams import DataWriter
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        h, w = img_bgr.shape[:2]
        # małe slajdy powiększ – OCR lepiej czyta większy tekst
        if w < 1400:
            scale = 1400 / w
            img_bgr = cv2.resize(img_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
        writer = DataWriter()
        writer.write_bytes(rgba.tobytes())
        sb = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.RGBA8,
                                                    rgba.shape[1], rgba.shape[0])
        result = asyncio.run(_await(engine.recognize_async(sb)))
        return "\n".join(line.text for line in result.lines).strip()
    except Exception:
        log.info("OCR błąd", exc_info=True)
        return ""
