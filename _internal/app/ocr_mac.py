"""OCR slajdów na Macu: Apple Vision (VNRecognizeTextRequest) przez pyobjc. Gdy brak – pusty tekst.
Nowe w wersji 2.2.0.

Polski jest w Vision od nowszych wersji macOS – jeśli system go nie zna, rozpoznawanie idzie po angielsku
(litery bez ogonków mogą wtedy wypaść gorzej)."""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)
WANTED = ["pl-PL", "en-US"]
_langs: list[str] | None = None
_failed = False


def _languages(req) -> list[str]:
    """Języki z WANTED, które zna ten macOS (pamiętane po pierwszym sprawdzeniu)."""
    global _langs
    if _langs is None:
        try:
            supported, _err = req.supportedRecognitionLanguagesAndReturnError_(None)
            supported = [str(x) for x in (supported or [])]
        except Exception:  # noqa: BLE001 – starszy macOS
            supported = []
        _langs = [x for x in WANTED if x in supported] or ["en-US"]
        log.info("Apple Vision OCR: języki %s (system zna: %s)", _langs, ", ".join(supported[:30]))
    return _langs


def ocr_image(img_bgr: np.ndarray) -> str:
    global _failed
    if _failed or img_bgr is None:
        return ""
    try:
        import objc
        import Vision
        from Foundation import NSData
    except Exception:  # noqa: BLE001
        log.info("Apple Vision niedostępne (brak pyobjc)", exc_info=True)
        _failed = True
        return ""
    try:
        import cv2
        h, w = img_bgr.shape[:2]
        if w < 1400:          # małe slajdy powiększ – drobny tekst czyta się lepiej
            scale = 1400 / w
            img_bgr = cv2.resize(img_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        ok, png = cv2.imencode(".png", img_bgr)
        if not ok:
            return ""
        raw = png.tobytes()
        with objc.autorelease_pool():
            data = NSData.dataWithBytes_length_(raw, len(raw))
            req = Vision.VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            req.setUsesLanguageCorrection_(True)
            req.setRecognitionLanguages_(_languages(req))
            handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
            done, err = handler.performRequests_error_([req], None)
            if not done:
                log.info("Apple Vision OCR: %s", err)
                return ""
            lines = []
            for obs in req.results() or []:
                cand = obs.topCandidates_(1)
                if not cand:
                    continue
                box = obs.boundingBox()          # współrzędne 0..1, początek w lewym dolnym rogu
                top = box.origin.y + box.size.height
                lines.append((-round(top * 60), box.origin.x, str(cand[0].string())))
        lines.sort()                             # z góry na dół, w wierszu od lewej
        return "\n".join(t for _, _, t in lines).strip()
    except Exception:  # noqa: BLE001
        log.info("OCR błąd (Apple Vision)", exc_info=True)
        return ""
