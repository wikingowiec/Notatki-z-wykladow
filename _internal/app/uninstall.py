"""Odinstalowanie: usuwa to, co zainstalowała aplikacja (Ustawienia → Odinstaluj).

Co jest „nasze”, zapisuje setup.json (installer, pobieranie modeli, perf.ollama_env): ollama_installed_by_app,
ollama_models, whisper_models, env_set. Starsze instalacje nie mają tych wpisów – wtedy Ollama jest nasza tylko,
gdy pojawiła się po pierwszym starcie aplikacji (folder Ollamy młodszy niż runtime), a modele Ollamy to tylko
domyślne (Bielik 11B/4.5B, qwen3-vl 4B/8B). Cudzych rzeczy nie ruszamy.

Plik w użyciu (Python i biblioteki, na Windows także log) nie da się usunąć z działającej aplikacji – takie
foldery usuwa skrypt uruchamiany w tle, który czeka na zamknięcie aplikacji (Windows: PowerShell bez okna,
Mac: sh), a na końcu usuwa sam siebie.

Tryb próbny: WYKLADY_UNINSTALL_DRY=1 – cały ekran przechodzi normalnie, ale nic nie jest usuwane ani zatrzymywane;
do logu trafia lista tego, co by zostało usunięte (wpisy „[PRÓBA]”)."""
from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from . import ollama_local
from .i18n import gb, tr
from .perf import BIELIK_11, BIELIK_45, OLLAMA_ENV, QWEN_VL4, QWEN_VL8
from .setup import state
from .system import IS_MAC, IS_STORE, IS_WIN, app_bundle, data_dir

log = logging.getLogger(__name__)
DRY = os.environ.get("WYKLADY_UNINSTALL_DRY", "").strip() not in ("", "0")
NO_WINDOW = 0x08000000 if IS_WIN else 0
DEFAULT_OLLAMA = (BIELIK_11, BIELIK_45, QWEN_VL4, QWEN_VL8)
WHISPER_REPOS = {          # zapas, gdy nie ma faster_whisper (te same nazwy co faster_whisper.utils._MODELS)
    "large-v3": "Systran/faster-whisper-large-v3", "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "large-v2": "Systran/faster-whisper-large-v2",
    "medium": "Systran/faster-whisper-medium", "small": "Systran/faster-whisper-small",
    "base": "Systran/faster-whisper-base", "tiny": "Systran/faster-whisper-tiny"}
REGISTRY = "registry.ollama.ai"
# kolejność wykonywania (okno potwierdzenia pokazuje pozycje w kolejności ORDER_DIALOG)
ORDER = ("ollama_models", "ollama", "whisper", "library", "shortcuts", "settings", "runtime", "program")
ORDER_DIALOG = ("runtime", "whisper", "ollama_models", "ollama", "settings", "shortcuts", "program", "library")


def short_title(key: str) -> str:
    """Krótka nazwa kroku na ekranie postępu (lista w notesie)."""
    return {"runtime": tr("Python i biblioteki"), "whisper": tr("Modele mowy (Whisper)"),
            "ollama_models": tr("Modele AI (Ollama)"), "ollama": tr("Ollama"), "settings": tr("Ustawienia i log"),
            "shortcuts": tr("Skróty"), "program": tr("Pliki programu"),
            "library": tr("Notatki i nagrania")}.get(key, key)


