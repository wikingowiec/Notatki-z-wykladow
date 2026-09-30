"""Notatki na telefon: PDF (w formacie telefonu) do folderu synchronizowanego z chmurą.

Najprościej przez „Dysk Google na komputer” – tworzy on dysk (np. G:\\Mój dysk), który sam wysyła pliki do chmury.
Na telefonie notatki są wtedy w aplikacji Dysk Google. Tak samo działa iCloud Drive (aplikacja Pliki na iPhonie)
i OneDrive. Aplikacja niczego nie wysyła sama do internetu – tylko zapisuje plik w folderze."""
from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .storage import Lecture

log = logging.getLogger(__name__)
GDRIVE_DOWNLOAD = "https://www.google.com/drive/download/"
ICLOUD_DOWNLOAD = "https://apps.microsoft.com/detail/9pktq5699m62"
SUBFOLDER = "Wykłady"
last_error = ""


@dataclass
class CloudFolder:
    kind: str          # gdrive / icloud / onedrive
    label: str
    root: Path

    @property
    def target(self) -> Path:
        return self.root / SUBFOLDER


def _drive_letters() -> list[str]:
    """Litery dysków lokalnych (bez sieciowych i napędów CD – te potrafią długo nie odpowiadać)."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        out = []
        for i in range(26):
            if mask & (1 << i):
                d = f"{chr(65 + i)}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(d) in (2, 3, 6):     # wymienny, lokalny, RAM
                    out.append(d)
        return out
    except Exception:  # noqa: BLE001
        return []


def detect() -> list[CloudFolder]:
    """Foldery chmury znalezione na tym komputerze (Dysk Google najpierw)."""
    found: list[CloudFolder] = []
    home = Path.home()
    names = ("Mój dysk", "My Drive", "Moje dokumenty na Dysku")
    cands = [Path(d) / n for d in _drive_letters() for n in names]
    cands += [home / "Google Drive" / "Mój dysk", home / "Google Drive" / "My Drive", home / "Mój dysk",
              home / "My Drive", home / "Google Drive"]
    for c in cands:
        try:
            if c.is_dir() and not any(f.root == c for f in found):
                found.append(CloudFolder("gdrive", f"Dysk Google ({c})", c))
                break
        except OSError:
            pass
    for c in (home / "iCloudDrive", home / "iCloud Drive"):
        if c.is_dir():
            found.append(CloudFolder("icloud", f"iCloud Drive ({c})", c))
            break
    for env in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        v = os.environ.get(env)
        if v and Path(v).is_dir() and not any(f.root == Path(v) for f in found):
            found.append(CloudFolder("onedrive", f"OneDrive ({v})", Path(v)))
            break
    return found


def safe_name(s: str, fallback: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", (s or "").strip()).strip(" .")
    return (s or fallback)[:120]


def pdf_path(lecture: Lecture, folder: Path) -> Path:
    m = lecture.meta
    return folder / safe_name(m.subject, "Bez przedmiotu") / f"{safe_name(m.title, 'Wykład')}.pdf"


def enabled(settings) -> bool:
    return bool(getattr(settings, "phone_sync", False) and getattr(settings, "phone_dir", ""))


def export_lecture(lecture: Lecture, settings) -> Optional[Path]:
    """Zapisuje (albo podmienia) PDF notatki w folderze chmury. Wywoływać w wątku interfejsu."""
    global last_error
    if not enabled(settings) or not lecture.notes_path.exists():
        return None
    from .exporters import export_pdf
    folder = Path(settings.phone_dir)
    dest = pdf_path(lecture, folder)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp.pdf")
        export_pdf(lecture, tmp, mobile=True)
        os.replace(tmp, dest)            # telefon nigdy nie widzi pół-zapisanego pliku
        old = lecture.meta.phone_pdf
        if old and Path(old) != dest:    # zmiana tytułu/przedmiotu – usuń stary plik
            _remove(Path(old))
        lecture.meta.phone_pdf = str(dest)
        lecture.save_meta()
        last_error = ""
        log.info("PDF na telefon: %s", dest)
        return dest
    except Exception as e:  # noqa: BLE001
        last_error = str(e)
        log.warning("PDF na telefon: %s", e)
        return None


def remove_lecture(lecture: Lecture) -> None:
    if lecture.meta.phone_pdf:
        _remove(Path(lecture.meta.phone_pdf))


def _remove(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
        if p.parent.exists() and not any(p.parent.iterdir()):
            p.parent.rmdir()
    except OSError:
        pass


def export_all(lectures: list[Lecture], settings, progress: Optional[Callable[[int, int], bool]] = None) -> int:
    done = 0
    todo = [l for l in lectures if l.notes_path.exists()]
    for i, lec in enumerate(todo, 1):
        if progress and progress(i, len(todo)) is False:
            break
        if export_lecture(lec, settings):
            done += 1
    return done


def needs_update(lecture: Lecture) -> bool:
    """PDF starszy niż notatka (albo go nie ma)."""
    p = Path(lecture.meta.phone_pdf) if lecture.meta.phone_pdf else None
    if not p or not p.exists():
        return True
    try:
        return p.stat().st_mtime < lecture.notes_path.stat().st_mtime
    except OSError:
        return True
