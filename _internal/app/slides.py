"""Wykrywanie zmian slajdów i zapisywanie zrzutów.

Algorytm (bez AI):
  1. co `interval` s robimy zrzut (opcjonalnie wycinamy wybrany obszar),
  2. zmniejszamy do 320 px szerokości, skala szarości, lekkie rozmycie,
  3. liczymy ułamek pikseli, które zmieniły się względem poprzedniej klatki i względem ostatniego slajdu,
  4. gdy obraz różni się od ostatniego slajdu o więcej niż `sensitivity` i jest stabilny przez
     `stable_seconds` – zapisujemy nowy slajd (czas = moment, w którym zaczęła się zmiana),
  5. jeśli nowy obraz jest prawie identyczny z którymś wcześniejszym slajdem (powrót do slajdu),
     nie zapisujemy duplikatu, tylko notujemy zdarzenie „powrót do slajdu N”.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

PIXEL_DIFF = 25          # różnica jasności piksela uznawana za zmianę
GRID_W, GRID_H = 16, 9   # obraz dzielimy na 144 kratki
CELL_CHANGED = 0.02      # kratka „zmieniona”, gdy zmieniło się >2% jej pikseli
WORK_WIDTH = 480
MOVING_CELLS = 5         # tyle zmienionych kratek między klatkami to jeszcze „stoi” (kursor)


def small_gray(img: np.ndarray, width: int = WORK_WIDTH) -> np.ndarray:
    h, w = img.shape[:2]
    nh = max(GRID_H * 4, int(h * width / max(1, w)))
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.resize(g, (width, nh), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(g, (3, 3), 0)


def changed_cells(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Macierz GRID_H×GRID_W: True tam, gdzie kratka się zmieniła."""
    if a is None or b is None:
        return np.ones((GRID_H, GRID_W), dtype=bool)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    mask = (cv2.absdiff(a, b) > PIXEL_DIFF).astype(np.float32)
    frac = cv2.resize(mask, (GRID_W, GRID_H), interpolation=cv2.INTER_AREA)  # średnia w kratkach
    return frac > CELL_CHANGED


def changed_fraction(a: np.ndarray, b: np.ndarray, ignore: Optional[np.ndarray] = None) -> float:
    cells = changed_cells(a, b)
    if ignore is not None:
        valid = ~ignore
        n = int(valid.sum())
        return float((cells & valid).sum()) / n if n else 0.0
    return float(cells.mean())


@dataclass
class SlideEvent:
    t: float            # czas (s) od początku nagrania
    index: int          # numer slajdu (1..)
    is_new: bool        # False = powrót do wcześniejszego slajdu
    image: Optional[np.ndarray] = None
    updated: bool = False   # True = ten sam slajd, ale dopisały się elementy (animacja punktów) – podmieniamy zrzut
    text: str = ""          # tekst slajdu (OCR)
    ignored: bool = False   # powrót do slajdu usuniętego przez użytkownika – nic nie zapisujemy
    merge_local: tuple = () # (numer nowego, numer docelowy) w numeracji detektora – do scalenia duplikatu


def cell_std(g: np.ndarray) -> np.ndarray:
    f = g.astype(np.float32)
    m = cv2.resize(f, (GRID_W, GRID_H), interpolation=cv2.INTER_AREA)
    m2 = cv2.resize(f * f, (GRID_W, GRID_H), interpolation=cv2.INTER_AREA)
    return np.sqrt(np.maximum(m2 - m * m, 0))


