"""Odzyskiwanie po awarii: wykłady, które zostały przerwane w trakcie nagrywania albo generowania notatek."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .storage import Lecture, list_lectures

log = logging.getLogger(__name__)


@dataclass
class Recovered:
    lecture: Lecture
    kind: str                 # "recording" / "processing"
    duration: float = 0.0
    needs_transcription: bool = False
    ok: bool = True
    message: str = ""


def _audio_seconds(path: Path) -> float:
    try:
        import soundfile as sf
        return float(sf.info(str(path)).duration)
    except Exception:
        return -1.0


def _rewrite(path: Path) -> float:
    """Dekoduje uszkodzony (niedomknięty) plik tak daleko, jak się da, i zapisuje go od nowa poprawnie."""
    import soundfile as sf
    from .audio_decode import decode_audio
    audio = decode_audio(str(path), sampling_rate=16000)
    if len(audio) == 0:
        return 0.0
    tmp = path.with_name(path.stem + ".naprawa" + path.suffix)
    if path.suffix.lower() == ".opus":
        sf.write(str(tmp), audio, 16000, format="OGG", subtype="OPUS")
    else:
        sf.write(str(tmp), audio, 16000, format="FLAC", subtype="PCM_16")
    tmp.replace(path)
    return len(audio) / 16000


def repair(lec: Lecture) -> Recovered:
    m = lec.meta
    if m.status == "przetwarzanie":
        m.status = "nagrany"
        m.error = "Generowanie notatek zostało przerwane (aplikacja się zamknęła)."
        lec.save_meta()
        return Recovered(lec, "processing", m.duration)

    rec = Recovered(lec, "recording")
    parts = list(m.parts or [])
    if not parts:
        for name in ("audio.opus", "audio.flac"):
            if (lec.folder / name).exists():
                parts = [{"file": name, "offset": 0.0, "duration": 0.0}]
                break
    total = 0.0
    for p in parts:
        f = lec.folder / p["file"]
        if not f.exists():
            continue
        dur = _audio_seconds(f)
        if dur <= 0 or p.get("duration", 0) <= 0:
            try:
                dur = _rewrite(f)
            except Exception as e:  # noqa: BLE001
                log.exception("naprawa audio")
                rec.ok = False
                rec.message = f"Nie udało się odczytać nagrania: {e}"
                dur = max(dur, 0.0)
        p["duration"] = round(dur, 1)
        total = max(total, float(p.get("offset", 0)) + dur)
    m.parts = parts
    m.duration = round(total, 1)
    # niezamknięte zaznaczenia
    marks = lec.load_marks()
    if any(x.get("open") for x in marks):
        for x in marks:
            if x.get("open"):
                x["open"] = False
                x["end"] = min(max(x.get("end", x["start"]), x["start"] + 5), total or x["start"] + 5)
        lec.save_marks(marks)
    # czy transkrypcja na żywo objęła prawie całe nagranie?
    segs = lec.load_segments()
    covered = segs[-1]["end"] if segs else 0.0
    rec.needs_transcription = total > 0 and covered < total - 60
    m.status = "nagrany"
    m.error = "" if rec.ok else rec.message
    lec.save_meta()
    rec.duration = total
    return rec


def find_and_repair(library: Path) -> list[Recovered]:
    out = []
    for lec in list_lectures(library):
        if lec.meta.status in ("nagrywanie", "przetwarzanie"):
            try:
                out.append(repair(lec))
            except Exception as e:  # noqa: BLE001
                log.exception("odzyskiwanie")
                out.append(Recovered(lec, "recording", ok=False, message=str(e)))
    return out
