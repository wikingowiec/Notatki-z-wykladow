"""Szybkie sprawdzenie przed nagrywaniem (nowe w 2.3): czy działa transkrypcja, Ollama, źródło dźwięku i slajdów
oraz czy jest miejsce na dysku. Bez Qt – wynik to lista Problem, interfejs pokazuje ją jako kartę.

Sprawdzenia idą równolegle w wątkach, łącznie najwyżej ok. 3 s (CHECK_TIMEOUT). Sprawdzenie, które nie zdąży,
po prostu się nie liczy – lepiej nic nie pokazać niż straszyć fałszywym alarmem. Każdy błąd samego sprawdzenia
(a nie sprawdzanej rzeczy) trafia tylko do logu.

Zasada: nagranie wykładu jest najważniejsze. Problem z AI (Whisper, Ollama) ma area="ai" – „Nagrywaj mimo to”
nagrywa dźwięk i slajdy, a transkrypcja i notatki zrobią się później."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .i18n import tr

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
CHECK_TIMEOUT = 3.0          # s – łącznie na wszystkie sprawdzenia
LOW_DISK_GB = 2.0            # ostrzeżenie
CRITICAL_DISK_GB = 0.3       # poniżej tego nagranie może się nie zapisać
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"


@dataclass
class Problem:
    key: str                          # np. "ollama_down", "model:SpeakLeash/…", "cuda", "audio_gone"
    title: str                        # „Transkrypcja nie działa”
    desc: str                         # krótko, dlaczego i co z tego wynika
    steps: list[str] = field(default_factory=list)      # kroki naprawy po kolei
    action: str = ""                  # akcja naprawy: start_ollama / install_ollama / pull:<model> / cpu /
                                      # whisper:<model> / pick_audio / pick_video ("" = brak)
    action_label: str = ""            # napis na przycisku, np. „Uruchom Ollamę”
    critical: bool = False            # True = coś nie zadziała; False = zadziała gorzej (ostrzeżenie)
    area: str = "ai"                  # "ai" / "audio" / "slides" / "disk"


# ---------------------------------------------------------------------------------------------- pomocnicze
def _short(model: str) -> str:
    """„SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M” → „bielik-11b-v3.0-instruct”."""
    return model.split("/")[-1].split(":")[0] or model


def model_gb(model: str) -> float:
    from .perf import MODEL_GB
    low = model.lower()
    return next((v for k, v in MODEL_GB.items() if k in low), 5.0)


def ollama_tags(url: str, timeout: float = 2.0) -> Optional[set[str]]:
    """Pobrane modele Ollamy (nazwy w jednej postaci, uninstall.canon) albo None, gdy serwer nie odpowiada."""
    from .uninstall import canon
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=timeout) as r:
            data = json.loads(r.read())
        return {canon(m.get("name", "")) for m in data.get("models", [])}
    except Exception:  # noqa: BLE001
        return None


def missing_models(have: set[str], models: list[str]) -> list[str]:
    from .uninstall import canon
    return [m for m in dict.fromkeys(models) if m and canon(m) not in have]


def needed_models(settings, live_notes: bool, slides: bool) -> list[tuple[str, str]]:
    """[(model, rola)] – rola: notes / live / vision."""
    out = []
    if getattr(settings, "auto_generate_notes", True) or live_notes:
        out.append((settings.ollama_model, "notes"))
    if live_notes and getattr(settings, "live_model", ""):
        out.append((settings.live_model, "live"))
    if slides and getattr(settings, "describe_slides", True) and getattr(settings, "vision_model", ""):
        out.append((settings.vision_model, "vision"))
    seen, uniq = set(), []
    for m, role in out:
        if m and m not in seen:
            seen.add(m)
            uniq.append((m, role))
    return uniq


def ollama_down_problem(installed: bool, critical: bool = True) -> Problem:
    start_menu = tr("folderu Aplikacje") if IS_MAC else tr("menu Start")
    if not installed:
        return Problem("ollama_missing", tr("Ollama nie jest zainstalowana"),
                       tr("Bez Ollamy nie powstaną notatki ani odpowiedzi na pytania."),
                       [tr("Kliknij „Pobierz Ollamę” – otworzy się strona ollama.com."),
                        tr("Zainstaluj Ollamę i uruchom ją."),
                        tr("Wróć tutaj – brakujące modele pobierzesz jednym kliknięciem.")],
                       "install_ollama", tr("Pobierz Ollamę"), critical, "ai")
    return Problem("ollama_down", tr("Ollama nie jest uruchomiona"),
                   tr("Bez niej nie powstaną notatki ani odpowiedzi na pytania."),
                   [tr("Kliknij „Uruchom Ollamę” – to potrwa kilka sekund."),
                    tr("Albo otwórz Ollamę z {where}.", where=start_menu)],
                   "start_ollama", tr("Uruchom Ollamę"), critical, "ai")


def model_problem(model: str, role: str) -> Problem:
    why = {"notes": tr("Bez niego nie powstaną notatki po wykładzie."),
           "live": tr("Bez niego nie będzie notatek na żywo – notatki powstaną po zakończeniu."),
           "vision": tr("Bez niego slajdy nie dostaną opisów obrazów i wykresów."),
           "qa": tr("Bez niego nie powstaną odpowiedzi na pytania.")}.get(role, "")
    return Problem(f"model:{model}", tr("Brakuje modelu {name}", name=_short(model)), why,
                   [tr("Kliknij „Pobierz model” – to ok. {gb} GB, potrzebny jest internet.", gb=i18n_gb(model_gb(model))),
                    tr("Pobieranie może trwać w tle, także w trakcie nagrywania.")],
                   f"pull:{model}", tr("Pobierz model"), role in ("notes", "qa"), "ai")


# ---------------------------------------------------------------------------------------------- sprawdzenia
def check_whisper(settings) -> list[Problem]:
    try:
        import importlib
        importlib.import_module("ctranslate2")
        importlib.import_module("faster_whisper")
    except Exception as e:  # noqa: BLE001
        log.warning("Whisper: import nie działa: %s", e)
        return [Problem("whisper_import", tr("Transkrypcja nie działa"),
                        tr("Brakuje bibliotek do rozpoznawania mowy ({x}).", x=e.__class__.__name__),
                        [tr("Zamknij aplikację i uruchom ją ponownie."),
                         tr("Jeśli to nie pomoże: Ustawienia → Aktualizacje → „Sprawdź aktualizacje” albo pobierz "
                            "aplikację jeszcze raz ze strony.")],
                        "", "", True, "ai")]
    out: list[Problem] = []
    device = getattr(settings, "whisper_device", "auto") or "auto"
    nvidia = any(g.get("nvidia") for g in (getattr(settings, "hw_info", None) or {}).get("gpus", []) or [])
    cuda_ok = True
    if not IS_MAC and (device == "cuda" or (device == "auto" and nvidia)):
        from .transcriber import cuda_available
        cuda_ok = cuda_available()
        if not cuda_ok:
            out.append(Problem("cuda", tr("Transkrypcja pójdzie na procesorze (wolniej)"),
                               tr("Karta graficzna NVIDIA nie dała się uruchomić do rozpoznawania mowy. "
                                  "Wszystko zadziała, tylko tekst będzie się pojawiał wolniej."),
                               [tr("Kliknij „Przełącz na CPU”, żeby aplikacja nie próbowała już karty graficznej "
                                   "(dobierze lżejszy model)."),
                                tr("Jeśli chcesz używać karty: zaktualizuj sterownik NVIDIA i uruchom komputer "
                                   "ponownie.")],
                               "cpu", tr("Przełącz na CPU"), False, "ai"))
    name = settings.whisper_model
    # na CPU (auto, bez działającej karty) silnik bierze „medium” zamiast „large” – sprawdzamy ten model
    if device == "auto" and not IS_MAC and name.startswith("large") and (not nvidia or not cuda_ok):
        name = "medium"
    if not whisper_present(name):
        from .perf import WHISPER_GB
        gb = WHISPER_GB.get(name, 1.5)
        out.append(Problem(f"whisper_model:{name}", tr("Brakuje modelu rozpoznawania mowy"),
                           tr("Model {name} nie jest jeszcze pobrany. Pobierze się sam przy pierwszej transkrypcji "
                              "(ok. {gb} GB) – bez internetu transkrypcja nie zadziała.", name=name, gb=i18n_gb(gb)),
                           [tr("Kliknij „Pobierz model” – pobieranie idzie w tle, także w trakcie nagrywania."),
                            tr("Potrzebny jest internet.")],
                           f"whisper:{name}", tr("Pobierz model"), False, "ai"))
    return out


def i18n_gb(gb: float) -> str:
    from . import i18n
    try:
        return i18n.num(gb, 1)
    except Exception:  # noqa: BLE001
        return f"{gb:.1f}"


def whisper_present(name: str) -> bool:
    """Pliki modelu na dysku (bez ładowania): własny folder albo pamięć podręczna Hugging Face."""
    if os.path.isabs(name) or os.sep in name:
        return Path(name, "model.bin").exists()
    try:
        from faster_whisper.utils import download_model
        download_model(name, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001
        pass
    from .uninstall import whisper_cached
    return whisper_cached(name)


def check_ollama(settings, live_notes: bool, slides: bool, warm: bool = True) -> list[Problem]:
    from . import ollama_local
    models = needed_models(settings, live_notes, slides)
    if not models:
        return []
    url = settings.ollama_url
    if not ollama_local.quick_is_up(url, timeout=1.5):
        return [ollama_down_problem(ollama_local.find_ollama() is not None)]
    have = ollama_tags(url)
    if have is None:
        return []
    roles = dict(models)
    out = [model_problem(m, roles[m]) for m in missing_models(have, [m for m, _r in models])]
    live = getattr(settings, "live_model", "")
    if warm and live_notes and live and not missing_models(have, [live]):
        warm_up(url, live, int(getattr(settings, "live_ctx", 8192)))
    return out


def warm_up(url: str, model: str, num_ctx: int) -> None:
    """Załaduj model notatek na żywo do pamięci od razu (num_predict=1), żeby pierwsza notatka nie czekała.
    num_ctx taki sam jak w LiveNotes – inny przeładowałby model. Nie blokuje startu."""
    def work():
        body = json.dumps({"model": model, "prompt": "", "keep_alive": "30m", "stream": False,
                           "options": {"num_ctx": num_ctx, "num_predict": 1}}).encode()
        req = urllib.request.Request(url.rstrip("/") + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                r.read()
            log.info("Model %s załadowany w %.1f s", model, time.monotonic() - t0)
        except Exception as e:  # noqa: BLE001
            log.info("Wstępne ładowanie %s: %s", model, e)
    threading.Thread(target=work, name="OllamaWarmUp", daemon=True).start()


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WIN:
        from .audio_capture import process_table
        table = process_table()
        return not table or any(p == pid for p, _pp, _e in table)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:          # brak uprawnień = proces jest
        return True


def _mic_present(audio) -> Optional[bool]:
    """True/False – mikrofon jest / zniknął; None – nie da się sprawdzić (nie zgłaszamy problemu)."""
    name = audio.label.split(":", 1)[-1].strip().lower()
    if IS_MAC:
        from .mac_audio import input_devices
        devs = input_devices()
        return any(d == audio.device_index for d, *_r in devs) or any(n.lower() == name for _d, n, *_r in devs)
    if IS_WIN:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:  # noqa: BLE001
            return None
        try:
            from pycaw.pycaw import AudioUtilities
            names = [(d.FriendlyName or "").lower() for d in AudioUtilities.GetAllDevices()
                     if getattr(d, "state", None) is None or "active" in str(d.state).lower()]
            if not names:
                return None
            return any(name and (name in n or n in name) for n in names)
        except Exception:  # noqa: BLE001
            log.debug("lista mikrofonów", exc_info=True)
            return None
        finally:
            try:
                comtypes.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass
    return None


def audio_gone_problem(audio, why: str = "") -> Problem:
    if audio is not None and audio.kind == "process":
        title = tr("Aplikacja „{name}” jest zamknięta", name=audio.label)
        desc = why or tr("Nie ma skąd nagrać dźwięku wykładu.")
        steps = [tr("Otwórz „{name}” i włącz wykład.", name=audio.label),
                 tr("Kliknij „Wybierz inne źródło” i wskaż ją na liście (albo inną aplikację lub mikrofon).")]
    else:
        title = tr("Źródło dźwięku nie działa")
        desc = why or tr("Wybrane urządzenie ({name}) jest odłączone albo niedostępne.",
                         name=audio.label if audio is not None else "")
        steps = [tr("Podłącz urządzenie ponownie albo wybierz inne."),
                 tr("Kliknij „Wybierz inne źródło” i wskaż źródło na liście.")]
    return Problem("audio_gone", title, desc, steps, "pick_audio", tr("Wybierz inne źródło"), True, "audio")


def check_audio(audio) -> list[Problem]:
    if audio is None:
        return []
    if audio.kind == "process":
        return [] if _process_alive(audio.pid) else [audio_gone_problem(audio)]
    if audio.kind == "mic":
        return [audio_gone_problem(audio)] if _mic_present(audio) is False else []
    return []                 # dźwięk systemu – zawsze jest jakieś wyjście


def video_problem(video, why: str = "") -> Problem:
    win = video is not None and video.kind == "window"
    return Problem("video_gone", tr("Nie da się złapać slajdów"),
                   why or (tr("Okno „{name}” jest zamknięte albo zminimalizowane.", name=video.label) if win else
                           tr("Nie udało się zrobić zrzutu ekranu.")),
                   [tr("Otwórz okno ze slajdami i nie minimalizuj go (może być zasłonięte).") if win else
                    tr("Sprawdź, czy ekran jest podłączony i włączony."),
                    tr("Kliknij „Wybierz inne źródło”, żeby wskazać inny ekran albo okno."),
                    tr("„Nagrywaj mimo to” nagra sam dźwięk – slajdy możesz dodać później z plików.")],
                   "pick_video", tr("Wybierz inne źródło"), True, "slides")


def check_video(video) -> list[Problem]:
    if video is None or video.kind == "none":
        return []
    from .screen_capture import make_grabber
    g = make_grabber(video)
    if g is None:
        return []
    try:
        if video.kind == "window" and hasattr(g, "exists") and not g.exists():
            return [video_problem(video)]
        if video.kind == "window" and hasattr(g, "is_minimized") and g.is_minimized():
            return [video_problem(video, tr("Okno „{name}” jest zminimalizowane – zminimalizowanego okna nie "
                                            "da się nagrać.", name=video.label))]
        img = g.grab()
        if img is None or getattr(img, "size", 0) == 0:
            return [video_problem(video)]
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("Zrzut ekranu (sprawdzenie): %s", e)
        return [video_problem(video)]
    finally:
        try:
            g.close()
        except Exception:  # noqa: BLE001
            pass


def check_disk(settings) -> list[Problem]:
    try:
        free = shutil.disk_usage(settings.library_path()).free / 1024 ** 3
    except OSError:
        return []
    if free >= LOW_DISK_GB:
        return []
    crit = free < CRITICAL_DISK_GB
    return [Problem("disk", tr("Mało miejsca na dysku"),
                    tr("Zostało tylko {gb} GB w folderze biblioteki. Godzina wykładu to zwykle 50–200 MB, ale "
                       "notatki, slajdy i modele też potrzebują miejsca.", gb=i18n_gb(free)),
                    [tr("Usuń niepotrzebne pliki albo opróżnij Kosz."),
                     tr("Albo przenieś bibliotekę na inny dysk: Ustawienia → Biblioteka.")],
                    "", "", crit, "disk")]


# ---------------------------------------------------------------------------------------------- całość
def run_checks(settings, audio, video, live_notes: bool, timeout: float = CHECK_TIMEOUT,
               warm: bool = True) -> list[Problem]:
    """Wszystkie sprawdzenia naraz, łącznie najwyżej ok. timeout s. Kolejność wyniku: najpierw błędy nagrania,
    potem reszta (krytyczne przed ostrzeżeniami). warm=False – bez wstępnego ładowania modelu notatek na żywo."""
    t0 = time.monotonic()
    has_audio = audio is not None
    has_video = video is not None and getattr(video, "kind", "none") != "none"
    jobs: dict[str, Callable[[], list[Problem]]] = {"disk": lambda: check_disk(settings),
                                                     "ollama": lambda: check_ollama(settings, live_notes and has_audio,
                                                                                    has_video, warm)}
    if has_audio:
        jobs["whisper"] = lambda: check_whisper(settings)
        jobs["audio"] = lambda: check_audio(audio)
    if has_video:
        jobs["video"] = lambda: check_video(video)
    pool = ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="Healthcheck")
    futs = {pool.submit(fn): name for name, fn in jobs.items()}
    done, late = wait(futs, timeout=timeout)
    pool.shutdown(wait=False)
    out: list[Problem] = []
    for f in done:
        try:
            out += f.result()
        except Exception:  # noqa: BLE001 – błąd samego sprawdzenia, nie sprawdzanej rzeczy
            log.exception("Sprawdzenie %s", futs[f])
    if late:
        log.info("Sprawdzenia, które nie zdążyły: %s", ", ".join(futs[f] for f in late))
    order = {"audio": 0, "slides": 1, "disk": 2, "ai": 3}
    out.sort(key=lambda p: (order.get(p.area, 9), not p.critical))
    log.info("Sprawdzenie przed nagrywaniem: %.0f ms, problemy: %s", 1000 * (time.monotonic() - t0),
             ", ".join(p.key for p in out) or "brak")
    return out


def ai_only(problems: list[Problem]) -> bool:
    return bool(problems) and all(p.area == "ai" for p in problems)


# ---------------------------------------------------------------------------------------------- naprawy
def switch_to_cpu(settings) -> None:
    """Whisper tylko na procesorze; „large” na CPU jest za wolny do pracy na żywo – lżejszy model (jak profil Lekki)."""
    settings.whisper_device = "cpu"
    if settings.whisper_model.startswith("large") and not IS_MAC:
        settings.whisper_model = "small"
    settings.save()


def download_whisper(name: str, progress: Optional[Callable[[float], None]] = None,
                     cancel: Optional[threading.Event] = None) -> None:
    """Pobiera model Whispera (jak instalator); progress(0–1) z rozmiaru pobranych plików."""
    from faster_whisper.utils import download_model
    from .perf import WHISPER_GB
    from .uninstall import whisper_cached, whisper_folder
    had = whisper_cached(name)
    total = WHISPER_GB.get(name, 1.5) * 1024 ** 3
    folder = whisper_folder(name)
    err: list = []

    def run():
        try:
            download_model(name)
        except Exception as e:  # noqa: BLE001
            err.append(e)
    th = threading.Thread(target=run, name="WhisperDownload", daemon=True)
    th.start()
    while th.is_alive():
        if cancel is not None and cancel.is_set():
            return
        if progress and folder is not None:
            size = sum(f.stat().st_size for f in (folder / "blobs").glob("*") if f.is_file()) \
                if (folder / "blobs").is_dir() else 0
            progress(min(0.99, size / total))
        th.join(0.5)
    if err:
        raise err[0]
    if not had:
        from .setup.state import remember
        remember("whisper_models", name)
