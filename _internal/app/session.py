"""Sesja nagrywania: spina audio, transkrypcję na żywo, slajdy, zaznaczenia i notatki na żywo.

Kontynuacja wykładu: nowa sesja dla istniejącego wykładu nagrywa kolejną część (audio_02.opus …),
a czas biegnie dalej od końca poprzedniej części – transkrypcja, slajdy i zaznaczenia trafiają do tej samej notatki.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .audio_capture import AudioRecorder, AudioSourceInfo
from .config import Settings
from .screen_capture import VideoSourceInfo, make_grabber
from .slides import SlideEvent, SlideRecorder, SlideStore
from .storage import Lecture, load_glossary
from .transcriber import LiveTranscriber, Vocabulary, WhisperEngine

log = logging.getLogger(__name__)

MARK_LOOKBACK = 20.0   # zaznaczenie zaczyna się tyle sekund wcześniej (reagujemy po usłyszeniu)


class RecordingSession:
    def __init__(self, lecture: Lecture, settings: Settings, audio: Optional[AudioSourceInfo],
                 video: Optional[VideoSourceInfo], roi=None, live_transcription: bool = True,
                 on_segments: Optional[Callable[[list[dict]], None]] = None,
                 on_slide: Optional[Callable[[SlideEvent, Optional[str]], None]] = None,
                 on_status: Optional[Callable[[str], None]] = None,
                 on_video_status: Optional[Callable[[str], None]] = None,
                 live_notes: bool = False,
                 on_notes_update: Optional[Callable[[], None]] = None,
                 on_notes_status: Optional[Callable[[str], None]] = None,
                 language: Optional[str] = None):
        self.lecture = lecture
        self.settings = settings
        self.audio_info = audio
        self.video_info = video
        self.roi = roi
        self.live = live_transcription and audio is not None      # bez dźwięku (tylko slajdy) – nic do transkrypcji
        self.on_segments = on_segments
        self.on_slide = on_slide
        self.on_status = on_status or (lambda s: None)
        self.on_video_status = on_video_status
        self.live_notes_enabled = live_notes and live_transcription
        self.on_notes_update = on_notes_update
        self.on_notes_status = on_notes_status
        self.live_notes = None
        self.language = language or settings.language
        self.recorder: Optional[AudioRecorder] = None
        self.slide_rec: Optional[SlideRecorder] = None
        self.engine: Optional[WhisperEngine] = None
        self.transcriber: Optional[LiveTranscriber] = None
        self.vocab = Vocabulary(load_glossary(settings.library_path(), lecture.meta.subject),
                                lecture.meta.subject, lecture.meta.title)
        self.t0 = 0.0
        self.offset = 0.0              # początek tej części na osi całego wykładu
        self.part_index = 0
        self.whisper_ready = False
        self.whisper_error: Optional[str] = None
        self.needs_file_transcription = False
        self.open_mark: Optional[dict] = None
        self._loader: Optional[threading.Thread] = None

    @property
    def is_continuation(self) -> bool:
        return self.offset > 0

    # ------------------------------------------------------------------
    def start(self) -> None:
        s = self.settings
        lec = self.lecture
        m = lec.meta
        # --- kolejna część wykładu? ---
        parts = lec.audio_parts()
        if parts and not m.parts:          # starszy wykład z jednym plikiem – zapisz go jako część 1
            f, off, dur = parts[0]
            m.parts = [{"file": f.name, "offset": 0.0, "duration": float(m.duration or dur)}]
        self.offset = float(m.duration or 0.0)          # kontynuacja: czas biegnie dalej
        part_file = None
        if self.audio_info is not None:
            part_file = lec.new_part_file()
            from datetime import datetime
            m.parts = list(m.parts or []) + [{"file": part_file, "offset": self.offset, "duration": 0.0,
                                              "recorded_at": datetime.now().astimezone().isoformat()}]
        self.part_index = max(1, len(m.parts or [])) if part_file else 1 + int(self.offset > 0)
        m.status = "nagrywanie"
        if self.audio_info is not None:
            m.audio_source = self.audio_info.label
        m.video_source = self.video_info.label if self.video_info else ""
        if self.language not in ("", "auto") and not m.language:
            m.language = self.language
        lec.save_meta()

        self.t0 = time.monotonic()
        # 1) audio
        if part_file is not None:
            self.recorder = AudioRecorder(self.audio_info, lec.folder / part_file, backend=s.audio_backend)
        if self.live:
            self.engine = WhisperEngine(s.whisper_model, s.whisper_device, self.language,
                                        low_vram=self.live_notes_enabled)
            self.engine.hotwords = self.vocab.hotwords()
            self.transcriber = LiveTranscriber(self.engine, s.live_chunk_seconds, self._segments)
            self.recorder.listeners.append(self.transcriber.feed)
        if self.recorder:
            self.recorder.start(self.t0)

        # 2) slajdy (czas liczony od początku całego wykładu)
        if self.video_info and self.video_info.kind != "none":
            grabber = make_grabber(self.video_info)
            if grabber is not None:
                store = SlideStore(lec, ocr=s.ocr_enabled, on_ocr=self._slide_text)
                self.slide_rec = SlideRecorder(grabber, store, roi=self.roi, interval=s.slide_interval,
                                               sensitivity=s.slide_sensitivity, stable_seconds=s.slide_stable_seconds,
                                               on_slide=self.on_slide, on_status=self.on_video_status)
                self.slide_rec.start(self.t0 - self.offset)

        # 3) model Whisper ładujemy w tle – audio w tym czasie się buforuje
        if self.live:
            self._loader = threading.Thread(target=self._load_whisper, daemon=True)
            self._loader.start()

    def delete_slide(self, index: int) -> bool:
        """Usuwa złapany slajd (np. kamerkę) – także w trakcie nagrywania."""
        if self.slide_rec is not None:
            return self.slide_rec.store.delete(index)
        from .slides import delete_slide
        return delete_slide(self.lecture, index)

    def slide_text(self, index: int) -> str:
        if self.slide_rec is not None:
            return self.slide_rec.store.text_of(index)
        e = next((x for x in self.lecture.load_slides().get("slides", []) if x["index"] == index), None)
        return (e or {}).get("ocr", "")

    def _slide_text(self, text: str):
        self.vocab.add_slide_text(text)
        if self.engine:
            self.engine.hotwords = self.vocab.hotwords()

    def _load_whisper(self):
        try:
            self.engine.load(self.on_status)
            self.whisper_ready = True
            self.on_status(f"Transkrypcja na żywo działa ({self.engine.device})")
            self.transcriber.start()
            if self.live_notes_enabled:
                from .live_notes import LiveNotes
                self.live_notes = LiveNotes(self.lecture, self.settings, self.on_notes_update, self.on_notes_status)
                self.live_notes.start()
        except Exception as e:  # noqa: BLE001
            log.exception("whisper")
            self.whisper_error = str(e)
            self.on_status(f"⚠ Transkrypcja na żywo niedostępna: {e}. Nagranie trwa – transkrypcja zostanie zrobiona z pliku.")
            if self.recorder and self.transcriber:
                try:
                    self.recorder.listeners.remove(self.transcriber.feed)
                except ValueError:
                    pass

    def _segments(self, segs: list[dict]):
        for sg in segs:
            sg["start"] = round(sg["start"] + self.offset, 2)
            sg["end"] = round(sg["end"] + self.offset, 2)
        # język wykładu z automatycznego wykrywania (gdy w ustawieniach „wykryj”)
        if not self.lecture.meta.language and self.engine and self.engine.detected[1] >= 0.7:
            self.lecture.meta.language = self.engine.detected[0]
            self.lecture.save_meta()
        self.lecture.append_segments(segs)
        if self.on_segments:
            self.on_segments(segs)

    # ------------------------------------------------------------------ zaznaczenia
    def now(self) -> float:
        """Bieżący czas na osi całego wykładu."""
        return self.offset + self.elapsed()

    def start_mark(self, kind: str = "important") -> dict:
        t = self.now()
        self.open_mark = {"id": int(time.time() * 1000), "start": round(max(self.offset, t - MARK_LOOKBACK), 1),
                          "end": round(t, 1), "kind": kind}
        self._save_mark(final=False)
        return self.open_mark

    def end_mark(self) -> Optional[dict]:
        mk = self.open_mark
        if mk:
            mk["end"] = round(max(mk["start"] + 5, self.now()), 1)
            self._save_mark(final=True)
            self.open_mark = None
        return mk

    def _save_mark(self, final: bool):
        mk = self.open_mark
        if not mk:
            return
        marks = [x for x in self.lecture.load_marks() if x.get("id") != mk["id"]]
        entry = dict(mk)
        entry["open"] = not final
        marks.append(entry)
        marks.sort(key=lambda x: x["start"])
        self.lecture.save_marks(marks)

    # ------------------------------------------------------------------
    def elapsed(self) -> float:
        return time.monotonic() - self.t0 if self.t0 else 0.0

    def level_db(self) -> float:
        return self.recorder.level_db if self.recorder else -90.0

    def pending_seconds(self) -> float:
        return self.transcriber.pending_seconds if self.transcriber else 0.0

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Blokujące – wywoływać w wątku roboczym."""
        self.on_status("Zatrzymywanie nagrywania…")
        if self.open_mark:
            self.end_mark()
        if self.live_notes:
            self.live_notes.stop(timeout=3)
            if self.live_notes.model != self.settings.ollama_model:   # zwolnij kartę dla mocniejszego modelu
                try:
                    from .llm import Ollama
                    Ollama(self.settings.ollama_url).unload(self.live_notes.model)
                except Exception:
                    pass
        if self.slide_rec:
            self.slide_rec.stop()
        if self.recorder:
            self.recorder.stop()
        part_dur = round(self.recorder.elapsed() if self.recorder else self.elapsed(), 1)
        m = self.lecture.meta
        if m.parts and self.recorder:
            m.parts[-1]["duration"] = part_dur
        m.duration = round(self.offset + part_dur, 1)
        if self._loader:
            self._loader.join()
        if self.transcriber and self.whisper_ready:
            self.on_status("Kończenie transkrypcji ostatnich fragmentów…")
            self.transcriber.stop_and_flush()
        self.needs_file_transcription = self.audio_info is not None and ((not self.live) or (not self.whisper_ready) or bool(
            self.transcriber and self.transcriber.error))
        if self.engine:
            self.engine.unload()
        m.status = "nagrany"
        self.lecture.save_meta()
        self.on_status("Nagranie zapisane")
