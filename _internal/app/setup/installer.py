"""Kroki przygotowania aplikacji (w tle, bez okien konsoli): biblioteki, model mowy, Ollama, modele AI, skrót.

Każdy krok sam sprawdza, czy jest potrzebny – ten sam kod robi pierwszą instalację i doinstalowanie
bibliotek po aktualizacji. Postęp liczony jest z pobieranych bajtów (wagi = przybliżone rozmiary w GB)."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from . import state
from ..perf import MODEL_GB, WHISPER_GB

log = logging.getLogger(__name__)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"


class Cancelled(Exception):
    pass


@dataclass
class Step:
    key: str
    title: str
    weight: float                  # przybliżony rozmiar w GB
    run: Callable
    frac: float = 0.0
    state: str = "pending"         # pending / active / done / warn / skipped
    note: str = ""
    extra: dict = field(default_factory=dict)


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f}".replace(".", ",") + " GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


class Installer(QObject):
    step_changed = Signal(int, str)            # indeks kroku, stan
    progress = Signal(float, str)              # całość 0..1, opis
    failed = Signal(str)
    completed = Signal()

    def __init__(self, settings):
        super().__init__()
        self.s = settings
        self.cancel = threading.Event()
        self._proc: Optional[subprocess.Popen] = None
        m = state.load_marker()
        self.marker = m
        models = self._models()
        self.steps = [
            Step("pip", "Biblioteki aplikacji", 2.6 if m.get("req_hash") != state.req_hash() else 0.02, self._pip),
            Step("whisper", "Model rozpoznawania mowy",
                 0.02 if m.get("whisper") == self.s.whisper_model else WHISPER_GB.get(self.s.whisper_model, 1.5),
                 self._whisper),
            Step("ollama", "Ollama – lokalne AI", 0.02 if m.get("ai_done") else 1.0, self._ollama),
            Step("models", "Modele AI do notatek",
                 0.02 if m.get("ai_done") else sum(self._model_gb(x) for x in models), self._models_step),
            Step("shortcut", "Skrót na pulpicie", 0.02, self._shortcut),
        ]

    # ------------------------------------------------------------------ sterowanie
    def start(self):
        threading.Thread(target=self._run_all, name="setup", daemon=True).start()

    def stop(self):
        self.cancel.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    def overall(self) -> float:
        tot = sum(st.weight for st in self.steps) or 1.0
        return sum(st.weight * (1.0 if st.state in ("done", "warn", "skipped") else st.frac) for st in self.steps) / tot

    def _report(self, i: int, frac: float, detail: str):
        self.steps[i].frac = max(0.0, min(1.0, frac))
        self.progress.emit(self.overall(), detail)

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def _run_all(self):
        for i, st in enumerate(self.steps):
            try:
                self._check()
                st.state = "active"
                self.step_changed.emit(i, "active")
                self._report(i, 0.0, st.title + "…")
                res = st.run(i)
                st.state = res or "done"
                st.frac = 1.0
                self.step_changed.emit(i, st.state)
                self._report(i, 1.0, st.title)
            except Cancelled:
                return
            except Exception as e:  # noqa: BLE001
                log.exception("krok %s", st.key)
                if st.key == "pip":          # bez bibliotek aplikacja nie ruszy
                    st.state = "pending"
                    self.step_changed.emit(i, "error")
                    self.failed.emit(self._friendly(e))
                    return
                st.state = "warn"             # reszta dociągnie się później (np. model przy pierwszych notatkach)
                st.note = str(e)[:200]
                self.step_changed.emit(i, "warn")
        state.save_marker(complete=True, req_hash=state.req_hash(), version=self._version())
        self.progress.emit(1.0, "Gotowe")
        self.completed.emit()

    @staticmethod
    def _version() -> str:
        try:
            from ..version import VERSION
            return VERSION
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _friendly(e: Exception) -> str:
        t = str(e)
        if "getaddrinfo" in t or "Temporary failure" in t or "NewConnectionError" in t or "urlopen error" in t:
            return "Brak połączenia z internetem. Sprawdź sieć i spróbuj ponownie."
        if "No space" in t or "Errno 28" in t:
            return "Za mało miejsca na dysku. Zwolnij kilka GB i spróbuj ponownie."
        return t[-600:]

    # ------------------------------------------------------------------ pomocnicze
    def _run_proc(self, args: list, on_line: Optional[Callable[[str], None]] = None, cwd=None) -> int:
        self._check()
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd,
                             creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace", bufsize=1,
                             env={**os.environ, "PYTHONUTF8": "1", "PIP_NO_COLOR": "1"})
        self._proc = p
        tail: list[str] = []
        for line in p.stdout:
            if self.cancel.is_set():
                p.kill()
                raise Cancelled()
            line = line.rstrip()
            tail = (tail + [line])[-25:]
            if on_line and line:
                on_line(line)
        rc = p.wait()
        self._proc = None
        if rc != 0:
            raise RuntimeError("\n".join(x for x in tail if x.strip())[-800:] or f"kod błędu {rc}")
        return rc

    def _download(self, url: str, dest: Path, on_bytes: Callable[[int, int], None]):
        req = urllib.request.Request(url, headers={"User-Agent": "Wyklady"})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                self._check()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                on_bytes(done, total)

    # ------------------------------------------------------------------ 1. biblioteki
    def _pip(self, i: int):
        if self.marker.get("req_hash") == state.req_hash():
            return "done"
        py = state.python_console()
        seen = {"total": 0.0, "cur": 0.0, "cur_total": 0.0, "name": ""}
        est = 2.6e9

        def on_line(line: str):
            m = re.match(r"Collecting ([\w.\-\[\]]+)", line)
            if m:
                seen["name"] = m.group(1).split("[")[0]
                self._report(i, (seen["total"] + seen["cur"]) / max(est, seen["total"] + 1),
                             f"Sprawdzam: {seen['name']}")
                return
            m = re.match(r"\s*Downloading \S+ \(([\d.]+) (kB|MB|GB)\)", line)
            if m:
                seen["total"] += seen["cur_total"]
                size = float(m.group(1)) * {"kB": 1e3, "MB": 1e6, "GB": 1e9}[m.group(2)]
                seen["cur_total"], seen["cur"] = size, 0.0
                return
            m = re.match(r"Progress (\d+) of (\d+)", line)
            if m:
                seen["cur"] = float(m.group(1))
                done = seen["total"] + seen["cur"]
                self._report(i, min(0.95, done / max(est, done + 1)),
                             f"Pobieram biblioteki: {seen['name']} · {_gb(seen['cur'])} z {_gb(float(m.group(2)))}")
                return
            if line.startswith("Installing collected packages"):
                self._report(i, 0.96, "Instaluję biblioteki…")

        base = [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
                "--progress-bar", "raw"]
        req = self._requirements()
        try:
            self._run_proc(base + ["-r", req], on_line, cwd=str(state.BASE))
        except RuntimeError as e:
            if "--progress-bar" in str(e) and "invalid choice" in str(e):     # stary pip bez trybu „raw”
                base.remove("--progress-bar")
                base.remove("raw")
                self._run_proc(base + ["-r", req], on_line, cwd=str(state.BASE))
            else:
                raise
        try:
            self._report(i, 0.98, "Odczyt tekstu ze slajdów (OCR)…")
            self._run_proc(base + ["-r", str(state.BASE / "requirements-ocr.txt")], None, cwd=str(state.BASE))
        except Exception as e:  # noqa: BLE001
            log.warning("OCR niedostępny: %s", e)
        import importlib
        importlib.invalidate_caches()
        state.save_marker(req_hash=state.req_hash())
        return "done"

    def _requirements(self) -> str:
        """requirements.txt – bez bibliotek CUDA (ok. 1,4 GB), gdy w komputerze nie ma karty NVIDIA."""
        src = state.BASE / "requirements.txt"
        from ..perf import has_nvidia, hardware
        try:
            if has_nvidia(hardware(self.s)):
                return str(src)
            lines = [x for x in src.read_text(encoding="utf-8").splitlines() if not x.strip().startswith("nvidia-")]
            dst = state.RUNTIME / "requirements-cpu.txt"
            dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return str(dst)
        except Exception:  # noqa: BLE001
            return str(src)

    # ------------------------------------------------------------------ 2. model mowy
    def _whisper(self, i: int):
        name = self.s.whisper_model
        if self.marker.get("whisper") == name:
            return "done"
        from faster_whisper.utils import _MODELS, download_model
        try:
            download_model(name, local_files_only=True)
            state.save_marker(whisper=name)
            return "done"
        except Exception:  # noqa: BLE001
            pass
        repo = _MODELS.get(name, name)
        total = 3.1e9
        try:
            from huggingface_hub import HfApi
            info = HfApi().model_info(repo, files_metadata=True)
            total = float(sum((s.size or 0) for s in info.siblings)) or total
        except Exception:  # noqa: BLE001
            pass
        try:
            from huggingface_hub.constants import HF_HUB_CACHE
            folder = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))
        except Exception:  # noqa: BLE001
            folder = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo.replace("/", "--"))
        err: list = []
        t = threading.Thread(target=lambda: self._safe(lambda: download_model(name), err), daemon=True)
        t.start()
        while t.is_alive():
            self._check()
            size = _dir_size(folder / "blobs")
            self._report(i, min(0.99, size / total), f"Pobieram model rozpoznawania mowy · {_gb(size)} z {_gb(total)}")
            time.sleep(0.5)
        if err:
            raise err[0]
        state.save_marker(whisper=name)
        return "done"

    @staticmethod
    def _safe(fn, err: list):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            err.append(e)

    # ------------------------------------------------------------------ 3. Ollama
    @staticmethod
    def find_ollama() -> Optional[str]:
        p = shutil.which("ollama")
        if p:
            return p
        for c in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                  Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe"):
            if c.exists():
                return str(c)
        return None

    def _api(self, path: str, data: Optional[dict] = None, timeout: float = 5):
        url = self.s.ollama_url.rstrip("/") + path
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    def _ollama_up(self) -> bool:
        try:
            with self._api("/api/version", timeout=2) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    def _ollama(self, i: int):
        from ..perf import ollama_env
        ollama_env()                  # zmienne przed instalacją – Ollama wystartuje już z nimi
        exe = self.find_ollama()
        if not exe:
            import tempfile
            dest = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
            self._download(OLLAMA_SETUP_URL, dest, lambda d, t: self._report(
                i, 0.85 * d / t if t else 0.3, f"Pobieram Ollamę · {_gb(d)}" + (f" z {_gb(t)}" if t else "")))
            self._report(i, 0.9, "Instaluję Ollamę…")
            self._run_proc([str(dest), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES", "/SP-"])
            for _ in range(20):
                exe = self.find_ollama()
                if exe:
                    break
                time.sleep(1)
            if not exe:
                raise RuntimeError("Nie udało się zainstalować Ollamy – pobierz ją z ollama.com/download.")
        if not self._ollama_up():
            self._report(i, 0.95, "Uruchamiam Ollamę…")
            from ..perf import ollama_env
            subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ollama_env(),
                             creationflags=NO_WINDOW | (0x00000008 if sys.platform == "win32" else 0))
            for _ in range(40):
                if self._ollama_up():
                    break
                self._check()
                time.sleep(0.5)
        if not self._ollama_up():
            raise RuntimeError("Ollama nie odpowiada.")
        return "done"

    # ------------------------------------------------------------------ 4. modele AI
    def _models(self) -> list[str]:
        out = [self.s.ollama_model] + ([self.s.live_model] if getattr(self.s, "live_notes", True) else [])
        if getattr(self.s, "describe_slides", True) and getattr(self.s, "vision_model", ""):
            out.append(self.s.vision_model)
        return [m for m in dict.fromkeys(out) if m]

    @staticmethod
    def _model_gb(name: str) -> float:
        low = name.lower()
        return next((v for k, v in MODEL_GB.items() if k in low), 5.0)

    def _installed(self) -> set[str]:
        try:
            with self._api("/api/tags", timeout=5) as r:
                return {m["name"] for m in json.loads(r.read()).get("models", [])}
        except Exception:  # noqa: BLE001
            return set()

    def _models_step(self, i: int):
        if self.marker.get("ai_done"):
            return "done"
        if not self._ollama_up():
            raise RuntimeError("Ollama nie działa – modele pobiorą się przy pierwszych notatkach.")
        models = self._models()
        have = self._installed()
        todo = [m for m in models if m not in have and f"{m}:latest" not in have]
        weights = [self._model_gb(m) for m in todo]
        tot = sum(weights) or 1.0
        done_w = 0.0
        problems = []
        for m, w in zip(todo, weights):
            short = m.split("/")[-1]
            try:
                with self._api("/api/pull", {"model": m, "stream": True}, timeout=60) as r:
                    for raw in r:
                        self._check()
                        if not raw.strip():
                            continue
                        d = json.loads(raw)
                        if "error" in d:
                            raise RuntimeError(d["error"])
                        total, comp = d.get("total") or 0, d.get("completed") or 0
                        f = comp / total if total else 0.0
                        big = total > 2e8
                        det = f"Pobieram model {short}" + (f" · {_gb(comp)} z {_gb(total)}" if big else "…")
                        self._report(i, (done_w + w * (f if big else 0.02)) / tot, det)
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("model %s: %s", m, e)
                problems.append(short)
            done_w += w
        if problems:
            raise RuntimeError("Nie pobrano: " + ", ".join(problems) + " – pobiorą się przy pierwszych notatkach.")
        state.save_marker(ai_done=True)
        return "done"

    # ------------------------------------------------------------------ 5. skrót
    def _shortcut(self, i: int):
        if sys.platform != "win32":
            return "skipped"
        exe = state.launcher_exe()
        if not exe.exists():
            return "skipped"
        create_shortcuts(exe)
        return "done"


def create_shortcuts(exe: Path) -> None:
    """Skrót „Wykłady” na pulpicie i w menu Start (PowerShell bez okna)."""
    import tempfile
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
  if (-not $dir) {{ continue }}
  $old = Join-Path $dir 'Wykłady AI.lnk'
  if (Test-Path $old) {{ Remove-Item $old -Force }}
  $s = $ws.CreateShortcut((Join-Path $dir 'Wykłady.lnk'))
  $s.TargetPath = '{str(exe).replace("'", "''")}'
  $s.WorkingDirectory = '{str(exe.parent).replace("'", "''")}'
  $s.IconLocation = '{str(exe).replace("'", "''")},0'
  $s.Description = 'Wykłady – notatki z wykładów'
  $s.Save()
}}
"""
    f = Path(tempfile.gettempdir()) / "wyklady_skrot.ps1"
    f.write_text(ps, encoding="utf-8-sig")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(f)],
                   creationflags=NO_WINDOW, timeout=60, capture_output=True)


def _dir_size(p: Path) -> float:
    tot = 0
    try:
        for f in p.iterdir():
            try:
                tot += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return float(tot)
