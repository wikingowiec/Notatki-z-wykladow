"""Powtórki rozłożone w czasie (uproszczony algorytm w stylu Anki).

Pola fiszki: due (RRRR-MM-DD), ivl (odstęp w dniach), reps, lapses, known (opanowana: odstęp ≥ 7 dni).
Umiem:        1 → 3 → 7 → 16 → 37 … dni
Jeszcze nie:  wraca dziś (w tej samej rundzie) i zaczyna od nowa.
"""
from __future__ import annotations

from datetime import date, timedelta

MASTERED_DAYS = 7


def today() -> str:
    return date.today().isoformat()


def is_due(card: dict, day: str | None = None) -> bool:
    due = card.get("due")
    return not due or due <= (day or today())


def review(card: dict, ok: bool) -> None:
    ivl = int(card.get("ivl", 0) or 0)
    if ok:
        ivl = 1 if ivl <= 0 else 3 if ivl == 1 else max(ivl + 1, round(ivl * 2.3))
        card["reps"] = int(card.get("reps", 0)) + 1
    else:
        ivl = 0
        card["lapses"] = int(card.get("lapses", 0)) + 1
    card["ivl"] = ivl
    card["due"] = (date.today() + timedelta(days=ivl)).isoformat()
    card["known"] = 1 if ivl >= MASTERED_DAYS else 0


def next_label(card: dict) -> str:
    ivl = int(card.get("ivl", 0) or 0)
    nxt = 1 if ivl <= 0 else 3 if ivl == 1 else max(ivl + 1, round(ivl * 2.3))
    return "jutro" if nxt == 1 else f"za {nxt} dni"