# ---------------------------------------------------------------------------------------------- rozmiary, ścieżki
def dir_size(p: Path) -> int:
    """Rozmiar pliku albo folderu (bez wchodzenia w dowiązania)."""
    try:
        st = os.lstat(p)
    except OSError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size
    tot = 0
    stack = [str(p)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            tot += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return tot


def _born(p: Path) -> Optional[float]:
    """Czas utworzenia (Windows: st_ctime, Mac: st_birthtime); None, gdy system tego nie podaje."""
    try:
        st = p.stat()
    except OSError:
        return None
    b = getattr(st, "st_birthtime", None)
    return b if b else (st.st_ctime if IS_WIN else None)


def _user_env(name: str) -> str:
    """Zmienna użytkownika z rejestru (Windows) – Ollama uruchomiona z autostartu widzi właśnie te."""
    if not IS_WIN:
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def _shell_folder(csidl: int) -> Optional[Path]:
    """Folder powłoki Windows (pulpit, menu Start) – także przeniesiony np. do OneDrive."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------------------------- Whisper
def hf_cache() -> Path:
    for k in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(k):
            return Path(os.environ[k])
    home = os.environ.get("HF_HOME") or os.path.join(os.environ.get("XDG_CACHE_HOME") or
                                                     str(Path.home() / ".cache"), "huggingface")
    return Path(home) / "hub"


def _whisper_repo(name: str) -> str:
    try:
        from faster_whisper.utils import _MODELS
        return _MODELS.get(name) or WHISPER_REPOS.get(name, name)
    except Exception:  # noqa: BLE001
        return WHISPER_REPOS.get(name, name)


def whisper_folder(name: str) -> Optional[Path]:
    repo = _whisper_repo(name)
    if "/" not in repo or os.path.isabs(name):       # własny model z dysku – nie nasz
        return None
    return hf_cache() / ("models--" + repo.replace("/", "--"))


def whisper_cached(name: str) -> bool:
    f = whisper_folder(name)
    try:
        return f is not None and any((f / "snapshots").iterdir())
    except OSError:
        return False


# ---------------------------------------------------------------------------------------------- Ollama
def ollama_models_dir() -> Path:
    v = os.environ.get("OLLAMA_MODELS") or _user_env("OLLAMA_MODELS")
    return Path(v) if v else Path.home() / ".ollama" / "models"


def canon(name: str) -> str:
    """Nazwa modelu w jednej postaci: „qwen3-vl:8b-instruct”, „speakleash/bielik-…:q4_k_m” (bez :latest – dodany)."""
    n = (name or "").strip().lower()
    parts = n.split("/")
    host, ns = REGISTRY, "library"
    if len(parts) >= 3:
        host, ns, rest = parts[0], parts[1], "/".join(parts[2:])
    elif len(parts) == 2:
        ns, rest = parts
    else:
        rest = parts[0]
    model, _, tag = rest.partition(":")
    tag = tag or "latest"
    if host == REGISTRY:
        return f"{model}:{tag}" if ns == "library" else f"{ns}/{model}:{tag}"
    return f"{host}/{ns}/{model}:{tag}"


def installed_ollama() -> dict[str, Path]:
    """Modele Ollamy z plików na dysku (bez działającej Ollamy): nazwa (canon) → plik manifestu."""
    out: dict[str, Path] = {}
    root = ollama_models_dir() / "manifests"
    if not root.is_dir():
        return out
    for dirpath, _dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root).parts
        if len(rel) != 3:
            continue
        host, ns, model = rel
        for tag in files:
            out[canon(f"{host}/{ns}/{model}:{tag}")] = Path(dirpath) / tag
    return out


def _digests(manifest: Path) -> set[str]:
    try:
        d = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    out = {(d.get("config") or {}).get("digest", "")}
    out |= {x.get("digest", "") for x in d.get("layers") or []}
    return {x for x in out if x}


def _blob(digest: str) -> Path:
    return ollama_models_dir() / "blobs" / digest.replace(":", "-")


def ollama_targets(ours: list[str]) -> tuple[list[Path], list[Path]]:
    """(manifesty naszych modeli, bloby używane tylko przez nie) – części wspólne z cudzymi modelami zostają."""
    inst = installed_ollama()
    mine = {c: p for c, p in inst.items() if c in {canon(m) for m in ours}}
    keep: set[str] = set()
    for c, p in inst.items():
        if c not in mine:
            keep |= _digests(p)
    blobs: set[str] = set()
    for p in mine.values():
        blobs |= _digests(p)
    return list(mine.values()), [_blob(d) for d in sorted(blobs - keep) if _blob(d).exists()]


def ollama_install_dir() -> Optional[Path]:
    """Folder z programem Ollama (Windows) albo Ollama.app (Mac)."""
    exe = ollama_local.find_ollama()
    if not exe:
        return None
    p = Path(exe).resolve()
    if IS_MAC:
        app = next((x for x in p.parents if x.suffix == ".app"), None)
        return app
    return p.parent


def ollama_is_ours(marker: dict) -> bool:
    """Czy Ollamę zainstalowała aplikacja. Bez zapisanej informacji (starsze wersje): tylko gdy jest w miejscu, do
    którego instaluje ją aplikacja, i pojawiła się po pierwszym uruchomieniu aplikacji. Nie wiadomo – cudza."""
    v = marker.get("ollama_installed_by_app")
    if v is not None:
        return bool(v)
    d = ollama_install_dir()
    if d is None:
        return False
    expected = (ollama_local.MAC_APP_DIR / "Ollama.app" if IS_MAC else
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama")
    try:
        if d.resolve() != expected.resolve():
            return False
    except OSError:
        return False
    t_ollama, t_app = _born(d), _born(state.RUNTIME)
    return bool(t_ollama and t_app and t_ollama > t_app)


def _api(url: str, path: str, data: Optional[dict] = None, timeout: float = 5):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=body, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


# ---------------------------------------------------------------------------------------------- plan
@dataclass
class Item:
    key: str
    title: str
    desc: str = ""
    checked: bool = True
    enabled: bool = True            # False = pokazane tylko dla informacji (np. cudza Ollama)
    danger: bool = False
    count: int = 0                  # liczba wykładów (biblioteka)
    size: Optional[int] = None      # bajty; None = jeszcze liczone


class Plan:
    """Co da się usunąć na tym komputerze i ile to zajmuje (liczenie rozmiarów – measure(), w tle)."""

    def __init__(self, settings):
        self.s = settings
        self.marker = state.load_marker()
        legacy = not self.marker.get("tracked")
        # modele Ollamy: zapisane przez aplikację + (starsze instalacje) domyślne, o ile są pobrane
        names = list(self.marker.get("ollama_models") or [])
        if legacy:
            names += list(DEFAULT_OLLAMA)
        inst = installed_ollama()
        self.ollama_models = [m for m in dict.fromkeys(names) if canon(m) in inst]
        # modele Whispera: zapisane + (starsze instalacje) ten z instalatora i z ustawień
        wn = list(self.marker.get("whisper_models") or [])
        if legacy:
            wn += [self.marker.get("whisper") or "", getattr(settings, "whisper_model", "")]
        self.whisper = [w for w in dict.fromkeys(wn) if w and whisper_cached(w)]
        self.ollama_dir = ollama_install_dir()
        self.ollama_ours = self.ollama_dir is not None and ollama_is_ours(self.marker)
        self.root = state.BASE.parent
        self.bundle = app_bundle()
        self.lib = Path(settings.library_dir)
        try:
            from .storage import list_lectures
            self.lectures = [lec.folder for lec in list_lectures(self.lib)]
        except Exception:  # noqa: BLE001
            self.lectures = []
        self.items = self._items()

    def _items(self) -> list[Item]:
        out: dict[str, Item] = {}
        if state.RUNTIME.exists():
            out["runtime"] = Item("runtime", tr("Biblioteki aplikacji i Python"),
                                  tr("Pobrane przy pierwszym uruchomieniu (folder runtime)."))
        if self.whisper:
            out["whisper"] = Item("whisper", tr("Modele rozpoznawania mowy (Whisper)"), ", ".join(self.whisper))
        if self.ollama_models:
            out["ollama_models"] = Item("ollama_models", tr("Modele AI pobrane przez aplikację (Ollama)"),
                                        ", ".join(m.split("/")[-1] for m in self.ollama_models))
        if self.ollama_dir is not None:
            out["ollama"] = (Item("ollama", tr("Ollama"), tr("Zainstalowana przez aplikację."))
                             if self.ollama_ours else
                             Item("ollama", tr("Ollama"), tr("Była na komputerze przed aplikacją albo zainstalowano ją "
                                                             "osobno – zostaje."), checked=False, enabled=False))
        out["settings"] = Item("settings", tr("Ustawienia, log, pamięć podręczna"),
                               tr("Ustawienia aplikacji, dziennik zdarzeń i pliki tymczasowe."))
        if self._shortcuts():
            out["shortcuts"] = Item("shortcuts", tr("Skróty na pulpicie i w menu Start"))
        if self._program_targets():
            out["program"] = Item("program", tr("Pliki programu"),
                                  tr("Wykłady.app trafi do Kosza.") if IS_MAC else str(self.root))
        if self.lectures or self._library_extra():
            out["library"] = Item("library", tr("Moje notatki, nagrania i fiszki"), str(self.lib), checked=False,
                                  danger=True, count=len(self.lectures))
        return [out[k] for k in ORDER_DIALOG if k in out]

    def item(self, key: str) -> Optional[Item]:
        return next((i for i in self.items if i.key == key), None)

    # ------------------------------------------------------------------ cele poszczególnych pozycji
    def _shortcuts(self) -> list[Path]:
        if not IS_WIN or IS_STORE:
            return []
        out = []
        for csidl in (0x10, 0x02):          # CSIDL_DESKTOPDIRECTORY, CSIDL_PROGRAMS
            d = _shell_folder(csidl)
            for n in ("Wykłady.lnk", "Wykłady AI.lnk"):  # i18n: nie – nazwy plików skrótów
                if d is not None and (d / n).exists():
                    out.append(d / n)
        return out

    def _program_targets(self) -> list[Path]:
        if IS_MAC:
            return [self.bundle] if self.bundle is not None else []
        if IS_STORE or not IS_WIN:          # Store: paczkę usuwa Windows (Ustawienia → Aplikacje)
            return []
        exe = state.launcher_exe()
        if not exe.exists():
            return []
        names = (exe.name, state.BASE.name, "README.md", "README.txt", "LICENSE", "LICENSE.txt")
        return [self.root / n for n in names if (self.root / n).exists()]

    def is_dev_checkout(self) -> bool:
        """Folder z kodem (git) – plików programu nigdy nie usuwamy, nawet poza trybem próbnym."""
        return (self.root / ".git").exists()

    def _library_extra(self) -> list[Path]:
        from .study_stats import FILE
        return [p for p in (self.lib / FILE,) if p.exists()]

    def _settings_targets(self) -> list[Path]:
        out = []
        try:
            d = data_dir()
            for p in d.iterdir():
                if p.resolve() != state.RUNTIME.resolve():
                    out.append(p)
        except OSError:
            pass
        tmp = Path(tempfile.gettempdir())
        for n in ("OllamaSetup.exe", "Ollama-darwin.zip", "wyklady_skrot.ps1"):  # i18n: nie
            if (tmp / n).exists():
                out.append(tmp / n)
        return out

    def _ollama_extra(self) -> list[Path]:
        """Pozostałości po Ollamie (logi, ustawienia Ollamy) – tylko gdy Ollama jest nasza."""
        out = []
        if IS_WIN:
            p = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama"
            if p.exists():
                out.append(p)
        return out

    def measure(self, key: str) -> int:
        if key == "runtime":
            return dir_size(state.RUNTIME)
        if key == "whisper":
            return sum(dir_size(f) for f in (whisper_folder(w) for w in self.whisper) if f is not None)
        if key == "ollama_models":
            mans, blobs = ollama_targets(self.ollama_models)
            return sum(dir_size(p) for p in mans + blobs)
        if key == "ollama":
            return (dir_size(self.ollama_dir) if self.ollama_dir else 0) + sum(dir_size(p) for p in self._ollama_extra())
        if key == "settings":
            return sum(dir_size(p) for p in self._settings_targets())
        if key == "shortcuts":
            return sum(dir_size(p) for p in self._shortcuts())
        if key == "program":
            tot = 0
            for p in self._program_targets():
                if p == state.BASE:        # _internal bez runtime (runtime to osobna pozycja)
                    tot += sum(dir_size(c) for c in p.iterdir() if c.name != "runtime")
                else:
                    tot += dir_size(p)
            return tot
        if key == "library":
            return sum(dir_size(Path(f)) for f in self.lectures) + sum(dir_size(p) for p in self._library_extra())
        return 0

    def measure_all(self) -> None:
        for it in self.items:
            if it.size is None:
                it.size = self.measure(it.key)


# ---------------------------------------------------------------------------------------------- wykonanie
@dataclass
class Step:
    key: str
    title: str
    size: int
    state: str = "pending"          # pending / active / done / later (po zamknięciu aplikacji) / warn
    note: str = ""
    extra: dict = field(default_factory=dict)


class Uninstaller(QObject):
    """Kroki odinstalowania w wątku w tle. Postęp liczony z usuniętych bajtów; błąd kroku nie przerywa reszty."""
    step_changed = Signal(int, str)         # indeks kroku, stan
    progress = Signal(float, str)           # całość 0..1, opis
    completed = Signal(object)              # {"freed": bajty, "warnings": [(tytuł, opis)], "later": bool}

    def __init__(self, settings, plan: Plan, keys: list[str]):
        super().__init__()
        self.s = settings
        self.plan = plan
        self.steps = []
        for k in ORDER:
            it = plan.item(k)
            if k in keys and it is not None and it.enabled:
                self.steps.append(Step(k, short_title(k), int(it.size if it.size is not None else plan.measure(k))))
        self.total = max(1, sum(st.size for st in self.steps))
        self.done = 0.0
        self.freed = 0
        self.later: list[Path] = []         # usuwane przez skrypt po zamknięciu aplikacji
        self.rmdir_later: list[Path] = []   # foldery usuwane po zamknięciu, jeśli zostaną puste
        self._last = 0.0
        self._ollama_was_up = False
        self._ollama_stopped = False

    # ------------------------------------------------------------------ sterowanie
    def start(self):
        threading.Thread(target=self._run_all, name="odinstaluj", daemon=True).start()

    def _advance(self, nbytes: float, detail: str, force: bool = False):
        self.done += nbytes
        now = time.monotonic()
        if force or now - self._last > 0.05:
            self._last = now
            self.progress.emit(min(1.0, self.done / self.total), detail)

    def _run_all(self):
        if DRY:
            log.info("[PRÓBA] Odinstalowanie w trybie próbnym – nic nie zostanie usunięte")
        warnings = []
        for i, st in enumerate(self.steps):
            st.state = "active"
            self.step_changed.emit(i, "active")
            start = self.done
            self._advance(0, st.title + "…", force=True)
            try:
                res = getattr(self, "_do_" + st.key)(st)
                st.state = res or "done"
            except Exception as e:  # noqa: BLE001
                log.exception("odinstalowanie: krok %s", st.key)
                st.state = "warn"
                st.note = st.note or str(e)[:200]
            if st.state == "warn":
                warnings.append((st.title, st.note))
            self.done = start + st.size          # krok zamknięty – postęp równo z jego rozmiarem
            self.step_changed.emit(i, st.state)
            self._advance(0, st.title, force=True)
        self._restart_ollama()
        try:
            self._schedule_cleanup()
        except Exception as e:  # noqa: BLE001
            log.exception("skrypt sprzątający")
            warnings.append((tr("Sprzątanie po zamknięciu"), str(e)[:200]))
        self.progress.emit(1.0, tr("Gotowe"))
        self.completed.emit({"freed": self.freed, "warnings": warnings, "later": bool(self.later)})

    # ------------------------------------------------------------------ usuwanie z postępem
    def _delete(self, path: Path, detail: str, size: Optional[int] = None) -> int:
        """Usuwa plik albo folder, przesuwając postęp o usunięte bajty. Pliki w użyciu – po zamknięciu aplikacji."""
        if not os.path.lexists(path):
            return 0
        if DRY:
            return self._dry(path, detail, size)
        if not os.path.isdir(path) or os.path.islink(path):
            n = dir_size(path)
            if not self._unlink(str(path)):
                self.later.append(path)
            self._advance(n, detail)
            self.freed += n
            return n
        tot, failed = 0, 0
        for dirpath, dirnames, filenames in os.walk(path, topdown=False):
            for f in filenames:
                p = os.path.join(dirpath, f)
                try:
                    n = os.lstat(p).st_size
                except OSError:
                    n = 0
                if not self._unlink(p):
                    failed += 1
                tot += n
                self._advance(n, detail)
            for d in dirnames:
                dp = os.path.join(dirpath, d)
                try:
                    if os.path.islink(dp):
                        try:
                            os.unlink(dp)
                        except OSError:
                            os.rmdir(dp)          # dowiązanie do folderu na Windows
                    else:
                        os.rmdir(dp)
                except OSError:
                    pass
        try:
            os.rmdir(path)
        except OSError:
            pass
        if failed or path.exists():
            log.info("W użyciu (%d plików) – usunę po zamknięciu: %s", failed, path)
            self.later.append(path)
        self.freed += tot
        return tot

    @staticmethod
    def _unlink(p: str) -> bool:
        try:
            os.unlink(p)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            try:                       # plik tylko do odczytu (Windows)
                os.chmod(p, stat.S_IWRITE)
                os.unlink(p)
                return True
            except OSError:
                return False
        except OSError:
            return False

    def _dry(self, path: Path, detail: str, size: Optional[int] = None) -> int:
        """Tryb próbny: wpis do logu i postęp rozłożony na chwilę (żeby było widać cały ekran)."""
        n = dir_size(path) if size is None else size
        log.info("[PRÓBA] usunąłbym: %s (%s)", path, gb(n))
        parts = 12
        dur = min(1.6, 0.35 + n / 6e9)
        for _ in range(parts):
            time.sleep(dur / parts)
            self._advance(n / parts, detail)
        self.freed += n
        return n

    def _later(self, path: Path, detail: str, size: int) -> None:
        """Folder w użyciu (Python, pliki programu) – skrypt usunie go po zamknięciu aplikacji."""
        log.info("%susunę po zamknięciu aplikacji: %s (%s)", "[PRÓBA] " if DRY else "", path, gb(size))
        self.later.append(path)
        for _ in range(8):
            time.sleep(0.06)
            self._advance(size / 8, detail)
        self.freed += size

    # ------------------------------------------------------------------ Ollama: zwolnienie modeli i zatrzymanie
    def _stop_ollama(self):
        if self._ollama_stopped:
            return
        self._ollama_stopped = True
        url = self.s.ollama_url
        self._ollama_was_up = ollama_local.is_up(url)
        if DRY:
            log.info("[PRÓBA] zwolniłbym modele i zatrzymał Ollamę (działa: %s)", self._ollama_was_up)
            return
        if self._ollama_was_up:
            try:
                with _api(url, "/api/ps") as r:
                    loaded = [m.get("name") or m.get("model") for m in json.loads(r.read()).get("models", [])]
                for m in loaded:
                    try:
                        _api(url, "/api/generate", {"model": m, "keep_alive": 0}, timeout=15).close()
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
        if IS_WIN:
            for name in ("ollama app.exe", "ollama.exe"):  # i18n: nie
                subprocess.run(["taskkill", "/F", "/T", "/IM", name], capture_output=True, creationflags=NO_WINDOW,
                               timeout=20)
        elif IS_MAC:
            subprocess.run(["/usr/bin/osascript", "-e", 'if application "Ollama" is running then tell application '
                            '"Ollama" to quit'], capture_output=True, timeout=15)
            subprocess.run(["/usr/bin/pkill", "-x", "ollama"], capture_output=True, timeout=10)
        for _ in range(20):
            if not ollama_local.is_up(url, timeout=0.5):
                break
            time.sleep(0.5)
        time.sleep(1.0)                 # system zwalnia uchwyty plików

    def _restart_ollama(self):
        """Ollama zostaje na komputerze, a działała przed odinstalowaniem – uruchom ją z powrotem."""
        if DRY or not self._ollama_was_up or any(st.key == "ollama" for st in self.steps):
            return
        try:
            ollama_local.start(self.s.ollama_url, wait=10)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ kroki
    def _do_ollama_models(self, st: Step):
        self.progress.emit(min(1.0, self.done / self.total), tr("Zatrzymuję Ollamę i zwalniam modele…"))
        self._stop_ollama()
        mans, blobs = ollama_targets(self.plan.ollama_models)
        for p in blobs:
            self._delete(p, tr("Usuwam modele AI…"))
        for p in mans:
            self._delete(p, tr("Usuwam modele AI…"))
            if not DRY:                 # puste foldery po manifeście (…/manifests/host/ns/model)
                d = p.parent
                for _ in range(3):
                    try:
                        d.rmdir()
                    except OSError:
                        break
                    d = d.parent
        log.info("Usunięte modele Ollamy: %s", ", ".join(self.plan.ollama_models))
        return "done"

    def _do_ollama(self, st: Step):
        d = self.plan.ollama_dir
        if d is None or not self.plan.ollama_ours:
            return "done"
        self._stop_ollama()
        if IS_MAC:
            self.progress.emit(min(1.0, self.done / self.total), tr("Przenoszę Ollamę do Kosza…"))
            n = dir_size(d) if not DRY else st.size
            if DRY:
                self._dry(d, tr("Przenoszę Ollamę do Kosza…"), n)
            else:
                trash(d)
                self._advance(n, tr("Przenoszę Ollamę do Kosza…"))
                self.freed += n
        else:
            self._uninstall_ollama_win(d, st)
        for p in self.plan._ollama_extra():
            self._delete(p, tr("Usuwam pozostałości Ollamy…"))
        # folder z modelami Ollamy (~/.ollama): gdy nie zostały w nim żadne modele – razem z kluczami Ollamy
        home = Path.home() / ".ollama"
        if home.exists() and not installed_ollama() and ollama_models_dir().is_relative_to(home):
            self._delete(home, tr("Usuwam pozostałości Ollamy…"))
        return "done"

    def _uninstall_ollama_win(self, d: Path, st: Step):
        unins = next(iter(sorted(d.glob("unins*.exe"))), None)
        before = dir_size(d) if not DRY else st.size
        detail = tr("Odinstalowuję Ollamę…")
        if DRY:
            log.info("[PRÓBA] uruchomiłbym deinstalator Ollamy: %s", unins or "(brak – usunięcie folderu)")
            self._dry(d, detail, before)
            return
        if unins is None:
            self._delete(d, detail)
            return
        subprocess.Popen([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], creationflags=NO_WINDOW,
                         close_fds=True)
        # deinstalator Inno Setup kopiuje się do %TEMP% i działa dalej sam – postęp z tego, ile zostało w folderze
        t0, gone = time.monotonic(), 0
        while time.monotonic() - t0 < 240:
            left = dir_size(d) if d.exists() else 0
            step = max(0, before - left) - gone
            if step > 0:
                gone += step
                self._advance(step, detail)
            if not d.exists() or left == 0:
                break
            time.sleep(0.5)
        self.freed += gone
        if d.exists() and dir_size(d) > 0:
            st.note = tr("Deinstalator Ollamy nie skończył – usuń Ollamę w Ustawieniach Windows → Aplikacje.")
            raise RuntimeError(st.note)

    def _do_whisper(self, st: Step):
        for w in self.plan.whisper:
            f = whisper_folder(w)
            if f is not None:
                self._delete(f, tr("Usuwam model mowy {x}…", x=w))
                lock = hf_cache() / ".locks" / f.name
                if lock.exists():
                    self._delete(lock, tr("Usuwam model mowy {x}…", x=w))
        return "done"

    def _do_library(self, st: Step):
        for f in self.plan.lectures:
            self._delete(Path(f), tr("Usuwam wykład: {x}", x=Path(f).name))
        for p in self.plan._library_extra():
            self._delete(p, tr("Usuwam notatki…"))
        if not DRY:
            try:
                self.plan.lib.rmdir()          # tylko gdy nic innego w nim nie zostało
            except OSError:
                pass
        return "done"

    def _do_shortcuts(self, st: Step):
        for p in self.plan._shortcuts():
            self._delete(p, tr("Usuwam skróty…"))
        return "done"

    def _do_settings(self, st: Step):
        for p in self.plan._settings_targets():
            self._delete(p, tr("Usuwam ustawienia i log…"))
        d = data_dir()
        # log i ustawienia zapisują się jeszcze przy zamykaniu – skrypt sprząta je jeszcze raz po zamknięciu
        for p in self.plan._settings_targets():
            if p.parent == d and p not in self.later:
                self.later.append(p)
        self.rmdir_later.append(d)
        self._remove_env()
        return "done"

    def _remove_env(self):
        """Zmienne OLLAMA_* – tylko te, które ustawiła aplikacja (i tylko gdy mają wciąż naszą wartość)."""
        names = [n for n in (self.plan.marker.get("env_set") or []) if n in OLLAMA_ENV]
        if not names:
            return
        if DRY:
            log.info("[PRÓBA] usunąłbym zmienne środowiskowe: %s", ", ".join(names))
            return
        if IS_WIN:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                                    winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                    for n in names:
                        try:
                            if str(winreg.QueryValueEx(k, n)[0]) == OLLAMA_ENV[n]:
                                winreg.DeleteValue(k, n)
                        except OSError:
                            pass
                from .perf import broadcast_env
                broadcast_env()
            except Exception:  # noqa: BLE001
                log.exception("zmienne środowiskowe")
        elif IS_MAC:
            for n in names:
                subprocess.run(["/bin/launchctl", "unsetenv", n], capture_output=True, timeout=5)
        log.info("Usunięte zmienne środowiskowe: %s", ", ".join(names))

    def _do_runtime(self, st: Step):
        # Python z bibliotekami jest teraz w użyciu – usunie go skrypt po zamknięciu aplikacji
        self._later(state.RUNTIME, tr("Python i biblioteki usuną się po zamknięciu aplikacji"), st.size)
        if IS_STORE or IS_MAC:
            self.rmdir_later.append(state.RUNTIME.parent)
        return "later"

    def _do_program(self, st: Step):
        if self.plan.is_dev_checkout():
            st.note = tr("To folder z kodem źródłowym (git) – pliki programu zostają.")
            log.warning("Pominięto pliki programu – folder z kodem (git): %s", self.plan.root)
            return "warn"
        if IS_MAC:
            b = self.plan.bundle
            if b is None:
                return "done"
            if DRY:
                self._dry(b, tr("Przenoszę Wykłady.app do Kosza…"), st.size)
            else:
                trash(b)
                self._advance(st.size, tr("Przenoszę Wykłady.app do Kosza…"))
                self.freed += st.size
            return "done"
        targets = self.plan._program_targets()
        for p in targets:
            log.info("%susunę po zamknięciu aplikacji: %s", "[PRÓBA] " if DRY else "", p)
        self.later.extend(targets)
        self.rmdir_later.append(self.plan.root)
        for _ in range(8):
            time.sleep(0.06)
            self._advance(st.size / 8, tr("Pliki programu usuną się po zamknięciu aplikacji"))
        self.freed += st.size
        return "later"

    # ------------------------------------------------------------------ sprzątanie po zamknięciu
    def _schedule_cleanup(self):
        later = list(dict.fromkeys(str(p) for p in self.later))
        dirs = list(dict.fromkeys(str(p) for p in self.rmdir_later))
        if not later and not dirs:
            return
        pid = os.getpid()
        if IS_WIN:
            script = _ps_script(pid, later, dirs)
            name = "wyklady_odinstaluj.ps1"  # i18n: nie
        else:
            script = _sh_script(pid, later, dirs)
            name = "wyklady_odinstaluj.sh"  # i18n: nie
        if DRY:
            log.info("[PRÓBA] skrypt po zamknięciu aplikacji (nie uruchomiony):\n%s", script)
            return
        f = Path(tempfile.gettempdir()) / name
        f.write_text(script, encoding="utf-8-sig" if IS_WIN else "utf-8")
        tmp = tempfile.gettempdir()
        if IS_WIN:
            args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(f)]
            base = NO_WINDOW | 0x00000200           # CREATE_NEW_PROCESS_GROUP
            try:        # wersja ze Store: proces poza zadaniem paczki, żeby przeżył zamknięcie aplikacji
                subprocess.Popen(args, cwd=tmp, creationflags=base | 0x01000000, close_fds=True)
            except OSError:
                subprocess.Popen(args, cwd=tmp, creationflags=base, close_fds=True)
        else:
            os.chmod(f, 0o700)
            subprocess.Popen(["/bin/sh", str(f)], cwd=tmp, start_new_session=True, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("Skrypt sprzątający po zamknięciu: %s", f)


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _ps_script(pid: int, paths: list[str], dirs: list[str]) -> str:
    """PowerShell: czeka na zamknięcie aplikacji, usuwa foldery (z ponawianiem – pliki zwalniają się chwilę),
    usuwa puste foldery nadrzędne, na końcu sam siebie."""
    p = ", ".join(_ps_quote(x) for x in paths) or ""
    d = ", ".join(_ps_quote(x) for x in dirs) or ""
    # i18n: nie – skrypt PowerShell
    return f"""$ErrorActionPreference = 'SilentlyContinue'
try {{ Wait-Process -Id {pid} }} catch {{}}
Start-Sleep -Seconds 1
$paths = @({p})
foreach ($x in $paths) {{
  for ($i = 0; $i -lt 30 -and (Test-Path -LiteralPath $x); $i++) {{
    if (Test-Path -LiteralPath $x -PathType Container) {{ & cmd.exe /d /c rd /s /q "$x" | Out-Null }}
    if (Test-Path -LiteralPath $x) {{ Remove-Item -LiteralPath $x -Recurse -Force }}
    if (Test-Path -LiteralPath $x) {{ Start-Sleep -Seconds 1 }}
  }}
}}
$dirs = @({d})
foreach ($x in $dirs) {{
  if ((Test-Path -LiteralPath $x) -and -not (Get-ChildItem -LiteralPath $x -Force)) {{ Remove-Item -LiteralPath $x -Force }}
}}
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force
"""


def _sh_script(pid: int, paths: list[str], dirs: list[str]) -> str:
    rm = "\n".join(f"rm -rf {shlex.quote(x)}" for x in paths)
    rd = "\n".join(f"rmdir {shlex.quote(x)} 2>/dev/null" for x in dirs)
    # i18n: nie – skrypt sh
    return f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
sleep 1
{rm}
{rd}
rm -f "$0"
"""


def trash(p: Path) -> None:
    """Mac: do Kosza (Finder pozwoli przywrócić). Zapas: przeniesienie do ~/.Trash."""
    try:
        from Foundation import NSFileManager, NSURL
        ok, _url, _err = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            NSURL.fileURLWithPath_(str(p)), None, None)
        if ok:
            return
    except Exception:  # noqa: BLE001
        pass
    dst = Path.home() / ".Trash" / p.name
    k = 1
    while dst.exists():
        dst = dst.with_name(f"{p.stem} {k}{p.suffix}")
        k += 1
    shutil.move(str(p), str(dst))
