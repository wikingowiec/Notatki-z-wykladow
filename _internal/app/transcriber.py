"""Transkrypcja mowy lokalnie przez faster-whisper (GPU NVIDIA, a gdy się nie da – CPU)."""
from __future__ import annotations

import gc
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)
SR = 16000

# Typowe „halucynacje” Whispera na ciszy/muzyce
_HALLUCINATIONS = [
    r"napisy (stworzone|wykonane|przygotowane) przez", r"amara\.org", r"dzięki za (obejrzenie|uwagę)\.?$",
    r"^dziękuję( bardzo)?\.?$", r"subskrybuj", r"zapraszam na (mój|kolejny) (kanał|odcinek)",
    r"subtitles by", r"thanks for watching", r"^\.+$", r"^muzyka\.?$", r"^\[muzyka\]$",
    r"tłumaczenie.*napisy", r"^ *$",
]
_HALL_RE = re.compile("|".join(_HALLUCINATIONS), re.IGNORECASE)


def is_hallucination(text: str) -> bool:
    t = text.strip()
    return not t or bool(_HALL_RE.search(t))


def setup_cuda_dll_paths() -> None:
    """Na Windows dodaje katalogi DLL z pakietów nvidia-cublas-cu12 / nvidia-cudnn-cu12 do ścieżki wyszukiwania."""
    if sys.platform != "win32":
        return
    import site
    bases = list(site.getsitepackages()) + [site.getusersitepackages()]
    for base in bases:
        nv = Path(base) / "nvidia"
        if not nv.exists():
            continue
        for sub in nv.iterdir():
            b = sub / "bin"
            if b.is_dir():
                try:
                    os.add_dll_directory(str(b))
                except Exception:
                    pass
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


def cuda_available() -> bool:
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return False
    except Exception:
        return False
    if sys.platform == "win32":
        # brak cuDNN/cuBLAS potrafi „zabić” proces zamiast rzucić wyjątek – sprawdzamy wcześniej
        import ctypes
        for dll in ("cublas64_12.dll", "cudnn_ops64_9.dll"):
            try:
                ctypes.WinDLL(dll)
            except OSError:
                log.warning("Brak %s – Whisper użyje CPU", dll)
                return False
    return True


