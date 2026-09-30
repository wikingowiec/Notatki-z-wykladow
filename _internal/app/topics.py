"""Tematy i kategorie wykładu.

* czyszczenie tytułów (model czasem przepisuje z polecenia „Krótki tytuł tematu”),
* kategorie = grupy podobnych tematów (np. „Percepcja”: tematy 23–32) – każda ma swój kolor
  w spisie treści, w nagłówkach notatki, w ściądze i w fiszkach,
* kategorie robi AI przy generowaniu notatek (categories.json); dla starszych notatek – prosta heurystyka."""
from __future__ import annotations

import json
import re
from typing import Optional

_TEMPLATE = re.compile(r"^(?:(?:krótki|krotki)\s+)?tytuł\s+tematu(?:\s*\([^)]*\))?\s*[:\-–—]?\s*|"
                       r"^short\s+topic\s+title(?:\s*\([^)]*\))?\s*[:\-–—]?\s*|^temat\s*[:\-–—]\s*", re.IGNORECASE)
_SEC = re.compile(r"^(\d+)\.\s*(★\s*)?(.*)$")
STOP_FIRST = {"wprowadzenie", "wstęp", "wstep", "podsumowanie", "introduction", "summary", "cd", "ciąg", "dalszy",
              "przykład", "przykłady", "fragment", "część", "czesc"}


def clean_title(t: str) -> str:
    t = (t or "").strip().strip("*").strip()
    for _ in range(2):
        t2 = _TEMPLATE.sub("", t).strip()
        if t2 == t:
            break
        t = t2
    t = t.strip(" :–-\"„”'")
    return t[:1].upper() + t[1:] if t else t


def clean_md_titles(md: str) -> str:
    """Usuwa „Krótki tytuł tematu:” z nagłówków notatki (także starszych)."""
    def fix(m):
        head, num, star, title = m.group(1), m.group(2) or "", m.group(3) or "", m.group(4)
        return f"{head}{num}{star}{clean_title(title) or title}"
    return re.sub(r"^(#{2,3}\s+)(\d+\.\s*)?(★\s*)?(.+)$", fix, md, flags=re.MULTILINE)


def sections_of(md: str) -> list[tuple[int, str, str, str]]:
    """Tematy z „Notatek szczegółowych”: (numer, tytuł, kotwica, czas)."""
    from .notes_doc import headings
    out = []
    for h in headings(md):
        m = _SEC.match(h.label.strip())
        if m:
            out.append((int(m.group(1)), clean_title(m.group(3)), h.anchor, h.time))
    return out


def _key(title: str) -> str:
    words = [w for w in re.findall(r"[a-ząćęłńóśźż]+", title.lower()) if len(w) > 2]
    words = [w for w in words if w not in STOP_FIRST] or words
    return words[0][:6] if words else ""


