"""Opisy slajdów lokalnym modelem, który widzi obrazy (np. Qwen3-VL w Ollamie).

Dla każdego slajdu model odczytuje tekst (także wzory, w LaTeX) i opisuje elementy graficzne: zdjęcia, schematy,
wykresy, tabele. Wynik trafia do slides.json (pole "vision") i jest liczony tylko raz na slajd i model."""
from __future__ import annotations

import base64
import logging
import re
import threading
from typing import Callable, Optional

from .storage import Lecture

log = logging.getLogger(__name__)
MAX_SIDE = 1280

_KIND_KEYS = ("rodzaj", "kind", "type", "typ")
_DESC_KEYS = ("opis", "description", "desc", "text")
_TEXT_KEYS = ("tekst", "text", "content", "tresc", "treść")
_LIST_KEYS = ("elementy", "elements", "items", "obrazy", "images")
_SKIP = re.compile(r"\b(logo|tło|background|dekoracj|decorat|watermark|znak wodny)\b", re.IGNORECASE)


def encode_image(path) -> Optional[str]:
    """Slajd → JPEG w base64 (zmniejszony, żeby model działał szybko)."""
    import cv2
    import numpy as np
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        img = None
    if img is None:
        return None
    h, w = img.shape[:2]
    s = MAX_SIDE / max(h, w)
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None


def parse_vision(raw: str) -> dict:
    """Odpowiedź modelu → {"text": str, "items": [{"kind": str, "desc": str}]} (odporne na różne klucze)."""
    from .notes_pipeline import _json_any
    data = _json_any(raw)
    if not isinstance(data, dict):
        return {"text": "", "items": []}
    low = {str(k).lower(): v for k, v in data.items()}
    text = next((str(low[k]).strip() for k in _TEXT_KEYS if isinstance(low.get(k), str)), "")
    items_raw = next((low[k] for k in _LIST_KEYS if isinstance(low.get(k), list)), [])
    items = []
    for it in items_raw:
        if isinstance(it, str):
            kind, desc = "", it
        elif isinstance(it, dict):
            li = {str(k).lower(): v for k, v in it.items()}
            kind = next((str(li[k]).strip() for k in _KIND_KEYS if li.get(k)), "")
            desc = next((str(li[k]).strip() for k in _DESC_KEYS if li.get(k)), "")
        else:
            continue
        kind = kind.split("|")[0].strip(" .").lower()
        if len(desc) < 8 or _SKIP.search(kind) or (_SKIP.search(desc) and len(desc) < 80):
            continue
        items.append({"kind": kind, "desc": desc})
    return {"text": text, "items": items[:6]}


def describe_slide(llm, model: str, path, lang: str = "pl", subject: str = "", cancel=None,
                   keep_alive: str = "5m", src: str = "") -> Optional[dict]:
    from .prompts import texts
    b64 = encode_image(path)
    if not b64:
        return None
    subj = f" ({subject})" if subject else ""
    prompt = texts(lang, src).vision.format(subject=subj)
    raw = llm.chat(model, [{"role": "user", "content": prompt, "images": [b64]}], num_ctx=8192, temperature=0.1,
                   json_mode=True, cancel=cancel, keep_alive=keep_alive)
    return parse_vision(raw)


def describe_slides(lecture: Lecture, llm, model: str, lang: str = "pl",
                    progress: Optional[Callable[[str, float], None]] = None,
                    cancel: Optional[threading.Event] = None, src: str = "") -> int:
    """Opisuje wszystkie slajdy wykładu, których jeszcze nie opisano tym modelem w tym języku (lang – język notatek,
    src – język wykładu). Zwraca liczbę nowych opisów."""
    data = lecture.load_slides()
    slides = data.get("slides", [])

    def stale(v: dict) -> bool:          # starsze opisy nie mają „lang” – powstały w języku wykładu
        return v.get("model") != model or v.get("lang", src or lang) != lang
    todo = [s for s in slides if stale(s.get("vision") or {}) and s.get("file")]
    done = 0
    for k, sl in enumerate(todo, 1):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(f"Opisywanie slajdów: {k}/{len(todo)}", (k - 1) / max(1, len(todo)))
        path = lecture.folder / sl["file"]
        if not path.exists():
            continue
        try:
            res = describe_slide(llm, model, path, lang, lecture.meta.subject, cancel, src=src)
        except Exception as e:  # noqa: BLE001
            from .llm import Cancelled
            if isinstance(e, Cancelled):
                raise
            log.warning("opis slajdu %s: %s", sl.get("index"), e)
            if k == 1:
                raise          # model nie działa (np. brak obsługi obrazów) – nie próbuj dalej
            continue
        if res is None:
            continue
        sl["vision"] = {"model": model, "lang": lang, **res}
        done += 1
        if done % 4 == 0:
            lecture.save_slides(data)
    if done:
        lecture.save_slides(data)
    llm.unload(model)          # zwolnij kartę graficzną dla modelu notatek
    return done


def slide_text(sl: dict) -> str:
    """Najlepszy dostępny tekst slajdu: odczyt modelu (ze wzorami) albo OCR."""
    v = sl.get("vision") or {}
    t = (v.get("text") or "").strip()
    ocr = (sl.get("ocr") or "").strip()
    return t if len(t) >= max(10, len(ocr) * 0.5) else (ocr or t)


def slide_items(sl: dict) -> list[dict]:
    return list((sl.get("vision") or {}).get("items") or [])