class WhisperEngine:
    def __init__(self, model_name: str = "large-v3", device: str = "auto", language: str = "pl",
                 low_vram: bool = False):
        self.low_vram = low_vram   # przy notatkach na żywo: Whisper w int8 zostawia miejsce na model AI
        self.model_name = model_name
        self.device_pref = device
        self.language = None if language in ("", "auto") else language
        self.model = None
        self.device = ""
        self.hotwords = ""          # terminy z przedmiotu i slajdów – podpowiedź dla rozpoznawania
        self.detected: tuple[str, float] = ("", 0.0)
        self._lock = threading.Lock()

    def load(self, status: Optional[Callable[[str], None]] = None) -> None:
        from faster_whisper import WhisperModel
        from .audio_decode import patch_faster_whisper
        patch_faster_whisper()
        attempts = []
        if self.device_pref in ("auto", "cuda") and cuda_available():
            if self.low_vram:
                attempts += [("cuda", "int8_float16"), ("cuda", "float16")]
            else:
                attempts += [("cuda", "float16"), ("cuda", "int8_float16")]
        if self.device_pref in ("auto", "cpu") or not attempts:
            attempts.append(("cpu", "int8"))
        last = None
        for device, ctype in attempts:
            try:
                if status:
                    status(f"Ładowanie modelu Whisper {self.model_name} ({device})… przy pierwszym uruchomieniu model się pobiera (~3 GB)")
                model_name = self.model_name
                if device == "cpu" and self.model_name.startswith("large") and self.device_pref == "auto":
                    model_name = "medium"   # na CPU large jest za wolny do pracy na żywo
                m = WhisperModel(model_name, device=device, compute_type=ctype)
                # szybki test, czy biblioteki CUDA (cuBLAS/cuDNN) naprawdę działają
                list(m.transcribe(np.zeros(SR, dtype=np.float32), language=self.language or "pl")[0])
                self.model, self.device = m, f"{device}/{ctype}/{model_name}"
                log.info("Whisper: %s", self.device)
                return
            except Exception as e:  # noqa: BLE001
                log.exception("Whisper load %s %s", device, ctype)
                last = e
        raise RuntimeError(f"Nie udało się załadować modelu Whisper: {last}")

    def unload(self) -> None:
        self.model = None
        gc.collect()

    def transcribe_array(self, audio: np.ndarray, prompt: str = "") -> list[dict]:
        with self._lock:
            segments, info = self.model.transcribe(
                audio, language=self.language, beam_size=5, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False, initial_prompt=prompt or None,
                no_speech_threshold=0.6, hotwords=self.hotwords or None,
            )
            if getattr(info, "language", None):
                self.detected = (info.language, float(getattr(info, "language_probability", 0) or 0))
            out = []
            for s in segments:
                text = s.text.strip()
                if s.no_speech_prob > 0.8 or is_hallucination(text):
                    continue
                out.append({"start": float(s.start), "end": float(s.end), "text": text})
            return out

    def transcribe_file(self, path: str, progress: Optional[Callable[[float], None]] = None,
                        on_segment: Optional[Callable[[dict], None]] = None,
                        cancel: Optional[threading.Event] = None) -> list[dict]:
        with self._lock:
            segments, info = self.model.transcribe(
                path, language=self.language, beam_size=5, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False,
                hotwords=self.hotwords or None,
            )
            if getattr(info, "language", None):
                self.detected = (info.language, float(getattr(info, "language_probability", 0) or 0))
            duration = info.duration or 1.0
            out = []
            for s in segments:
                if cancel is not None and cancel.is_set():
                    break
                text = s.text.strip()
                if s.no_speech_prob > 0.8 or is_hallucination(text):
                    continue
                seg = {"start": round(float(s.start), 2), "end": round(float(s.end), 2), "text": text}
                out.append(seg)
                if on_segment:
                    on_segment(seg)
                if progress:
                    progress(min(1.0, s.end / duration))
            return out


def find_cut(buf: np.ndarray, lo: int, hi: int) -> int:
    """Szuka najcichszego miejsca (okna 100 ms) w buf[lo:hi] – tam tniemy, żeby nie przeciąć słowa."""
    lo, hi = max(0, lo), min(len(buf), hi)
    win = SR // 10
    if hi - lo < win * 2:
        return hi
    seg = buf[lo:hi]
    n = len(seg) // win
    energy = np.square(seg[: n * win]).reshape(n, win).mean(axis=1)
    return lo + int(np.argmin(energy)) * win + win // 2


