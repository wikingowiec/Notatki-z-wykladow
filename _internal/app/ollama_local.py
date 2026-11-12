"""Lokalna Ollama: gdzie jest program i uruchomienie serwera, gdy nie działa (bez zewnętrznych bibliotek).
Nowe w wersji 2.2.0.

Windows: instalator Ollamy sam dodaje ją do autostartu. Mac: aplikacja pobiera Ollama.app do ~/Applications i przy
każdym starcie uruchamia „ollama serve”, jeśli serwer nie odpowiada (np. po ponownym uruchomieniu komputera)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW
MAC_APP_DIR = Path.home() / "Applications"                     # bez uprawnień administratora


def candidates() -> list[Path]:
    if sys.platform == "darwin":
        # aplikacje z Findera mają krótki PATH (bez Homebrew) – sprawdzamy typowe miejsca wprost
        return [MAC_APP_DIR / "Ollama.app" / "Contents" / "Resources" / "ollama",
                Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama")]
    return [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe"]


def find_ollama() -> Optional[str]:
    p = shutil.which("ollama")
    if p:
        return p
    for c in candidates():
        if c.exists():
            return str(c)
    return None


def is_up(url: str = "http://localhost:11434", timeout: float = 2) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def start(url: str = "http://localhost:11434", wait: float = 20, exe: Optional[str] = None) -> bool:
    """Uruchamia „ollama serve” w tle (jeśli serwer nie odpowiada) i czeka, aż wstanie. True = działa."""
    if is_up(url):
        return True
    exe = exe or find_ollama()
    if not exe:
        return False
    from .perf import ollama_env
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = NO_WINDOW | 0x00000008          # DETACHED_PROCESS
    else:
        kw["start_new_session"] = True                        # działa dalej po zamknięciu aplikacji (jak Ollama.app)
    # Ollama działa dalej po zamknięciu aplikacji, więc w wersji ze Store nie może trzymać nic otwartego w folderach
    # paczki (log w folderze danych, bieżący folder w WindowsApps) – inaczej Windows nie usunie danych paczki przy
    # odinstalowaniu i nie zainstaluje jej ponownie (błąd 0x80073D05)
    from .system import IS_STORE, data_dir
    try:
        log_dir = Path(tempfile.gettempdir()) if IS_STORE else data_dir()
        out = open(log_dir / "ollama.log", "ab")
    except OSError:
        out = subprocess.DEVNULL
    try:
        subprocess.Popen([exe, "serve"], stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         env=ollama_env(), close_fds=True, cwd=str(Path.home()), **kw)
    except OSError as e:
        log.warning("Nie udało się uruchomić Ollamy (%s): %s", exe, e)
        return False
    finally:
        if out is not subprocess.DEVNULL:
            out.close()           # proces ma własną kopię uchwytu
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        if is_up(url, timeout=1):
            log.info("Uruchomiono Ollamę: %s", exe)
            return True
        time.sleep(0.5)
    return is_up(url)


def quick_is_up(url: str = "http://localhost:11434", timeout: float = 2) -> bool:
    """Jak is_up, ale szybko, gdy Ollama nie działa (nowe w 2.3). Na Windows odmowa połączenia na localhost trwa
    ok. 2 s (system ponawia próbę), więc najpierw patrzymy na listę procesów: bez procesu „ollama…” od razu False."""
    if sys.platform == "win32":
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1"):
            try:
                from .audio_capture import process_table
                table = process_table()
            except Exception:  # noqa: BLE001
                table = []
            if table and not any(exe.lower().startswith("ollama") for _p, _pp, exe in table):
                return False
    return is_up(url, timeout)