class SlideDetector:
    """Wykrywa nowe slajdy. Obszary, które ciągle się ruszają (kamerka prowadzącego, film),
    są automatycznie ignorowane (maska ruchu), więc nie blokują wykrywania."""

    def __init__(self, sensitivity: float = 0.05, stable_seconds: float = 1.5):
        self.sensitivity = sensitivity
        self.stable_seconds = stable_seconds
        self.prev: Optional[np.ndarray] = None
        self.current: Optional[np.ndarray] = None   # mały obraz aktualnego slajdu
        self.current_index = 0
        self.saved: list[np.ndarray] = []
        self.stable_since: Optional[float] = None
        self.change_started: Optional[float] = None
        self.history: deque = deque(maxlen=8)

    def _mask(self) -> np.ndarray:
        if len(self.history) < 3:
            return np.zeros((GRID_H, GRID_W), dtype=bool)
        m = np.sum(self.history, axis=0) >= 3
        return m if m.mean() < 0.6 else np.zeros_like(m)   # gdy „rusza się” prawie wszystko – nie maskuj

    def process(self, img: np.ndarray, t: float) -> Optional[SlideEvent]:
        if img is None or img.size == 0:
            return None
        s = small_gray(img)
        # pomiń puste/czarne ekrany (np. zminimalizowane okno, wygaszacz)
        if float(s.std()) < 4.0:
            self.prev = None
            self.stable_since = None
            return None

        if self.prev is not None and self.prev.shape != s.shape:
            self.prev = None
        moving_cells = changed_cells(s, self.prev) if self.prev is not None else np.ones((GRID_H, GRID_W), bool)
        # maska ruchu: kratki, które zmieniały się w ≥3 z ostatnich 8 klatek (kamerka, film)
        if self.prev is not None:
            self.history.append(moving_cells)
        mask = self._mask()
        self.prev = s

        moving = int((moving_cells & ~mask).sum()) > MOVING_CELLS   # kursor myszy zmienia tylko kilka kratek
        if moving:
            self.stable_since = None
        elif self.stable_since is None:
            self.stable_since = t

        diff_cur = changed_fraction(s, self.current, mask) if self.current is not None else 1.0
        if diff_cur > self.sensitivity:
            if self.change_started is None:
                self.change_started = t
        else:
            self.change_started = None
            return None

        stable_for = (t - self.stable_since) if self.stable_since is not None else -1
        if stable_for < self.stable_seconds - 1e-6:
            return None

        t_change = self.change_started if self.change_started is not None else t
        self.change_started = None
        prev_slide = self.current
        self.current = s
        # animacja: na tym samym slajdzie pojawiły się nowe elementy w pustych miejscach
        if prev_slide is not None and self.current_index and diff_cur < 0.35:
            changed = changed_cells(s, prev_slide) & ~mask
            if changed.any():
                empty_before = cell_std(prev_slide) < 6.0
                if (changed & empty_before).sum() / changed.sum() >= 0.8:
                    self.saved[self.current_index - 1] = s
                    return SlideEvent(t_change, self.current_index, False, img, updated=True)
        # powrót do wcześniejszego slajdu?
        best_i, best_d = -1, 1.0
        for i, old in enumerate(self.saved):
            d = changed_fraction(s, old, mask)
            if d < best_d:
                best_i, best_d = i, d
        if best_i >= 0 and best_d < self.sensitivity * 0.8:
            self.current_index = best_i + 1
            return SlideEvent(t_change, self.current_index, False)
        self.saved.append(s)
        self.current_index = len(self.saved)
        return SlideEvent(t_change, self.current_index, True, img)

    def merge(self, new_local: int, target_local: int, replace: bool) -> None:
        """Magazyn uznał „nowy” slajd za duplikat (powrót / animacja) – scal go z wcześniejszym."""
        if new_local == len(self.saved) and 1 <= target_local < new_local:
            s = self.saved.pop()
            if replace:
                self.saved[target_local - 1] = s
            self.current_index = target_local


def save_png(path: Path, img: np.ndarray) -> None:
    """cv2.imwrite nie obsługuje polskich znaków w ścieżce na Windows – zapisujemy przez imencode."""
    ok, buf = cv2.imencode(".png", img)
    if ok:
        Path(path).write_bytes(buf.tobytes())


THUMB_W = 960


def thumb_path(folder: Path, file: str) -> Path:
    """slides/slide_001.png -> slides/thumbs/slide_001.jpg"""
    return Path(folder) / "slides" / "thumbs" / (Path(file).stem + ".jpg")


