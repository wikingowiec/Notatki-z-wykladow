"""Fiszki pogrupowane w kategorie (talie): kategoria wykładu → tematy → fiszki."""
from __future__ import annotations

from dataclasses import dataclass, field

from .storage import Lecture


@dataclass
class Deck:
    lecture: Lecture
    name: str
    color: int                                   # indeks koloru kategorii (jak w spisie treści)
    entries: list = field(default_factory=list)  # [(lista fiszek wykładu, indeks)]
    sections: list = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (str(self.lecture.folder), self.name)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def known(self) -> int:
        return sum(1 for cards, i in self.entries if cards[i].get("known"))

    def due(self, day=None) -> int:
        from .srs import is_due, today
        d = day or today()
        return sum(1 for cards, i in self.entries if is_due(cards[i], d))


def decks_for(lectures: list[Lecture]) -> list[Deck]:
    from .topics import load_categories, section_colors
    out: list[Deck] = []
    for lec in lectures:
        cards = lec.load_flashcards()
        if not cards:
            continue
        md = lec.read_text(lec.notes_path) if lec.notes_path.exists() else ""
        cats = load_categories(lec, md) if md else []
        colors = section_colors(cats)
        by_sec = {n: c["name"] for c in cats for n in c["sections"]}
        decks: dict[str, Deck] = {}
        for i, c in enumerate(cards):
            sec = int(c.get("section") or 0)
            name = c.get("category") or by_sec.get(sec) or "Ogólne"
            if name not in decks:
                ci = next((k for k, cat in enumerate(cats) if cat["name"] == name), colors.get(sec, len(decks)))
                decks[name] = Deck(lec, name, ci)
            d = decks[name]
            d.entries.append((cards, i))
            if sec and sec not in d.sections:
                d.sections.append(sec)
        order = {c["name"]: k for k, c in enumerate(cats)}
        out += sorted(decks.values(), key=lambda d: (order.get(d.name, 99), min(d.sections or [0])))
    return out


def deck_markdown(deck: Deck) -> str:
    """Kategoria do przeglądania: tematy (w kolorze) → definicje i wzory z notatki → fiszki."""
    from . import cheatsheet as CS
    from .topics import sections_of
    lec = deck.lecture
    md = lec.read_text(lec.notes_path) if lec.notes_path.exists() else ""
    titles = {n: (t, tm) for n, t, _a, tm in sections_of(md)}
    defs = [it for it in CS.extract(md) if it.section in deck.sections and it.kind in ("def", "formula")]
    by_sec: dict[int, list] = {}
    for cards, i in deck.entries:
        by_sec.setdefault(int(cards[i].get("section") or 0), []).append(cards[i])
    out = []
    for sec in sorted(by_sec, key=lambda s: (s == 0, s)):
        title, tm = titles.get(sec, (by_sec[sec][0].get("topic") or "", ""))
        head = f"{sec}. {title}" if sec else (title or "Pozostałe")
        out += ["", f"## {head}", ""]
        for it in (d for d in defs if d.section == sec):
            out += [f"> **{CS.KIND_LABEL[it.kind]}:** " + it.text.replace("\n", "\n> "), ""]
        for c in by_sec[sec]:
            known = "  ✓ umiem" if c.get("known") else ""
            out += [f"> **Fiszka:** **{c['q'].strip()}**{known}", ">",
                    "> " + c["a"].strip().replace("\n", "\n> "), ""]
    return "\n".join(out).strip() + "\n"
