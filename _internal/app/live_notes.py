"""Notatki na żywo: w trakcie nagrywania zamknięte fragmenty wykładu (po zmianie slajdu albo co kilka minut)
od razu trafiają do lokalnego modelu, a notes.md aktualizuje się na bieżąco.

Po zakończeniu nagrania pełne generowanie korzysta z tej samej pamięci podręcznej (notes_cache.json),
więc liczy już tylko ostatni fragment, fiszki i podsumowanie.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from .notes_pipeline import (assemble_markdown, attach_marks, build_sections, lang_key, lecture_lang, load_cache,
                             notes_lang, save_cache, section_key, section_note)
from .prompts import texts
from .storage import Lecture

log = logging.getLogger(__name__)

LIVE_HEADING = "Na żywo – ostatnie minuty (transkrypcja)"


class LiveNotes:
    def __init__(self, lecture: Lecture, settings, on_update: Optional[Callable[[], None]] = None,
                 on_status: Optional[Callable[[str], None]] = None, interval: float = 15.0):
        self.lecture = lecture
        self.s = settings
        self.model = getattr(settings, "live_model", "") or settings.ollama_model
        self.ctx = int(getattr(settings, "live_ctx", 8192))
        self.on_update = on_update or (lambda: None)
        self.on_status = on_status or (lambda m: None)
        self.interval = interval
        self.cache: dict = load_cache(lecture)
        self.done_sections = 0
        self.open_text = ""          # transkrypcja fragmentu, który jeszcze trwa (do pytań na żywo)
        self.open_start = 0.0
        self.busy = False
        self.available = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, name="LiveNotes", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------------
    def _run(self):
        from .llm import Ollama
        self.llm = Ollama(self.s.ollama_url)
        if not self.llm.is_running():
            self.on_status("Notatki na żywo wyłączone: Ollama nie działa. Notatki powstaną po zakończeniu.")
            return
        if not self.llm.has_model(self.model):
            if self.model != self.s.ollama_model and self.llm.has_model(self.s.ollama_model):
                self.model = self.s.ollama_model     # brak lżejszego modelu – używamy głównego
            else:
                self.on_status("Notatki na żywo wyłączone: model AI nie jest pobrany (Ustawienia → Notatki AI).")
                return
        self.available = True
        self.on_status("Notatki na żywo: czekam na pierwszy pełny fragment (zmiana slajdu albo kilka minut mowy).")
        while not self._stop.wait(self.interval):
            try:
                self.step()
            except Exception as e:  # noqa: BLE001
                if self._stop.is_set():
                    break
                log.exception("live notes")
                self.on_status(f"Notatki na żywo: błąd ({e}) – spróbuję ponownie.")

    def step(self, final: bool = False) -> bool:
        """Jeden przebieg: zrób notatki dla nowych zamkniętych fragmentów. Zwraca True, gdy coś dopisano."""
        segs = self.lecture.load_segments()
        if not segs:
            return False
        slides = self.lecture.load_slides()
        sections = build_sections(segs, slides, segs[-1]["end"])
        attach_marks(sections, self.lecture.load_marks())
        src, lang = lecture_lang(self.lecture), notes_lang(self.lecture)   # język wykładu i notatek
        lk = lang_key(lang, src)
        closed = sections if final else sections[:-1]
        if sections and not final:
            with self._lock:
                self.open_text = sections[-1].text
                self.open_start = sections[-1].start
        changed = False
        title, subject = self.lecture.meta.title, self.lecture.meta.subject
        for i, sec in enumerate(closed, 1):
            if self._stop.is_set():
                break
            key = section_key(sec, self.model, lk)
            if key in self.cache:
                continue
            self.busy = True
            self.on_status(f"Notatki na żywo: piszę fragment {i}…")
            try:
                note = section_note(self.llm, self.model, sec, i, 0, title, subject, self.ctx,
                                    cancel=self._stop, keep_alive="30m", lang=lang, src=src)
            finally:
                self.busy = False
            self.cache[key] = note
            save_cache(self.lecture, self.cache)
            changed = True
            self._write(closed, lang, lk)
        if changed:
            self.done_sections = sum(1 for s in closed if section_key(s, self.model, lk) in self.cache)
            self.on_status(f"Notatki na żywo: gotowe fragmenty – {self.done_sections}. "
                           "Następny po zmianie slajdu albo po kilku minutach.")
            self.on_update()
        return changed

    def _write(self, closed, lang: str, lk: str):
        notes = [self.cache.get(section_key(s, self.model, lk), "") for s in closed]
        md = assemble_markdown(self.lecture, closed, notes, texts(lang).live_banner, marks=self.lecture.load_marks())
        tmp = self.lecture.notes_path.with_suffix(".tmp")
        tmp.write_text(md, encoding="utf-8")
        tmp.replace(self.lecture.notes_path)

    # ------------------------------------------------------------------
    def qa_markdown(self) -> str:
        """Źródło dla pytań w trakcie wykładu: gotowe notatki + transkrypcja trwającego fragmentu."""
        md = self.lecture.read_text(self.lecture.notes_path) if self.lecture.notes_path.exists() else \
            f"# {self.lecture.meta.title}\n"
        with self._lock:
            text = self.open_text
        if not text:
            segs = self.lecture.load_segments()
            text = " ".join(s["text"] for s in segs[-60:])
        if text:
            from .storage import fmt_time
            md += f"\n\n## {LIVE_HEADING}\n*{fmt_time(self.open_start)}–teraz*\n\n{text}\n"
        return md
