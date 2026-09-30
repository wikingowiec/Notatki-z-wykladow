"""Aktualizacje z GitHuba: sprawdzenie wersji, pobranie, podmiana plików, ponowne uruchomienie.

Źródło (w tej kolejności):
  1. najnowszy „Release” repozytorium (tag v2.1.0) – paczka źródeł z GitHuba albo załączony plik .zip,
  2. gdy wydań nie ma – plik _internal/app/version.py w gałęzi main i archiwum tej gałęzi.

Podmieniane są pliki programu (Wykłady.exe i _internal, bez _internal/runtime – tam jest Python i biblioteki).
Notatki (Dokumenty/Wykłady) i ustawienia (%APPDATA%) leżą gdzie indziej, więc aktualizacja ich nie dotyka.
Jeśli nowa wersja potrzebuje nowych bibliotek, po restarcie pojawi się ekran z notesem i je doinstaluje."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import version

log = logging.getLogger(__name__)
INTERNAL = Path(__file__).resolve().parents[1]
ROOT = INTERNAL.parent
EXE = "Wykłady.exe"
KEEP = {"runtime", "__pycache__"}


@dataclass
class UpdateInfo:
    version: str
    notes: str
    url: str
    source: str        # release / branch


def repo_of(settings) -> str:
    r = (getattr(settings, "update_repo", "") or version.REPO or "").strip()
    r = re.sub(r"^https?://github\.com/", "", r).strip("/")
    r = re.sub(r"\.git$", "", r)
    return r if re.fullmatch(r"[\w.\-]+/[\w.\-]+", r) else ""


def parse(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4]) or (0,)


def newer(remote: str, local: Optional[str] = None) -> bool:
    return parse(remote) > parse(local or version.VERSION)


def _get(url: str, timeout: float = 15, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Wyklady-updater", "Accept": accept,
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(repo: str) -> Optional[UpdateInfo]:
    """Najnowsza wersja w repozytorium (None = nie ma nowszej). Wyjątek = problem z siecią/repozytorium."""
    if not repo:
        raise RuntimeError("Nie ustawiono repozytorium na GitHubie (np. „uzytkownik/wyklady”).")
    try:
        rel = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest"))
        tag = rel.get("tag_name", "")
        url = rel.get("zipball_url", "")
        for a in rel.get("assets", []):
            if a.get("name", "").lower().endswith(".zip"):
                url = a.get("browser_download_url", url)
                break
        info = UpdateInfo(tag.lstrip("vV"), rel.get("body") or "", url, "release")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise RuntimeError(f"GitHub odpowiedział błędem {e.code}.") from e
        path = "_internal/app/version.py"
        try:   # API nie ma kilkuminutowego opóźnienia jak raw.githubusercontent.com
            raw = _get(f"https://api.github.com/repos/{repo}/contents/{path}?ref={version.BRANCH}",
                       accept="application/vnd.github.raw").decode("utf-8")
        except Exception:  # noqa: BLE001
            raw = _get(f"https://raw.githubusercontent.com/{repo}/{version.BRANCH}/{path}").decode("utf-8")
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', raw)
        if not m:
            raise RuntimeError("W repozytorium nie ma pliku _internal/app/version.py.")
        info = UpdateInfo(m.group(1), "", f"https://github.com/{repo}/archive/refs/heads/{version.BRANCH}.zip", "branch")
    return info if newer(info.version) else None


def download(info: UpdateInfo, progress: Optional[Callable[[int, int], None]] = None,
             cancel: Optional[threading.Event] = None) -> Path:
    dest = Path(tempfile.gettempdir()) / f"wyklady-{info.version}.zip"
    req = urllib.request.Request(info.url, headers={"User-Agent": "Wyklady-updater"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise RuntimeError("Anulowano.")
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return dest


def can_update() -> tuple[bool, str]:
    if not (ROOT / EXE).exists() or not (INTERNAL / "main.py").exists():
        return False, ("Aktualizacja działa w wersji zainstalowanej z Wykłady.exe (folder z plikiem Wykłady.exe "
                       "i podfolderem _internal).")
    probe = INTERNAL / ".zapis_test"
    try:
        probe.write_text("x")
        probe.unlink()
    except OSError:
        return False, "Brak uprawnień do zapisu w folderze aplikacji – przenieś go np. do Dokumentów."
    return True, ""


def apply(zip_path: Path) -> None:
    """Rozpakowuje i podmienia pliki programu. Bezpieczne: najpierw rozpakowanie w całości, potem kopiowanie."""
    ok, why = can_update()
    if not ok:
        raise RuntimeError(why)
    tmp = Path(tempfile.mkdtemp(prefix="wyklady-upd-"))
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        src = next((p.parent.parent for p in tmp.rglob("main.py") if p.parent.name == "_internal"), None)
        if src is None or not (src / "_internal" / "app").is_dir():
            raise RuntimeError("Pobrana paczka nie wygląda na aplikację Wykłady (brak _internal/app).")
        new_int = src / "_internal"
        # 1. pliki programu
        for item in new_int.iterdir():
            if item.name in KEEP:
                continue
            target = INTERNAL / item.name
            if item.is_dir():
                _sync_dir(item, target)
            else:
                shutil.copy2(item, target)
        # 2. program startowy (działający plik można przemianować, ale nie nadpisać)
        new_exe = src / EXE
        if new_exe.exists():
            cur = ROOT / EXE
            old = ROOT / (EXE + ".old")
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass
            if cur.exists():
                os.replace(cur, old)
            shutil.copy2(new_exe, cur)
        for extra in ("README.md",):
            if (src / extra).exists():
                shutil.copy2(src / extra, ROOT / extra)
        log.info("Zaktualizowano z %s", zip_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass


def _sync_dir(src: Path, dst: Path) -> None:
    """Kopiuje folder; pliki .py, których w nowej wersji już nie ma, usuwa (żeby nie zostały stare moduły)."""
    dst.mkdir(parents=True, exist_ok=True)
    names = set()
    for item in src.iterdir():
        if item.name in KEEP:
            continue
        names.add(item.name)
        t = dst / item.name
        if item.is_dir():
            _sync_dir(item, t)
        else:
            shutil.copy2(item, t)
    for old in dst.iterdir():
        if old.name not in names and old.suffix == ".py":
            try:
                old.unlink()
            except OSError:
                pass


def restart() -> None:
    """Uruchamia aplikację od nowa (przez Wykłady.exe) – wywołać tuż przed zamknięciem."""
    exe = ROOT / EXE
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0     # DETACHED_PROCESS | NEW_PROCESS_GROUP
    if exe.exists():
        subprocess.Popen([str(exe), "--wait"], cwd=str(ROOT), creationflags=flags, close_fds=True)
    else:
        subprocess.Popen([sys.executable, str(INTERNAL / "main.py"), "--wait"], cwd=str(INTERNAL),
                         creationflags=flags, close_fds=True)
