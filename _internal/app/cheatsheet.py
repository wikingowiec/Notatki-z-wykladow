"""Ściąga: definicje, wzory, przykłady i ważne rzeczy z notatki – pogrupowane po tematach, z odnośnikiem
do miejsca w notatce. Źródło: ramki (> **Definicja:** …), zakreślenia ==…== i „Kluczowe pojęcia”."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .notes_style import LABELS

KINDS = {"def": "Definicje", "formula": "Wzory", "example": "Przykłady", "important": "Ważne"}
KIND_LABEL = {"def": "Definicja", "formula": "Wzór", "example": "Przykład", "important": "Ważne",
              "highlight": "Zapamiętaj"}
_BOX = re.compile(r"^>\s*\*\*([^*:\n]{2,30}?)\s*:?\s*\*\*\s*:?\s*(.*)$")
_HL = re.compile(r"==(?=\S)([^=\n]+?)(?<=\S)==")
_TERM = re.compile(r"^\s*[-*]\s+\*\*([^*]+)\*\*\s*[—–:-]\s*(.+)$")
KEY_TERMS = ("kluczowe pojęcia", "key terms")


@dataclass
class Item:
    kind: str
    text: str            # Markdown (może zawierać wzory)
    section: int         # numer tematu (0 = sekcja bez numeru, np. „Kluczowe pojęcia”)
    title: str
    anchor: str
    time: str = ""

    @property
    def group(self) -> str:        # do filtra: zakreślenia liczą się jako „Ważne”
        return "important" if self.kind == "highlight" else self.kind


def extract(md: str) -> list[Item]:
    from .notes_doc import headings
    from .topics import clean_md_titles, clean_title
    md = clean_md_titles(md)
    lines = md.splitlines()
    hs = headings(md)
    by_line = {h.line: h for h in hs}
    items: list[Item] = []
    cur = None          # (numer, tytuł, kotwica, czas, czy „kluczowe pojęcia”)
    i = 0
    while i < len(lines):
        line = lines[i]
        if i in by_line:
            h = by_line[i]
            m = re.match(r"^(\d+)\.\s*(?:★\s*)?(.*)$", h.label.strip())
            if m:
                cur = (int(m.group(1)), clean_title(m.group(2)), h.anchor, h.time, False)
            else:
                cur = (0, h.label, h.anchor, h.time, h.label.strip().lower() in KEY_TERMS)
            i += 1
            continue
        if cur is None:
            i += 1
            continue
        num, title, anchor, tm, key_terms = cur
        m = _BOX.match(line.strip())
        if m:
            kind = LABELS.get(m.group(1).strip().lower(), "")
            body = [m.group(2).strip()]
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith(">") and not _BOX.match(lines[j].strip()):
                body.append(re.sub(r"^\s*>\s?", "", lines[j]))
                j += 1
            if kind in KINDS:
                text = "\n".join(b for b in body if b.strip()).strip()
                if text:
                    items.append(Item(kind, text, num, title, anchor, tm))
            i = j
            continue
        if key_terms:
            t = _TERM.match(line)
            if t:
                items.append(Item("def", f"**{t.group(1).strip()}** — {t.group(2).strip()}", num, title, anchor, tm))
                i += 1
                continue
        if (num or key_terms) and not line.lstrip().startswith(">"):   # zakreślenia z podsumowania – pomijamy
            for h in _HL.findall(line):
                items.append(Item("highlight", h.strip(), num, title, anchor, tm))
        i += 1
    # bez powtórzeń (np. to samo w „Zaznaczonych fragmentach” i w temacie) – zostaje wystąpienie w temacie
    def norm(t):
        return re.sub(r"\W+", "", t.lower())[:120]
    in_topics = {norm(it.text) for it in items if it.section}
    seen, out = set(), []
    for it in items:
        k = norm(it.text)
        if (not it.section and k in in_topics) or (k, it.section) in seen:
            continue
        seen.add((k, it.section))
        out.append(it)
    return out


def counts(items: list[Item]) -> dict[str, int]:
    out = {k: 0 for k in KINDS}
    for it in items:
        out[it.group] = out.get(it.group, 0) + 1
    return out


def to_markdown(items: list[Item], only: str = "") -> str:
    """Ściąga jako Markdown (ramki pod nagłówkami tematów) – renderowana tak samo jak notatka."""
    sel = [it for it in items if not only or it.group == only]
    out: list[str] = []
    last = None
    for it in sel:
        key = (it.section, it.anchor)
        if key != last:
            head = f"{it.section}. {it.title}" if it.section else it.title
            out += ["", f"## {head}", f"*{(it.time + ' · ') if it.time else ''}[pokaż w notatce](#note-{it.anchor})*", ""]
            last = key
        label = KIND_LABEL[it.kind]
        body = it.text.replace("\n", "\n> ")
        out += [f"> **{'Ważne' if it.kind == 'highlight' else label}:** {body}", ""]
    return "\n".join(out).strip() + "\n"
