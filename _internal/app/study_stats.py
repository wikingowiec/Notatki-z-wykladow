"""Seria dni nauki i cel dzienny (plik nauka.json w folderze biblioteki – zostaje razem z notatkami).

Dzień liczy się jako „zrobiony”, gdy oceniono w nim co najmniej jedną fiszkę."""
from __future__ import annotations

import json
import threading
from datetime import date, timedelta
from pathlib import Path

_lock = threading.Lock()
FILE = "nauka.json"


def _path(library: Path) -> Path:
    return Path(library) / FILE


def load(library: Path) -> dict:
    try:
        d = json.loads(_path(library).read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("days"), dict):
            return d
    except Exception:  # noqa: BLE001
        pass
    return {"days": {}, "best": 0}


def _save(library: Path, d: dict) -> None:
    p = _path(library)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def record_review(library: Path, n: int = 1, day: date | None = None) -> dict:
    """Zapisuje ocenioną fiszkę (n > 0) albo cofnięcie oceny (n < 0)."""
    with _lock:
        d = load(library)
        k = (day or date.today()).isoformat()
        d["days"][k] = max(0, int(d["days"].get(k, 0)) + n)
        if not d["days"][k]:
            d["days"].pop(k)
        d["best"] = max(int(d.get("best", 0)), streak(d))
        _save(library, d)
        return d


def streak(d: dict, today: date | None = None) -> int:
    """Liczba kolejnych dni nauki. Dziś jeszcze bez nauki nie przerywa serii (liczy się od wczoraj)."""
    days = {k for k, v in d.get("days", {}).items() if v}
    t = today or date.today()
    cur = t if t.isoformat() in days else t - timedelta(days=1)
    n = 0
    while cur.isoformat() in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def today_count(d: dict, today: date | None = None) -> int:
    return int(d.get("days", {}).get((today or date.today()).isoformat(), 0))


def week(d: dict, today: date | None = None) -> list[tuple[str, bool, bool]]:
    """Bieżący tydzień Pn–Nd: (litera dnia, czy zrobiony, czy dziś)."""
    t = today or date.today()
    mon = t - timedelta(days=t.weekday())
    names = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]
    out = []
    for i in range(7):
        day = mon + timedelta(days=i)
        out.append((names[i], bool(d.get("days", {}).get(day.isoformat())), day == t))
    return out


def summary(library: Path) -> dict:
    d = load(library)
    s = streak(d)
    return {"streak": s, "best": max(int(d.get("best", 0)), s), "today": today_count(d), "week": week(d)}


def days_word(n: int) -> str:
    if n == 1:
        return "dzień"
    return "dni"
