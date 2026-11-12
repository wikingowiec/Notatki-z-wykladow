"""Sesja nagrywania: spina audio, transkrypcję na żywo, slajdy, zaznaczenia i notatki na żywo.

Kontynuacja wykładu: nowa sesja dla istniejącego wykładu nagrywa kolejną część (audio_02.opus …),
a czas biegnie dalej od końca poprzedniej części – transkrypcja, slajdy i zaznaczenia trafiają do tej samej notatki.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import numpy as np

from .audio_capture import TARGET_SR, AudioRecorder, AudioSourceInfo
from .config import Settings
from .screen_capture import VideoSourceInfo, make_grabber
from .slides import SlideEvent, SlideRecorder, SlideStore
from .storage import Lecture, load_glossary
from .transcriber import LiveTranscriber, Vocabulary, WhisperEngine, engine_for, take_warm
from .i18n import tr
from .timing import StepTimer

log = logging.getLogger(__name__)

MARK_LOOKBACK = 20.0   # zaznaczenie zaczyna się tyle sekund wcześniej (reagujemy po usłyszeniu)


class _AudioFeed:
    """Przekazuje dźwięk do transkrypcji na żywo tylko z bieżącego rejestratora.

    Po zmianie źródła nowy rejestrator zaczyna się w próbce `base` (oś tej sesji). Zanim stary się zamknie, oba
    przez chwilę nagrywają – zakładkę obcinamy, a ewentualną dziurę wypełniamy ciszą. Dzięki temu czas fragmentów
    transkrypcji dalej zgadza się z zegarem wykładu, a Whisper pracuje bez przerwy (bez ponownego ładowania)."""

    def __init__(self, sink: Callable[[np.ndarray], None]):
        self.sink: Optional[Callable[[np.ndarray], None]] = sink
        self.fed = 0               # próbek przekazanych do transkrypcji (oś sesji)
        self.active = None         # rejestrator, z którego bierzemy dźwięk
        self.base = 0              # próbka sesji odpowiadająca próbce 0 aktywnego rejestratora
        self._lock = threading.Lock()

    def activate(self, rec, base: int) -> None:
        with self._lock:
            self.active, self.base = rec, int(base)

    def listener(self, rec) -> Callable[[np.ndarray], None]:
        def on_audio(x: np.ndarray):
            with self._lock:
                if rec is not self.active or self.sink is None:
                    return
                start = self.base + rec.samples_written - len(x)    # _emit liczy próbki przed słuchaczami
                end = start + len(x)
                if start > self.fed:                                # dziura – cisza
                    self.sink(np.zeros(start - self.fed, dtype=np.float32))
                elif start < self.fed:                              # zakładka ze starym źródłem – obetnij
                    x = x[self.fed - start:]
                if x.size:
                    self.sink(x)
                self.fed = max(self.fed, end)
        return on_audio


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
        self.paused = False
        self._pause_at = 0.0
        self._paused_total = 0.0
        self._loader: Optional[threading.Thread] = None
        self.part_file: Optional[str] = None      # plik dźwięku tej części (np. audio_02.opus)
        self.part_offset = 0.0         # początek bieżącego pliku dźwięku na osi wykładu (zmienia się przy zmianie źródła)
        self._feed: Optional[_AudioFeed] = None
        self._switch_lock = threading.Lock()      # zmiana źródła i zatrzymanie nie mogą się przeplatać
        self.slides_held = False       # „Wstrzymaj slajdy” – dźwięk i transkrypcja idą dalej

    @property
    def is_continuation(self) -> bool:
        return self.offset > 0

    # ------------------------------------------------------------------
    def start(self) -> None:
        """Blokujące (otwiera dźwięk, ekran, pliki) – wołać w wątku roboczym. Czasy kroków trafiają do logu."""
        steps = StepTimer("Start nagrywania")  # i18n: nie
        s = self.settings
        lec = self.lecture
        m = lec.meta
        # --- kolejna część wykładu? ---
        parts = lec.audio_parts()
        if parts and not m.parts:          # starszy wykład z jednym plikiem – zapisz go jako część 1
            f, off, dur = parts[0]
            m.parts = [{"file": f.name, "offset": 0.0, "duration": float(m.duration or dur)}]
        self.offset = float(m.duration or 0.0)          # kontynuacja: czas biegnie dalej
        self.part_offset = self.offset
        part_file = None
        if self.audio_info is not None:
            part_file = lec.new_part_file()
            m.parts = list(m.parts or []) + [{"file": part_file, "offset": self.offset, "duration": 0.0,
                                              "recorded_at": datetime.now().astimezone().isoformat()}]
        self.part_file = part_file
        self.part_index = max(1, len(m.parts or [])) if part_file else 1 + int(self.offset > 0)
        m.status = "nagrywanie"
        if self.audio_info is not None:
            m.audio_source = self.audio_info.label
        m.video_source = self.video_info.label if self.video_info else ""
        if self.language not in ("", "auto") and not m.language:
            m.language = self.language
        lec.save_meta()
        steps.step("meta.json")

        # 1) audio
        if part_file is not None:
            self.recorder = AudioRecorder(self.audio_info, lec.folder / part_file, backend=s.audio_backend)
        if self.live:
            # zaplanowane nagrywanie: silnik mógł się załadować wcześniej (prewarm) – wtedy start bez czekania
            self.engine = (take_warm(s, self.language, low_vram=self.live_notes_enabled)
                           or engine_for(s, self.language, low_vram=self.live_notes_enabled))
            self.engine.hotwords = self.vocab.hotwords()
            self.transcriber = LiveTranscriber(self.engine, s.live_chunk_seconds, self._segments)
            self._feed = _AudioFeed(self.transcriber.feed)
            self._feed.activate(self.recorder, 0)
            self.recorder.listeners.append(self._feed.listener(self.recorder))
            steps.step("engine_for")
        self.t0 = time.monotonic()          # zegar nagrania rusza razem z dźwiękiem
        if self.recorder:
            self.recorder.start(self.t0)
            steps.step(f"AudioRecorder.start ({self.recorder.source_name})")  # i18n: nie

        # 2) slajdy (czas liczony od początku całego wykładu)
        if self.video_info and self.video_info.kind != "none":
            grabber = make_grabber(self.video_info)
            steps.step("make_grabber")
            if grabber is not None:
                store = SlideStore(lec, ocr=s.ocr_enabled, on_ocr=self._slide_text)
                steps.step("SlideStore")
                self.slide_rec = SlideRecorder(grabber, store, roi=self.roi, interval=s.slide_interval,
                                               sensitivity=s.slide_sensitivity, stable_seconds=s.slide_stable_seconds,
                                               on_slide=self.on_slide, on_status=self.on_video_status)
                self.slide_rec.start(self.t0 - self.offset)
                steps.step("SlideRecorder.start")

        # 3) model Whisper ładujemy w tle – audio w tym czasie się buforuje
        if self.live:
            self._loader = threading.Thread(target=self._load_whisper, name="WhisperLoad", daemon=True)
            self._loader.start()
        steps.done()

    def set_roi(self, roi) -> None:
        """Nowy obszar slajdu w trakcie nagrywania (złapane slajdy zostają)."""
        self.roi = tuple(roi) if roi else None
        if self.slide_rec is not None:
            self.slide_rec.set_roi(self.roi)

    # ------------------------------------------------------------------ zmiana źródeł w trakcie
    def _time_at(self, mono: float) -> float:
        """Chwila `mono` (time.monotonic) na osi całego wykładu."""
        if self.paused:
            return self.offset + self._pause_at - self.t0 - self._paused_total
        return self.offset + mono - self.t0 - self._paused_total

    def _note_switch(self, entry: dict) -> None:
        m = self.lecture.meta
        m.switches = list(m.switches or []) + [entry]
        self.lecture.save_meta()

    def switch_audio(self, info: AudioSourceInfo) -> dict:
        """Nowe źródło dźwięku bez przerywania nagrania (blokujące – wołać w wątku roboczym).

        Najpierw otwieramy nowe źródło (nowa część wykładu: audio_NN.opus, początek = bieżący czas wykładu), dopiero
        potem zamykamy stare – nagranie nie ma dziury, a gdy nowe źródło się nie otworzy, stare po prostu gra dalej
        (wyjątek z opisem błędu). Transkrypcja na żywo działa dalej na tym samym modelu."""
        with self._switch_lock:
            old = self.recorder
            if old is None:
                raise RuntimeError(tr("To nagranie jest bez dźwięku."))
            lec, m = self.lecture, self.lecture.meta
            name = lec.new_part_file()
            path = lec.folder / name
            t_start = time.monotonic()
            at = self._time_at(t_start)
            new = AudioRecorder(info, path, backend=self.settings.audio_backend)
            if self._feed is not None:
                new.listeners.append(self._feed.listener(new))
            try:
                new.start(t_start, paused=self.paused)
            except Exception:
                log.exception("zmiana źródła dźwięku")
                try:
                    new.stop()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            ready = time.monotonic()
            # od tej chwili transkrypcja słucha nowego źródła; zakładka ze starym jest obcinana
            if self._feed is not None:
                self._feed.activate(new, round((at - self.offset) * TARGET_SR))
            self.recorder = new
            old_label = self.audio_info.label if self.audio_info else ""
            self.audio_info = info
            try:
                old.stop()
            except Exception:  # noqa: BLE001
                log.exception("zamykanie poprzedniego źródła dźwięku")
            # stara część kończy się tam, gdzie zaczyna nowa (nagrała odrobinę dłużej – tę zakładkę pomijamy)
            if m.parts:
                m.parts[-1]["duration"] = round(max(0.0, min(old.elapsed(), at - self.part_offset)), 2)
            m.parts = list(m.parts or []) + [{"file": name, "offset": round(at, 2), "duration": 0.0,
                                              "recorded_at": datetime.now().astimezone().isoformat()}]
            self.part_offset = round(at, 2)
            self.part_file = name
            m.audio_source = info.label
            # przerwa = czas, w którym żadne źródło nie nagrywało; stare gra, dopóki nowe się nie otworzy, więc 0
            entry = {"t": round(at, 1), "kind": "audio", "from": old_label, "to": info.label, "gap": 0.0,
                     "switch_seconds": round(ready - t_start, 2), "file": name}
            self._note_switch(entry)
            log.info("Zmiana źródła dźwięku %s → %s w %.1f s (otwarcie %.2f s)", old_label, info.label, at,
                     ready - t_start)
            return entry

    def switch_video(self, info, roi=None) -> dict:
        """Nowy ekran/okno ze slajdami (blokujące – sprawdza, czy źródło daje obraz). Numeracja slajdów, magazyn
        i oś czasu zostają; podmiana następuje w wątku slajdów przy następnej klatce."""
        from .screen_capture import make_grabber
        with self._switch_lock:
            rec = self.slide_rec
            if rec is None:
                raise RuntimeError(tr("To nagranie jest bez slajdów."))
            probe = make_grabber(info)            # próbny zrzut osobnym grabberem (mss działa tylko w swoim wątku)
            if probe is None:
                raise RuntimeError(tr("Nie da się nagrywać tego źródła."))
            img, err = None, ""
            try:
                for _ in range(3):
                    img = probe.grab()
                    if img is not None:
                        break
                    err = getattr(probe, "last_error", "") or err
                    time.sleep(0.3)
            except Exception as e:  # noqa: BLE001
                err = str(e)
            finally:
                try:
                    probe.close()
                except Exception:  # noqa: BLE001
                    pass
            if img is None:
                raise RuntimeError(tr("Nie udało się zrobić zrzutu z „{label}”. {err}", label=info.label, err=err).strip())
            grabber = make_grabber(info)
            old_label = self.video_info.label if self.video_info else ""
            self.video_info = info
            self.roi = tuple(roi) if roi else None
            rec.set_source(grabber, self.roi)
            self.lecture.meta.video_source = info.label
            entry = {"t": round(self.now(), 1), "kind": "video", "from": old_label, "to": info.label}
            self._note_switch(entry)
            return entry

    def hold_slides(self, on: bool) -> None:
        """„Wstrzymaj slajdy”: zrzuty ekranu stoją, dźwięk i transkrypcja idą dalej (czas wykładu biegnie).
        Po wznowieniu ekran jest porównywany z ostatnim slajdem – ten sam obraz nie zapisze się drugi raz."""
        self.slides_held = bool(on)
        if self.slide_rec is not None:
            self.slide_rec.hold(self.slides_held)

    def current_frame(self):
        """Ostatni pełny zrzut ekranu ze źródła slajdów (None, gdy jeszcze żadnego nie było)."""
        return self.slide_rec.last_frame if self.slide_rec is not None else None

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
            self.on_status(tr("Transkrypcja na żywo działa ({device})", device=self.engine.device))
            self.transcriber.start()
            if self.live_notes_enabled:
                from .live_notes import LiveNotes
                self.live_notes = LiveNotes(self.lecture, self.settings, self.on_notes_update, self.on_notes_status)
                self.live_notes.start()
        except Exception as e:  # noqa: BLE001
            log.exception("whisper")
            self.whisper_error = str(e)
            self.on_status(tr("⚠ Transkrypcja na żywo niedostępna: {e}. Nagranie trwa – transkrypcja zostanie zrobiona z pliku.", e=e))
            if self._feed is not None:
                self._feed.sink = None          # dźwięk dalej trafia do pliku, ale już nie do transkrypcji

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

    # ------------------------------------------------------------------ pauza
    def pause(self) -> None:
        """Wstrzymuje dźwięk, transkrypcję i slajdy; czas stoi. Otwarte zaznaczenie się kończy."""
        if self.paused:
            return
        if self.open_mark:
            self.end_mark()
        self.paused = True
        self._pause_at = time.monotonic()
        if self.recorder:
            self.recorder.pause()
        if self.slide_rec:
            self.slide_rec.pause()

    def resume(self) -> None:
        if not self.paused:
            return
        self._paused_total += time.monotonic() - self._pause_at
        self.paused = False
        if self.recorder:
            self.recorder.resume()
        if self.slide_rec:
            self.slide_rec.resume()

    # ------------------------------------------------------------------
    def elapsed(self) -> float:
        if not self.t0:
            return 0.0
        now = self._pause_at if self.paused else time.monotonic()
        return now - self.t0 - self._paused_total

    def level_db(self) -> float:
        return self.recorder.level_db if self.recorder else -90.0

    def pending_seconds(self) -> float:
        return self.transcriber.pending_seconds if self.transcriber else 0.0

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Blokujące – wywoływać w wątku roboczym."""
        with self._switch_lock:          # trwająca zmiana źródła kończy się przed zatrzymaniem
            self._stop_locked()

    def _stop_locked(self) -> None:
        self.on_status(tr("Zatrzymywanie nagrywania…"))
        if self.paused:
            self.resume()
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
        m.duration = round(self.part_offset + part_dur, 1)
        if self._loader:
            self._loader.join()
        if self.transcriber and self.whisper_ready:
            self.on_status(tr("Kończenie transkrypcji ostatnich fragmentów…"))
            self.transcriber.stop_and_flush()
        self.needs_file_transcription = self.audio_info is not None and ((not self.live) or (not self.whisper_ready) or bool(
            self.transcriber and self.transcriber.error))
        if self.engine:
            self.engine.unload()
        m.status = "nagrany"
        self.lecture.save_meta()
        self.on_status(tr("Nagranie zapisane"))
