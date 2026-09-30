"""Przechowywanie wykładów: każdy wykład to osobny folder w bibliotece.

Struktura folderu:
    meta.json          - tytuł, przedmiot, data, czas trwania, status, części nagrania, język
    audio.opus         - nagranie (16 kHz mono, Opus); kolejne części: audio_02.opus … (starsze: audio.flac)
    marks.json         - zaznaczone fragmenty [{"start","end","kind"}]
    qa.json            - historia pytań do notatki
    transcript.jsonl   - segmenty transkrypcji {"start","end","text"} (sekundy od startu)
    slides/            - slide_001.png ...
    slides.json        - lista slajdów [{"index","file","t","ocr"}] i zdarzeń [{"t","index"}]
    notes.md           - notatki (Markdown)
    summary.md         - podsumowanie
    flashcards.json    - fiszki [{"q","a","known"}]
    notes.html         - eksport HTML
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional


def safe_name(text: str, max_len: int = 60) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().strip(".")
    text = re.sub(r"\s+", " ", text)
    return text[:max_len].strip() or "Wykład"


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@dataclass
class LectureMeta:
    title: str = ""
    subject: str = ""
    created: str = ""            # ISO
    duration: float = 0.0
    audio_source: str = ""
    video_source: str = ""
    status: str = "nowy"         # nagrywanie / nagrany / przetwarzanie / gotowy / błąd
    notes_model: str = ""
    error: str = ""
    parts: list = field(default_factory=list)   # [{"file","offset","duration"}] – kolejne części jednego wykładu
    language: str = ""           # język wykładu (wykryty przez Whisper), np. "pl", "en"
    edited: bool = False         # notatki poprawione ręcznie
    kind: str = "av"             # rodzaj notatki: av (dźwięk+slajdy) / audio / slides / files
    phone_pdf: str = ""          # gdzie leży PDF wysłany na telefon (folder chmury)


MARK_KINDS = {
    "important": "Ważne",
    "exam": "Na egzamin",
    "interesting": "Ciekawe",
    "unclear": "Niejasne",
}


class Lecture:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._lock = threading.Lock()
        self.meta = LectureMeta()
        self._load_meta()

    # --- tworzenie -------------------------------------------------------
    @classmethod
    def create(cls, library: Path, title: str, subject: str) -> "Lecture":
        now = datetime.now()
        title = title.strip() or f"Wykład {now:%d.%m.%Y %H:%M}"
        name = f"{now:%Y-%m-%d_%H-%M} {safe_name(title)}"
        folder = Path(library) / name
        i = 2
        while folder.exists():
            folder = Path(library) / f"{name} ({i})"
            i += 1
        (folder / "slides").mkdir(parents=True)
        lec = cls(folder)
        lec.meta = LectureMeta(title=title, subject=subject.strip(), created=now.isoformat(timespec="seconds"))
        lec.save_meta()
        return lec

    # --- ścieżki ---------------------------------------------------------
    @property
    def audio_path(self) -> Path:
        """Pierwsza część nagrania (zgodność wstecz)."""
        parts = self.audio_parts()
        return parts[0][0] if parts else self.folder / "audio.opus"

    def audio_parts(self) -> list[tuple[Path, float, float]]:
        """[(plik, początek na osi wykładu, długość)]. Starsze wykłady: jeden plik audio.flac/audio.opus."""
        out = []
        for p in self.meta.parts or []:
            f = self.folder / p["file"]
            if f.exists():
                out.append((f, float(p.get("offset", 0)), float(p.get("duration", 0))))
        if out:
            return out
        for name in ("audio.opus", "audio.flac"):
            f = self.folder / name
            if f.exists():
                return [(f, 0.0, float(self.meta.duration or 0))]
        return []

    def new_part_file(self) -> str:
        n = len(self.audio_parts())
        return "audio.opus" if n == 0 else f"audio_{n + 1:02d}.opus"

    def locate(self, t: float) -> tuple[Optional[Path], float]:
        """Czas na osi wykładu → (plik części, czas w tym pliku)."""
        parts = self.audio_parts()
        for f, off, dur in reversed(parts):
            if t >= off - 0.01:
                return f, max(0.0, t - off)
        return (parts[0][0], max(0.0, t)) if parts else (None, 0.0)

    @property
    def marks_path(self) -> Path: return self.folder / "marks.json"

    def load_marks(self) -> list[dict]:
        try:
            return json.loads(self.marks_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save_marks(self, marks: list[dict]) -> None:
        with self._lock:
            tmp = self.marks_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(marks, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.marks_path)
    @property
    def transcript_path(self) -> Path: return self.folder / "transcript.jsonl"
    @property
    def slides_dir(self) -> Path: return self.folder / "slides"
    @property
    def slides_json(self) -> Path: return self.folder / "slides.json"
    @property
    def notes_path(self) -> Path: return self.folder / "notes.md"
    @property
    def summary_path(self) -> Path: return self.folder / "summary.md"
    @property
    def flashcards_path(self) -> Path: return self.folder / "flashcards.json"
    @property
    def html_path(self) -> Path: return self.folder / "notes.html"

    # --- meta ------------------------------------------------------------
    def _load_meta(self) -> None:
        p = self.folder / "meta.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                m = LectureMeta()
                for k, v in data.items():
                    if hasattr(m, k):
                        setattr(m, k, v)
                self.meta = m
            except Exception:
                pass
        if not self.meta.title:
            self.meta.title = self.folder.name

    def save_meta(self) -> None:
        with self._lock:
            tmp = self.folder / "meta.json.tmp"
            tmp.write_text(json.dumps(asdict(self.meta), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.folder / "meta.json")

    # --- transkrypcja ----------------------------------------------------
    def append_segments(self, segments: list[dict]) -> None:
        if not segments:
            return
        with self._lock, open(self.transcript_path, "a", encoding="utf-8") as f:
            for s in segments:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

    def write_segments(self, segments: list[dict]) -> None:
        with self._lock, open(self.transcript_path, "w", encoding="utf-8") as f:
            for s in segments:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

    def load_segments(self) -> list[dict]:
        out = []
        if self.transcript_path.exists():
            for line in self.transcript_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
        out.sort(key=lambda s: s.get("start", 0))
        return out

    def transcript_text(self, with_times: bool = True) -> str:
        lines = []
        for s in self.load_segments():
            t = s.get("text", "").strip()
            if t:
                lines.append(f"[{fmt_time(s['start'])}] {t}" if with_times else t)
        return "\n".join(lines)

    # --- slajdy ----------------------------------------------------------
    def load_slides(self) -> dict:
        if self.slides_json.exists():
            try:
                return json.loads(self.slides_json.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"slides": [], "events": []}

    def save_slides(self, data: dict) -> None:
        with self._lock:
            tmp = self.folder / "slides.json.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.slides_json)

    # --- fiszki ----------------------------------------------------------
    def load_flashcards(self) -> list[dict]:
        if self.flashcards_path.exists():
            try:
                return json.loads(self.flashcards_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def save_flashcards(self, cards: list[dict]) -> None:
        self.flashcards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""


# ---------------------------------------------------------------------------
# Szybki indeks biblioteki (pamięć podręczna zależna od czasu modyfikacji plików)
# ---------------------------------------------------------------------------
_meta_cache: dict[str, tuple[float, Lecture]] = {}
_text_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return -1.0


def list_lectures(library: Path) -> list[Lecture]:
    """Lista wykładów. meta.json czytane tylko, gdy plik się zmienił."""
    library = Path(library)
    if not library.exists():
        return []
    out = []
    seen = set()
    with _cache_lock:
        for entry in os.scandir(library):
            if not entry.is_dir():
                continue
            meta = Path(entry.path) / "meta.json"
            mt = _mtime(meta)
            if mt < 0:
                continue
            key = entry.path
            seen.add(key)
            cached = _meta_cache.get(key)
            if cached and cached[0] == mt:
                out.append(cached[1])
            else:
                lec = Lecture(Path(entry.path))
                _meta_cache[key] = (mt, lec)
                out.append(lec)
    out.sort(key=lambda l: l.meta.created or l.folder.name, reverse=True)
    return out


def _cached(path: Path, loader):
    key = str(path)
    mt = _mtime(path)
    with _cache_lock:
        c = _text_cache.get(key)
        if c and c[0] == mt:
            return c[1]
    val = loader() if mt >= 0 else None
    with _cache_lock:
        _text_cache[key] = (mt, val)
    return val


def notes_lower(lec: Lecture) -> str:
    """Treść notatek małymi literami (do wyszukiwania), z pamięci podręcznej."""
    return _cached(lec.notes_path, lambda: lec.notes_path.read_text(encoding="utf-8").lower()) or ""


def card_stats(lec: Lecture) -> tuple[int, int]:
    """(liczba fiszek, liczba do powtórki dziś). Pamięć podręczna ważna tylko w danym dniu."""
    from .srs import is_due, today
    day = today()

    def load():
        cards = lec.load_flashcards()
        return day, len(cards), sum(1 for c in cards if is_due(c, day))
    res = _cached(lec.flashcards_path, load)
    if res and res[0] != day:
        with _cache_lock:
            _text_cache.pop(str(lec.flashcards_path), None)
        res = _cached(lec.flashcards_path, load)
    return (res[1], res[2]) if res else (0, 0)


def slides_info(lec: Lecture) -> dict:
    return _cached(lec.slides_json, lec.load_slides) or {"slides": [], "events": []}


# ---------------------------------------------------------------------------
# Słownik terminów przedmiotu (podpowiedzi dla rozpoznawania mowy)
# ---------------------------------------------------------------------------
def _glossary_file(library: Path) -> Path:
    return Path(library) / ".slowniki.json"


def load_glossary(library: Path, subject: str) -> str:
    try:
        return json.loads(_glossary_file(library).read_text(encoding="utf-8")).get(subject, "")
    except Exception:
        return ""


def save_glossary(library: Path, subject: str, terms: str) -> None:
    p = _glossary_file(library)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data[subject] = terms.strip()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
