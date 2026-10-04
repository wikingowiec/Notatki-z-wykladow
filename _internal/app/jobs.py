"""Zadania w tle: transkrypcja z pliku, import nagrania, generowanie notatek."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from .config import Settings
from .storage import Lecture

log = logging.getLogger(__name__)
Progress = Callable[[str, float], None]


def vocabulary_for(lecture: Lecture, settings: Settings) -> str:
    from .storage import load_glossary
    from .transcriber import Vocabulary
    v = Vocabulary(load_glossary(settings.library_path(), lecture.meta.subject), lecture.meta.subject,
                   lecture.meta.title)
    for sl in reversed(lecture.load_slides().get("slides", [])):
        if sl.get("ocr"):
            v.add_slide_text(sl["ocr"])
    return v.hotwords()


def transcribe_lecture(lecture: Lecture, settings: Settings, progress: Progress,
                       cancel: threading.Event, source: Optional[str] = None) -> None:
    """Transkrypcja wszystkich części nagrania (czas każdej części przesunięty o jej początek)."""
    from .transcriber import engine_for
    parts = [(Path(source), 0.0, 0.0)] if source else lecture.audio_parts()
    if not parts or not parts[0][0].exists():
        raise RuntimeError("Brak pliku audio do transkrypcji.")
    engine = engine_for(settings, lecture.meta.language or settings.language)
    engine.hotwords = vocabulary_for(lecture, settings)
    engine.load(lambda m: progress(m, -1))
    try:
        all_segs: list[dict] = []
        for k, (path, offset, _dur) in enumerate(parts, 1):
            label = f"Transkrypcja części {k}/{len(parts)}" if len(parts) > 1 else "Transkrypcja"
            progress(f"{label} ({engine.device})…", 0.0)
            segs = engine.transcribe_file(str(path), progress=lambda f, l=label: progress(l + "…", f), cancel=cancel)
            if cancel.is_set():
                return
            for sg in segs:
                sg["start"] = round(sg["start"] + offset, 2)
                sg["end"] = round(sg["end"] + offset, 2)
            all_segs += segs
        lecture.write_segments(all_segs)
        if all_segs:
            lecture.meta.duration = max(lecture.meta.duration, all_segs[-1]["end"])
        if not lecture.meta.language and engine.detected[0]:
            lecture.meta.language = engine.detected[0]
        lecture.meta.status = "nagrany"
        lecture.save_meta()
    finally:
        engine.unload()


def import_file(path: str, lecture: Lecture, settings: Settings, progress: Progress, cancel: threading.Event) -> None:
    """Import gotowego nagrania (audio lub wideo): zapis audio, wykrycie slajdów (jeśli wideo), transkrypcja."""
    import soundfile as sf
    from .audio_decode import decode_audio
    progress("Dekodowanie dźwięku…", -1)
    audio = decode_audio(path, sampling_rate=16000)
    part = lecture.new_part_file()
    sf.write(str(lecture.folder / part), audio, 16000, format="OGG", subtype="OPUS")
    lecture.meta.duration = round(len(audio) / 16000, 1)
    lecture.meta.parts = [{"file": part, "offset": 0.0, "duration": lecture.meta.duration}]
    lecture.meta.audio_source = f"Plik: {Path(path).name}"
    lecture.save_meta()
    del audio
    try:
        import av
        with av.open(path) as c:
            has_video = bool(c.streams.video) and (c.streams.video[0].frames or 0) != 1
    except Exception:
        has_video = False
    if has_video and not cancel.is_set():
        from .slides import SlideStore, detect_slides_in_video
        store = SlideStore(lecture, ocr=settings.ocr_enabled)
        n = detect_slides_in_video(path, store, settings.slide_sensitivity,
                                   progress=lambda f: progress("Wykrywanie slajdów w wideo…", f), cancel=cancel)
        lecture.meta.video_source = f"Plik: {Path(path).name} ({n} slajdów)"
        lecture.save_meta()
    if not cancel.is_set():
        transcribe_lecture(lecture, settings, progress, cancel)


def generate_notes(lecture: Lecture, settings: Settings, progress: Progress, cancel: threading.Event,
                   on_token: Optional[Callable[[str], None]] = None, use_cache: bool = False) -> None:
    from .llm import Ollama, LLMError
    from .notes_pipeline import generate
    llm = Ollama(settings.ollama_url)
    if not llm.is_running():
        raise LLMError("Ollama nie działa. Zainstaluj ją z https://ollama.com/download i uruchom, "
                       "a potem kliknij „Generuj notatki”.")
    model = settings.ollama_model
    if not llm.has_model(model):
        progress(f"Pobieranie modelu {model} (jednorazowo)…", 0)
        llm.pull(model, progress=lambda st, f: progress(f"Pobieranie modelu: {st}", f), cancel=cancel)
    vision = None
    if getattr(settings, "describe_slides", True) and settings.vision_model and lecture.load_slides().get("slides"):
        vision = settings.vision_model
        if not llm.has_model(vision):
            try:
                progress(f"Pobieranie modelu do opisu slajdów {vision} (jednorazowo, ~6 GB)…", 0)
                llm.pull(vision, progress=lambda st, f: progress(f"Pobieranie modelu do slajdów: {st}", f),
                         cancel=cancel)
            except Exception as e:  # noqa: BLE001
                from .llm import Cancelled
                if isinstance(e, Cancelled):
                    raise
                log.warning("model do slajdów niedostępny: %s", e)
                vision = None
    lecture.meta.status = "przetwarzanie"
    lecture.save_meta()
    try:
        reuse = [settings.live_model] if use_cache and getattr(settings, "reuse_live_notes", False) else []
        generate(lecture, llm, model, num_ctx=settings.ollama_ctx, cards_per_section=settings.flashcards_per_section,
                 progress=progress, on_token=on_token, cancel=cancel, use_cache=use_cache, vision_model=vision,
                 reuse_models=reuse)
        lecture.meta.status = "gotowy"
        lecture.meta.error = ""
    except Exception as e:
        lecture.meta.status = "nagrany" if cancel.is_set() else "błąd"
        lecture.meta.error = "" if cancel.is_set() else str(e)
        raise
    finally:
        lecture.save_meta()
        llm.unload(model)   # zwolnij pamięć karty graficznej


# ---------------------------------------------------------------------------
# Notatka z plików: nagrania (np. Dyktafon z iPhone'a – m4a, albo mp3) + zdjęcia slajdów
# ---------------------------------------------------------------------------
AUDIO_EXT = (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".flac", ".wma", ".amr", ".caf", ".3gp",
             ".mp4", ".mov", ".mkv", ".webm", ".avi")


def import_files(lecture: Lecture, audio_files: list[str], photo_files: list[str], settings: Settings,
                 progress: Progress, cancel: threading.Event, straighten: bool = True) -> None:
    """Dokłada do notatki kolejne części nagrania i zdjęcia slajdów, potem robi transkrypcję.

    Czas zdjęć: z EXIF (godzina zrobienia) względem godziny nagrania z metadanych pliku; gdy się nie da –
    dopasowanie po treści (tekst slajdu ↔ transkrypcja); gdy i to zawiedzie – w kolejności równomiernie."""
    import soundfile as sf
    from .audio_decode import decode_audio
    from .photos import audio_start_time
    m = lecture.meta
    if m.parts is None:
        m.parts = []
    if not m.parts and lecture.audio_parts():          # starszy wykład z jednym plikiem
        f, _o, d = lecture.audio_parts()[0]
        m.parts = [{"file": f.name, "offset": 0.0, "duration": float(m.duration or d)}]
    names = []
    for k, path in enumerate(audio_files, 1):
        if cancel.is_set():
            return
        progress(f"Wczytywanie nagrania {k}/{len(audio_files)}: {Path(path).name}", -1)
        audio = decode_audio(path, sampling_rate=16000)
        dur = round(len(audio) / 16000, 1)
        part = lecture.new_part_file()
        offset = float(m.duration or 0.0)
        sf.write(str(lecture.folder / part), audio, 16000, format="OGG", subtype="OPUS")
        del audio
        start, alt = audio_start_time(Path(path), dur)
        entry = {"file": part, "offset": offset, "duration": dur, "source": Path(path).name}
        if start:
            entry["recorded_at"] = start.isoformat()
            entry["recorded_at_alt"] = alt.isoformat()
        m.parts = list(m.parts) + [entry]
        m.duration = round(offset + dur, 1)
        names.append(Path(path).name)
        lecture.save_meta()
        # wideo: slajdy z obrazu
        try:
            import av
            with av.open(path) as c:
                has_video = bool(c.streams.video) and (c.streams.video[0].frames or 0) != 1
        except Exception:
            has_video = False
        if has_video and not cancel.is_set():
            from .slides import SlideStore, detect_slides_in_video
            detect_slides_in_video(path, SlideStore(lecture, ocr=settings.ocr_enabled), settings.slide_sensitivity,
                                   progress=lambda f: progress("Wykrywanie slajdów w wideo…", f), cancel=cancel,
                                   offset=offset)
    if names:
        m.audio_source = "Plik: " + ", ".join(names)
        lecture.save_meta()
        transcribe_lecture(lecture, settings, progress, cancel)
    if photo_files and not cancel.is_set():
        add_photos(lecture, photo_files, settings, progress, cancel, straighten)
    if cancel.is_set():
        return
    m.status = "nagrany"
    lecture.save_meta()


def add_photos(lecture: Lecture, photo_files: list[str], settings: Settings, progress: Progress,
               cancel: threading.Event, straighten: bool = True) -> int:
    from .ocr import ocr_image
    from .photos import load_photo, straighten as do_straighten, time_on_axis
    from .slides import thumb_path, write_thumb
    import cv2
    data = lecture.load_slides()
    base = max((x["index"] for x in data.get("slides", [])), default=0)
    m = lecture.meta
    segs = lecture.load_segments()
    duration = float(m.duration or (segs[-1]["end"] if segs else 0))
    loaded = []
    for k, path in enumerate(photo_files, 1):
        if cancel.is_set():
            return 0
        progress(f"Zdjęcia slajdów: {k}/{len(photo_files)} (prostowanie i odczyt tekstu)", k / len(photo_files))
        img, taken = load_photo(Path(path))
        if img is None:
            continue
        if straighten:
            try:
                img = do_straighten(img)
            except Exception:  # noqa: BLE001
                log.exception("prostowanie")
        text = ocr_image(img) if settings.ocr_enabled else ""
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0.0
        loaded.append({"img": img, "taken": taken, "ocr": text, "name": Path(path).name,
                       "sort": taken.timestamp() if taken else mtime})
    # kolejność: czas zrobienia zdjęcia (EXIF), gdy mają go wszystkie; inaczej numer w nazwie (IMG_0001…)
    from .photo_align import align, natural_key
    if loaded and all(ph["taken"] for ph in loaded):
        loaded.sort(key=lambda x: (x["taken"].timestamp(), natural_key(x["name"])))
    else:
        loaded.sort(key=lambda x: natural_key(x["name"]))
    n = len(loaded)
    anchors = {}
    for j, ph in enumerate(loaded):          # pewna godzina: EXIF zdjęcia + czas nagrania z metadanych
        try:
            t = time_on_axis(ph["taken"], m.parts or [])
        except Exception:  # noqa: BLE001 – brak/uszkodzone metadane: po prostu pomijamy
            t = None
        if t is not None:
            anchors[j] = t
    placed = align([ph["ocr"] for ph in loaded], segs, duration, anchors)
    for ph, (t, how) in zip(loaded, placed):
        ph["t"], ph["how"] = t, how
    loaded.sort(key=lambda x: x["t"])
    for j, ph in enumerate(loaded, 1):
        index = base + j
        name = f"slide_{index:03d}.jpg"
        path = lecture.slides_dir / name
        ok, buf = cv2.imencode(".jpg", ph["img"], [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            path.write_bytes(buf.tobytes())
        write_thumb(ph["img"], thumb_path(lecture.folder, f"slides/{name}"))
        data.setdefault("slides", []).append({"index": index, "file": f"slides/{name}", "t": ph["t"],
                                              "ocr": ph["ocr"], "photo": ph["name"], "timing": ph["how"]})
        data.setdefault("events", []).append({"t": ph["t"], "index": index})
    data["events"].sort(key=lambda e: e["t"])
    lecture.save_slides(data)
    if not m.video_source:
        m.video_source = f"Zdjęcia slajdów ({n})"
        lecture.save_meta()
    return n