def write_thumb(img: np.ndarray, dest: Path) -> None:
    h, w = img.shape[:2]
    if w > THUMB_W:
        img = cv2.resize(img, (THUMB_W, int(h * THUMB_W / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if ok:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(buf.tobytes())


def ensure_thumb(folder: Path, file: str) -> Optional[Path]:
    """Zwraca miniaturę slajdu (tworzy ją, jeśli brak albo oryginał jest nowszy). Wywoływać w tle."""
    src = Path(folder) / file
    dst = thumb_path(folder, file)
    try:
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        img = load_image(src)
        if img is None:
            return None
        write_thumb(img, dst)
        return dst
    except OSError:
        return None


def load_image(path: Path) -> Optional[np.ndarray]:
    try:
        data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Podobieństwo slajdów: odcisk obrazu (odporny na kursor, zegar, drobne różnice) i tekst ze slajdu
# ---------------------------------------------------------------------------
def dhash(img: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.resize(g, (33, 18), interpolation=cv2.INTER_AREA).astype(np.int16)
    return (g[:, 1:] > g[:, :-1]).ravel()


def hash_dist(a, b) -> float:
    if a is None or b is None or len(a) != len(b):
        return 1.0
    return float(np.count_nonzero(a != b)) / len(a)


def text_tokens(text: str) -> set:
    import re as _re
    return {w[:7] for w in _re.findall(r"[0-9a-ząćęłńóśźż]{3,}", (text or "").lower())}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / max(1, len(a | b))


def _contained(small: set, big: set) -> float:
    return len(small & big) / max(1, len(small))


class SlideStore:
    """Zapisuje slajdy na dysk i prowadzi slides.json.

    Duplikaty: nowy slajd porównujemy z wcześniejszymi po tekście (OCR) i odcisku obrazu –
      * tekst poprzedniego slajdu zawiera się w nowym i obraz podobny → animacja (punkty dochodzą po kolei):
        podmieniamy zrzut poprzedniego slajdu,
      * prawie ten sam tekst i obraz co któryś wcześniejszy → powrót do slajdu (bez nowego zdjęcia),
      * slajdy usunięte przez użytkownika (np. kamerka) są pamiętane – gdy wrócą, nic się nie zapisuje."""

    def __init__(self, lecture, ocr: bool = True, on_ocr: Optional[Callable[[str], None]] = None):
        self.lecture = lecture
        self.data = lecture.load_slides()
        self.ocr = ocr
        self.on_ocr = on_ocr            # tekst nowego slajdu (np. terminy dla rozpoznawania mowy)
        self._lock = threading.Lock()
        # kontynuacja wykładu: numeracja slajdów z nowej części idzie dalej
        self.base = max((x["index"] for x in self.data.get("slides", [])), default=0)
        self.sig: dict[int, tuple] = {}      # numer → (tokeny tekstu, odcisk obrazu)
        self.deleted: set[int] = set()
        self.last_index = 0
        for x in self.data.get("slides", []):          # kontynuacja: slajdy z poprzednich części też się liczą
            img = load_image(thumb_path(lecture.folder, x["file"])) if x.get("file") else None
            if img is None and x.get("file"):
                img = load_image(lecture.folder / x["file"])
            if img is not None:
                self.sig[x["index"]] = self._signature(img, x.get("ocr", ""))

    def _signature(self, img: np.ndarray, text: str) -> tuple:
        return (text_tokens(text), dhash(img), small_gray(img))

    def _find_duplicate(self, toks, _unused=None) -> tuple[str, int]:
        """('update'|'revisit'|'', numer)"""
        toks, h, g = toks
        prev = self.sig.get(self.last_index)
        if prev is not None and self.last_index not in self.deleted:
            pt, ph, _pg = prev
            if len(pt) >= 4 and len(toks) > len(pt) and _contained(pt, toks) >= 0.9 and hash_dist(ph, h) <= 0.35:
                return "update", self.last_index
        best, best_i = 1.0, 0
        for i, (t_, h_, g_) in self.sig.items():
            d = hash_dist(h_, h)
            if d > 0.30:
                continue
            both_text = len(toks) >= 3 and len(t_) >= 3
            if both_text and _jaccard(toks, t_) < 0.8:
                continue                      # inny tekst – na pewno inny slajd
            cells = changed_fraction(g, g_)   # kratki obrazu: dopuszczalny zegar, kursor, mała nakładka
            if cells <= 0.05 and d < best:
                best, best_i = d, i
        return ("revisit", best_i) if best_i else ("", 0)

    def delete(self, index: int) -> bool:
        """Usuwa slajd (np. zrzut kamerki). Zapamiętuje go, żeby nie złapał się drugi raz."""
        with self._lock:
            entry = next((x for x in self.data.get("slides", []) if x["index"] == index), None)
            if entry is None:
                return False
            self.data["slides"] = [x for x in self.data["slides"] if x["index"] != index]
            self.data["events"] = [e for e in self.data.get("events", []) if e["index"] != index]
            self.deleted.add(index)
            for f in (self.lecture.folder / entry["file"], thumb_path(self.lecture.folder, entry["file"])):
                try:
                    Path(f).unlink(missing_ok=True)
                except OSError:
                    pass
            self.lecture.save_slides(self.data)
            return True

    def text_of(self, index: int) -> str:
        with self._lock:
            e = next((x for x in self.data.get("slides", []) if x["index"] == index), None)
            return (e or {}).get("ocr", "")

    def add(self, ev: SlideEvent) -> Optional[str]:
        local = ev.index
        ev.index = self.base + ev.index      # numer detektora → numer w całym wykładzie
        if ev.index in self.deleted:         # powrót do usuniętego slajdu (np. kamerka) – pomiń
            ev.ignored = True
            return None
        with self._lock:
            path = self._add_locked(ev, local)
        if not ev.ignored and ev.text and self.on_ocr:
            try:
                self.on_ocr(ev.text)
            except Exception:
                pass
        return path

    def _add_locked(self, ev: SlideEvent, local: int) -> Optional[str]:
        folder = self.lecture.folder
        text = ""
        if ev.image is not None and self.ocr and (ev.is_new or ev.updated):
            from .ocr import ocr_image
            try:
                text = ocr_image(ev.image)
            except Exception:  # noqa: BLE001
                text = ""
        if ev.is_new and ev.image is not None:
            sig = self._signature(ev.image, text)
            kind, target = self._find_duplicate(sig, None)
            if kind == "update":
                ev.is_new, ev.updated, ev.index = False, True, target
                ev.merge_local = (local, target - self.base, True)
            elif kind == "revisit":
                ev.is_new, ev.index = False, target
                ev.merge_local = (local, target - self.base, False)
                if target in self.deleted:
                    ev.ignored = True
                    return None
                ev.image = None
        path = None
        if ev.updated and ev.image is not None:
            entry = next((x for x in self.data["slides"] if x["index"] == ev.index), None)
            if entry:
                path = folder / entry["file"]
                save_png(path, ev.image)
                write_thumb(ev.image, thumb_path(folder, entry["file"]))
                if self.ocr:
                    entry["ocr"] = text
                self.sig[ev.index] = self._signature(ev.image, text)
                ev.text = text
                self.last_index = ev.index
                self.lecture.save_slides(self.data)
            return str(path) if path else None
        if ev.is_new and ev.image is not None:
            name = f"slide_{ev.index:03d}.png"
            path = self.lecture.slides_dir / name
            save_png(path, ev.image)
            write_thumb(ev.image, thumb_path(folder, f"slides/{name}"))
            self.data["slides"].append({"index": ev.index, "file": f"slides/{name}", "t": round(ev.t, 2), "ocr": text})
            self.sig[ev.index] = self._signature(ev.image, text)
            ev.text = text
        self.last_index = ev.index
        self.data["events"].append({"t": round(ev.t, 2), "index": ev.index})
        self.lecture.save_slides(self.data)
        return str(path) if path else None


def delete_slide(lecture, index: int) -> bool:
    """Usuwa slajd z zapisanego wykładu (plik, miniatura, wpisy w slides.json, obrazek w notatce)."""
    import re as _re
    data = lecture.load_slides()
    entry = next((x for x in data.get("slides", []) if x["index"] == index), None)
    if entry is None:
        return False
    data["slides"] = [x for x in data["slides"] if x["index"] != index]
    data["events"] = [e for e in data.get("events", []) if e["index"] != index]
    lecture.save_slides(data)
    for f in (lecture.folder / entry["file"], thumb_path(lecture.folder, entry["file"])):
        try:
            Path(f).unlink(missing_ok=True)
        except OSError:
            pass
    if lecture.notes_path.exists():        # obrazek i opis „Na slajdzie” znikają też z notatki
        md = lecture.read_text(lecture.notes_path)
        esc = _re.escape(entry["file"])
        md2 = _re.sub(r"!\[[^\]]*\]\(" + esc + r"\)\n+(?:> \*\*[^*\n]+:\*\*[^\n]*\n(?:>[^\n]*\n)*\n?)?", "", md)
        if md2 != md:
            lecture.notes_path.write_text(md2, encoding="utf-8")
    return True


class SlideRecorder:
    """Wątek: co `interval` s robi zrzut, wykrywa zmiany slajdów i zapisuje je."""

    def __init__(self, grabber, store: SlideStore, roi=None, interval: float = 1.0,
                 sensitivity: float = 0.04, stable_seconds: float = 1.5,
                 on_slide: Optional[Callable[[SlideEvent, Optional[str]], None]] = None,
                 on_status: Optional[Callable[[str], None]] = None):
        self.grabber = grabber
        self.store = store
        self.roi = roi
        self.interval = interval
        self.detector = SlideDetector(sensitivity, stable_seconds)
        self.on_slide = on_slide
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.t0 = 0.0

    def start(self, t0: float):
        self.t0 = t0
        self._thread = threading.Thread(target=self._run, name="SlideRecorder", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(5)

    def _run(self):
        from .screen_capture import crop_roi
        last_status = ""
        next_t = time.monotonic()
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                try:
                    img = self.grabber.grab()
                except Exception as e:  # noqa: BLE001
                    img = None
                    log.exception("grab")
                    status = f"Błąd zrzutu ekranu: {e}"
                else:
                    status = getattr(self.grabber, "last_error", "") if img is None else ""
                if status != last_status and self.on_status:
                    self.on_status(status)
                    last_status = status
                if img is not None:
                    img = crop_roi(img, self.roi)
                    ev = self.detector.process(img, now - self.t0)
                    if ev:
                        path = self.store.add(ev)
                        if ev.merge_local:
                            self.detector.merge(*ev.merge_local)
                        if self.on_slide and not ev.ignored:
                            self.on_slide(ev, path)
                next_t += self.interval
                self._stop.wait(max(0.05, next_t - time.monotonic()))
        finally:
            try:
                self.grabber.close()
            except Exception:
                pass


def detect_slides_in_video(path: str, store: SlideStore, sensitivity: float, roi=None,
                           progress: Optional[Callable[[float], None]] = None,
                           cancel: Optional[threading.Event] = None, offset: float = 0.0) -> int:
    """Wykrywa slajdy w pliku wideo (dekoduje tylko klatki kluczowe – szybko). Zwraca liczbę slajdów."""
    import av
    from .screen_capture import crop_roi
    det = SlideDetector(sensitivity, stable_seconds=0.0)
    count = 0
    with av.open(path) as container:
        if not container.streams.video:
            return 0
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        duration = float(container.duration or 0) / 1_000_000 if container.duration else 0.0
        last_t = -999.0
        for frame in container.decode(stream):
            if cancel is not None and cancel.is_set():
                break
            t = float(frame.time or 0.0)
            if t - last_t < 0.9:
                continue
            last_t = t
            img = crop_roi(frame.to_ndarray(format="bgr24"), roi)
            # dwie „klatki” w tym samym czasie – detektor wymaga stabilności
            ev = det.process(img, t) or det.process(img, t)
            if ev:
                ev.t += offset
                store.add(ev)
                if ev.merge_local:
                    det.merge(*ev.merge_local)
                count += ev.is_new
            if progress and duration:
                progress(min(1.0, t / duration))
    return count