class LiveTranscriber:
    """Odbiera 16 kHz mono (feed), co ~chunk_seconds transkrybuje kawałek pociętego w ciszy audio."""

    def __init__(self, engine: WhisperEngine, chunk_seconds: float = 20.0,
                 on_segments: Optional[Callable[[list[dict]], None]] = None):
        self.engine = engine
        self.chunk = int(chunk_seconds * SR)
        self.on_segments = on_segments
        self._buf = np.zeros(0, dtype=np.float32)
        self._parts: list[np.ndarray] = []   # nowe kawałki – łączone dopiero przy transkrypcji (mniej kopiowania)
        self._parts_len = 0
        self._offset = 0          # próbka (od startu nagrania), od której zaczyna się _buf
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._prompt = ""
        self.pending_seconds = 0.0
        self.error: Optional[str] = None

    def feed(self, x: np.ndarray) -> None:
        with self._lock:
            self._parts.append(x)
            self._parts_len += len(x)
            self.pending_seconds = (len(self._buf) + self._parts_len) / SR

    def start(self):
        self._thread = threading.Thread(target=self._run, name="LiveTranscriber", daemon=True)
        self._thread.start()

    def stop_and_flush(self, timeout: Optional[float] = None):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _take(self, final: bool) -> Optional[tuple[np.ndarray, int]]:
        with self._lock:
            if self._parts:
                self._buf = np.concatenate([self._buf] + self._parts)
                self._parts, self._parts_len = [], 0
            n = len(self._buf)
            if n == 0:
                return None
            if not final and n < self.chunk:
                return None
            if final:
                cut = n
            else:
                cut = find_cut(self._buf, int(self.chunk * 0.7), self.chunk)
            piece = self._buf[:cut]
            self._buf = self._buf[cut:]
            off = self._offset
            self._offset += cut
            self.pending_seconds = len(self._buf) / SR
            return piece, off

    def _process(self, piece: np.ndarray, off: int):
        if piece.size < SR // 2 or float(np.sqrt(np.mean(np.square(piece)))) < 1e-4:
            return
        segs = self.engine.transcribe_array(piece, self._prompt)
        t_off = off / SR
        for s in segs:
            s["start"] = round(s["start"] + t_off, 2)
            s["end"] = round(s["end"] + t_off, 2)
        if segs:
            self._prompt = " ".join(s["text"] for s in segs)[-200:]
            if self.on_segments:
                self.on_segments(segs)

    def _run(self):
        try:
            while not self._stop.is_set():
                item = self._take(final=False)
                if item is None:
                    self._stop.wait(0.3)
                    continue
                self._process(*item)
            # dokończ wszystko, co zostało
            while True:
                item = self._take(final=False) or self._take(final=True)
                if item is None:
                    break
                self._process(*item)
        except Exception as e:  # noqa: BLE001
            log.exception("LiveTranscriber")
            self.error = str(e)


# ---------------------------------------------------------------------------
# Słownictwo dla rozpoznawania mowy
# ---------------------------------------------------------------------------
_COMMON = set("""oraz także które który która jest będzie przez tylko jeśli wtedy gdzie kiedy dlaczego można
należy wykład slajd przykład definicja twierdzenie dowód zadanie pytanie odpowiedź strona rozdział punkt
which there their about would could should these those where because example lecture slide chapter""".split())


def terms_from_text(text: str, limit: int = 25) -> list[str]:
    """Charakterystyczne słowa (terminy, nazwiska, skróty) z tekstu slajdu."""
    out: list[str] = []
    for m in re.finditer(r"[A-Za-zÀ-žĄ-Żą-ż][\wÀ-ž'’-]{3,}", text):
        w = m.group(0)
        lw = w.lower()
        if lw in _COMMON or len(w) < 5 and not w.isupper():
            continue
        before = text[:m.start()].rstrip()
        sentence_start = not before or before[-1] in ".!?:\n•-–"
        capital = w[0].isupper() and not sentence_start       # nazwy własne w środku zdania
        if not (capital or len(w) >= 11 or (w.isupper() and len(w) >= 2)):
            continue
        if lw not in (x.lower() for x in out):
            out.append(w)
        if len(out) >= limit:
            break
    return out


class Vocabulary:
    """Słownik przedmiotu + terminy z ostatnich slajdów → `hotwords` dla Whispera (limit długości)."""

    def __init__(self, glossary: str = "", subject: str = "", title: str = ""):
        self.base = [t.strip() for t in re.split(r"[,;\n]", glossary) if t.strip()]
        self.head = [x for x in (subject, title) if x]
        self.recent: list[str] = []

    def add_slide_text(self, text: str) -> None:
        for t in terms_from_text(text):
            if t in self.recent:
                self.recent.remove(t)
            self.recent.insert(0, t)
        self.recent = self.recent[:40]

    def hotwords(self, max_chars: int = 400) -> str:
        out, seen = [], set()
        for t in self.head + self.base + self.recent:
            if t.lower() in seen:
                continue
            if sum(len(x) + 2 for x in out) + len(t) > max_chars:
                break
            seen.add(t.lower())
            out.append(t)
        return ", ".join(out)