def heuristic_categories(sections: list[tuple[int, str]]) -> list[dict]:
    """Grupy po pierwszym znaczącym słowie tytułu („Percepcja: …”, „Percepcja wzrokowa” → „Percepcja”)."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for num, title in sections:
        k = _key(title)
        if k not in groups:
            word = next((w for w in re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+", title)
                         if w.lower()[:6] == k), "") or "Inne"
            groups[k] = {"name": word[:1].upper() + word[1:], "sections": []}
            order.append(k)
        groups[k]["sections"].append(num)
    cats = [groups[k] for k in order]
    if len(cats) > 8:          # za dużo drobnych grup → „Pozostałe”
        big = [c for c in cats if len(c["sections"]) > 1]
        small = [n for c in cats if len(c["sections"]) == 1 for n in c["sections"]]
        cats = big[:8] + ([{"name": "Pozostałe", "sections": small}] if small else [])
    return cats


def llm_categories(llm, model: str, sections: list[tuple[int, str]], lang: str, num_ctx: int,
                   cancel=None) -> list[dict]:
    """AI łączy tematy wykładu w 3–8 kategorii (JSON). Każdy temat w dokładnie jednej kategorii."""
    if len(sections) < 3:
        return []
    listing = "\n".join(f"{n}. {t}" for n, t in sections)
    if lang == "pl":
        prompt = ("Poniżej lista tematów z jednego wykładu (numer. tytuł):\n" + listing + "\n\n"
                  "Połącz podobne tematy w 3–8 kategorii (np. wszystkie tematy o percepcji w jedną kategorię). "
                  "Każdy numer tematu musi trafić do dokładnie jednej kategorii, kolejność kategorii zgodna z "
                  "przebiegiem wykładu. Nazwa kategorii: 1–3 słowa, po polsku.\n"
                  'Zwróć wyłącznie JSON: {"kategorie": [{"nazwa": "...", "tematy": [1, 2, 3]}]}')
    else:
        prompt = ("Below is the list of topics from one lecture (number. title):\n" + listing + "\n\n"
                  "Group similar topics into 3–8 categories. Every topic number must be in exactly one category; "
                  "keep the order of the lecture. Category name: 1–3 words, in the language of the topics.\n"
                  'Return JSON only: {"categories": [{"name": "...", "topics": [1, 2, 3]}]}')
    raw = llm.chat(model, [{"role": "user", "content": prompt}], num_ctx=min(num_ctx, 8192), json_mode=True,
                   temperature=0.1, cancel=cancel)
    return parse_categories(raw, [n for n, _t in sections])


def parse_categories(raw: str, numbers: list[int]) -> list[dict]:
    from .notes_pipeline import _json_any
    data = _json_any(raw)
    items = []
    if isinstance(data, dict):
        items = next((v for v in data.values() if isinstance(v, list)), [])
    elif isinstance(data, list):
        items = data
    cats, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        low = {str(k).lower(): v for k, v in it.items()}
        name = str(next((low[k] for k in ("nazwa", "name", "kategoria", "category") if low.get(k)), "")).strip()
        nums = next((low[k] for k in ("tematy", "topics", "sections", "numery") if isinstance(low.get(k), list)), [])
        nums = [int(x) for x in nums if str(x).strip().isdigit() and int(x) in numbers and int(x) not in seen]
        if name and nums:
            seen.update(nums)
            cats.append({"name": name[:40], "sections": sorted(nums)})
    missing = [n for n in numbers if n not in seen]
    for n in missing:                 # nieprzypisane – do kategorii poprzedniego tematu
        target = None
        for c in cats:
            if any(x < n for x in c["sections"]):
                target = c
        if target is None:
            if not cats:
                cats.append({"name": "Inne", "sections": []})
            target = cats[0]
        target["sections"].append(n)
    for c in cats:
        c["sections"].sort()
    return cats if len(cats) >= 2 else []


def save_categories(lecture, cats: list[dict]) -> None:
    (lecture.folder / "categories.json").write_text(json.dumps({"categories": cats}, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")


def load_categories(lecture, md: Optional[str] = None) -> list[dict]:
    """Kategorie wykładu: zapisane przez AI albo wyliczone z tytułów tematów."""
    md = md if md is not None else (lecture.read_text(lecture.notes_path) if lecture.notes_path.exists() else "")
    secs = sections_of(md)
    nums = {n for n, *_ in secs}
    try:
        data = json.loads((lecture.folder / "categories.json").read_text(encoding="utf-8"))
        cats = [c for c in data.get("categories", []) if c.get("sections")]
        if cats and nums and set(x for c in cats for x in c["sections"]) >= nums:
            return cats
    except Exception:  # noqa: BLE001
        pass
    return heuristic_categories([(n, t) for n, t, *_ in secs])


def section_colors(cats: list[dict]) -> dict[int, int]:
    """numer tematu → indeks koloru (kolejne kategorie – kolejne kolory palety)."""
    out = {}
    for ci, c in enumerate(cats):
        for n in c["sections"]:
            out[n] = ci
    return out


def category_of(cats: list[dict], section: int) -> str:
    return next((c["name"] for c in cats if section in c["sections"]), "")
