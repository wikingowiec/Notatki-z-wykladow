"""Zdjęcia slajdów (np. z telefonu): wczytanie (JPG/PNG/HEIC), obrót wg EXIF, wyprostowanie slajdu,
czas zrobienia zdjęcia i dopasowanie do nagrania."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".bmp", ".tif", ".tiff")
MAX_SIDE = 2560

try:
    import pillow_heif
    pillow_heif.register_heif_opener()      # zdjęcia z iPhone'a (HEIC)
except Exception:  # noqa: BLE001
    pass


def load_photo(path: Path) -> tuple[Optional[np.ndarray], Optional[datetime]]:
    """Zwraca (obraz BGR obrócony wg EXIF, czas zrobienia zdjęcia jako datetime ze strefą)."""
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as im:
            taken = _exif_time(im)
            im = ImageOps.exif_transpose(im).convert("RGB")
            w, h = im.size
            s = MAX_SIDE / max(w, h)
            if s < 1:
                im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
            arr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    except Exception as e:  # noqa: BLE001
        log.warning("zdjęcie %s: %s", path, e)
        return None, None
    return arr, taken


def _exif_time(im) -> Optional[datetime]:
    try:
        exif = im.getexif()
        sub = exif.get_ifd(0x8769)
        raw = sub.get(36867) or sub.get(36868) or exif.get(306)     # DateTimeOriginal / Digitized / DateTime
        if not raw:
            return None
        dt = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
        off = sub.get(36881) or sub.get(36880)                       # OffsetTimeOriginal
        if off:
            sign = 1 if str(off)[0] != "-" else -1
            hh, mm = str(off)[1:].split(":")
            from datetime import timedelta
            return dt.replace(tzinfo=timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
        return dt.astimezone()          # bez strefy – czas lokalny komputera
    except Exception:  # noqa: BLE001
        return None


def straighten(img: np.ndarray) -> np.ndarray:
    """Szuka dużego czworokąta (ekran/tablica/slajd) i prostuje perspektywę. Gdy nie jest pewne – bez zmian."""
    h, w = img.shape[:2]
    scale = 900 / max(h, w)
    small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1 else img.copy()
    scale = min(1.0, scale)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_img = small.shape[0] * small.shape[1]
    best = None
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            a = cv2.contourArea(approx)
            if 0.25 * area_img < a < 0.98 * area_img:
                best = approx.reshape(4, 2).astype(np.float32) / scale
                break
    if best is None:
        return img
    # uporządkuj rogi: lewy-górny, prawy-górny, prawy-dolny, lewy-dolny
    s = best.sum(axis=1)
    d = np.diff(best, axis=1).ravel()
    tl, br = best[np.argmin(s)], best[np.argmax(s)]
    tr, bl = best[np.argmin(d)], best[np.argmax(d)]
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if width < 200 or height < 120:
        return img
    ratio = width / height
    if not 0.9 < ratio < 2.6:          # slajdy są poziome (4:3 – 16:9) – inaczej nie ryzykujemy
        return img
    M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]),
                                    np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                                             dtype=np.float32))
    return cv2.warpPerspective(img, M, (width, height))


def audio_start_time(path: Path, duration: float) -> tuple[Optional[datetime], Optional[datetime]]:
    """Czas utworzenia nagrania z metadanych pliku (Dyktafon iPhone zapisuje go w m4a).
    Zwraca (początek, koniec) – nie wiadomo, czy zapisany czas to początek czy koniec, więc oba warianty."""
    t = None
    try:
        import av
        with av.open(str(path)) as c:
            md = dict(c.metadata or {})
            for k in ("com.apple.quicktime.creationdate", "creation_time", "date"):
                if md.get(k):
                    t = md[k]
                    break
    except Exception:  # noqa: BLE001
        pass
    if not t:
        return None, None
    try:
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None, None
    from datetime import timedelta
    return dt, dt - timedelta(seconds=duration)


def time_on_axis(taken: Optional[datetime], parts: list[dict]) -> Optional[float]:
    """Czas zdjęcia → sekunda na osi wykładu (jeśli zdjęcie zrobiono w trakcie którejś części nagrania)."""
    if taken is None:
        return None
    for p in parts:
        for key in ("recorded_at", "recorded_at_alt"):
            iso = p.get(key)
            if not iso:
                continue
            start = datetime.fromisoformat(iso)
            dt = (taken - start).total_seconds()
            if -30 <= dt <= p.get("duration", 0) + 30:
                return float(p.get("offset", 0)) + max(0.0, min(dt, p.get("duration", 0)))
    return None
