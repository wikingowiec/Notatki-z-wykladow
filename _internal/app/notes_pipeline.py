"""Generowanie notatek, podsumowania i fiszek z transkrypcji + slajdów przez lokalny model (Ollama).

Kroki:
  1. Podział transkrypcji na sekcje według zmian slajdów (albo co ~1200 słów, gdy slajdów brak).
  2. Notatki do każdej sekcji (transkrypcja + tekst ze slajdu z OCR).
  3. Fiszki do każdej sekcji (JSON).
  4. Podsumowanie całości (z notatek; przy bardzo długich wykładach – hierarchicznie).
  5. Złożenie notes.md, summary.md, flashcards.json, notes.html.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .storage import Lecture, fmt_time

log = logging.getLogger(__name__)

MIN_WORDS = 60
MAX_WORDS = 1400
NOSLIDE_WORDS = 1100

from .prompts import EXAM_PATTERNS, mark_names, texts

SYSTEM = texts("pl").system    # zgodność wstecz


@dataclass
class Section:
    start: float
    end: float
    texts: list[str] = field(default_factory=list)
    slides: list[dict] = field(default_factory=list)   # wpisy ze slides.json
    revisit: bool = False
    marks: list[str] = field(default_factory=list)     # rodzaje zaznaczeń studenta w tym fragmencie

    @property
    def text(self) -> str:
        return " ".join(t for t in self.texts if t).strip()

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def ocr(self) -> str:
        """Tekst slajdów: odczyt modelu widzącego obrazy (ze wzorami) albo OCR."""
        from .vision import slide_text
        return "\n---\n".join(t for t in (slide_text(s) for s in self.slides) if t).strip()

    @property
    def visuals(self) -> list[tuple[int, dict]]:
        from .vision import slide_items
        return [(s.get("index", 0), it) for s in self.slides for it in slide_items(s)]


# ---------------------------------------------------------------------------
# 1. sekcje
# ---------------------------------------------------------------------------
def _chunk_segments(segments: list[dict], start: float, end: float, max_words: int) -> list[Section]:
    out: list[Section] = []
    cur = Section(start, end)
    count = 0
    for s in segments:
        w = len(s["text"].split())
        if count and count + w > max_words:
            cur.end = s["start"]
            out.append(cur)
            cur = Section(s["start"], end)
            count = 0
        cur.texts.append(s["text"])
        count += w
    out.append(cur)
    return out


def build_sections(segments: list[dict], slides_data: dict, duration: float = 0.0) -> list[Section]:
    segments = sorted(segments, key=lambda s: s["start"])
    end_time = max([duration] + [s["end"] for s in segments] + [0.0]) + 1
    slides_by_index = {s["index"]: s for s in slides_data.get("slides", [])}
    events = sorted(slides_data.get("events", []), key=lambda e: e["t"])

    if not events:
        return [s for s in _chunk_segments(segments, 0.0, end_time, NOSLIDE_WORDS) if s.texts]
    if not segments:
        # notatka tylko ze slajdów: jeden fragment na slajd (bez scalania – nie ma mowy do liczenia)
        out: list[Section] = []
        seen_idx: set[int] = set()
        last_t = max(e["t"] for e in events)
        for i, ev in enumerate(events):
            slide = slides_by_index.get(ev["index"])
            if not slide or (out and out[-1].slides and out[-1].slides[0] is slide):
                continue
            end = events[i + 1]["t"] if i + 1 < len(events) else max(last_t + 60, duration)
            out.append(Section(ev["t"], end, slides=[slide], revisit=ev["index"] in seen_idx))
            seen_idx.add(ev["index"])
        return out

    # sekcje wg zdarzeń slajdów (pierwsza zaczyna się od 0, żeby objąć wstęp)
    sections: list[Section] = []
    seen: set[int] = set()
    for i, ev in enumerate(events):
        start = 0.0 if i == 0 else ev["t"]
        end = events[i + 1]["t"] if i + 1 < len(events) else end_time
        slide = slides_by_index.get(ev["index"])
        sec = Section(start, end, slides=[slide] if slide else [], revisit=ev["index"] in seen)
        seen.add(ev["index"])
        sections.append(sec)
    for s in segments:
        mid = (s["start"] + s["end"]) / 2
        for sec in sections:
            if sec.start <= mid < sec.end:
                sec.texts.append(s["text"])
                break
        else:
            sections[-1].texts.append(s["text"])

    # scal zbyt krótkie sekcje z poprzednią (albo następną, jeśli to pierwsza)
    merged: list[Section] = []
    for sec in sections:
        if merged and (sec.words < MIN_WORDS or (sec.slides and all(sl in merged[-1].slides for sl in sec.slides))):
            prev = merged[-1]
            prev.end = sec.end
            prev.texts.extend(sec.texts)
            for sl in sec.slides:
                if sl not in prev.slides:
                    prev.slides.append(sl)
        else:
            merged.append(sec)
    if len(merged) > 1 and merged[0].words < MIN_WORDS:
        first, second = merged[0], merged[1]
        second.start = first.start
        second.texts = first.texts + second.texts
        second.slides = first.slides + [s for s in second.slides if s not in first.slides]
        merged = merged[1:]

    # podziel zbyt długie sekcje
    final: list[Section] = []
    for sec in merged:
        if sec.words <= MAX_WORDS:
            final.append(sec)
            continue
        segs = [s for s in segments if sec.start <= (s["start"] + s["end"]) / 2 < sec.end]
        parts = _chunk_segments(segs, sec.start, sec.end, MAX_WORDS) if segs else [sec]
        for j, p in enumerate(parts):
            p.slides = sec.slides if j == 0 else []
            p.revisit = sec.revisit
        final.extend(parts)
    return final


# ---------------------------------------------------------------------------
# 2-4. prompty
# ---------------------------------------------------------------------------
def _normalize_headings(md: str) -> str:
    from .topics import clean_title
    lines = []
    for line in md.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        lines.append(f"### {clean_title(m.group(2)) or m.group(2)}" if m else line)
    md = "\n".join(lines).strip()
    md = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", md).strip()
    return md


# etykiety ramek (w notatce po polsku albo po angielsku) → rodzaj ramki
CALLOUT_LABELS = {
    "definicja": "def", "definicje": "def", "definition": "def", "definitions": "def",
    "wzór": "formula", "wzory": "formula", "formula": "formula", "formulas": "formula", "twierdzenie": "formula",
    "theorem": "formula",
    "przykład": "example", "przykłady": "example", "example": "example", "examples": "example",
    "ważne": "important", "uwaga": "important", "important": "important", "note": "important",
    "zapamiętaj": "important", "remember": "important", "na egzamin": "important",
    "na slajdzie": "slide", "on the slide": "slide",
    "w skrócie": "lead", "in short": "lead",
}
_LABEL_RE = re.compile(r"^\s*(?:[-*]\s+)?\*\*(" + "|".join(sorted(map(re.escape, CALLOUT_LABELS), key=len, reverse=True))
                       + r")\s*:?\s*\*\*\s*:?", re.IGNORECASE)


def tidy_note(md: str, max_marks: int = 4) -> str:
    """Porządkuje odpowiedź modelu: nagłówki, ramki (> **Definicja:** …) w osobnych akapitach,
    najwyżej kilka zakreśleń ==…==, bez pustych ramek i podwójnych pustych linii."""
    md = _normalize_headings(md)
    out: list[str] = []
    for line in md.splitlines():
        m = _LABEL_RE.match(line)
        if m and not line.lstrip().startswith(">"):
            label = m.group(1)
            kind = CALLOUT_LABELS.get(label.lower(), "")
            rest = line[m.end():].strip()
            label = label[0].upper() + label[1:]
            if kind == "lead":
                line = f"**{label}:** {rest}"
            else:
                line = f"> **{label}:** {rest}"
        starts_box = bool(re.match(r"^\s*>\s*\*\*[^*]{2,30}:\*\*", line))
        if line.lstrip().startswith(">") and out and out[-1].strip() and \
                (not out[-1].lstrip().startswith(">") or starts_box):
            out.append("")
        elif line.strip() and out and out[-1].lstrip().startswith(">") and not line.lstrip().startswith(">"):
            out.append("")
        elif re.match(r"^(?:[-*+]|\d+[.)])\s", line) and out and out[-1].strip() and \
                not re.match(r"^\s*(?:[-*+]|\d+[.)])\s", out[-1]) and not out[-1].startswith(("  ", "\t")):
            out.append("")            # lista musi być oddzielona od akapitu pustą linią
        out.append(line.rstrip())
    md = "\n".join(out)
    # zakreślenia: najwyżej max_marks, reszta zostaje zwykłym tekstem
    count = 0

    def hl(m):
        nonlocal count
        count += 1
        return m.group(0) if count <= max_marks else m.group(1)
    md = re.sub(r"==(?=\S)(.+?)(?<=\S)==", hl, md)
    md = re.sub(r"^>[ \t]*\*\*[^*\n]+:\*\*[ \t]*(?:\n(?!>)|\Z)", "", md, flags=re.MULTILINE)   # pusta ramka
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def attach_marks(sections: list[Section], marks: list[dict]) -> None:
    for sec in sections:
        kinds = []
        for m in marks:
            if m.get("start", 0) < sec.end and m.get("end", m.get("start", 0)) > sec.start and m.get("kind") not in kinds:
                kinds.append(m.get("kind", "important"))
        sec.marks = kinds


def lecture_lang(lecture: Lecture) -> str:
    return (lecture.meta.language or "pl").lower()[:2]


def section_prompt(sec: Section, i: int, n: int, title: str, subject: str, lang: str = "pl") -> str:
    T = texts(lang)
    frag = (f"{T.fragment_of} {i}/{n}" if n else f"{T.fragment_of} {i}")
    parts = [f"{T.subject}: {subject or '—'}", f"{T.lecture}: {title}",
             f"{frag} ({T.time} {fmt_time(sec.start)}–{fmt_time(sec.end)}).", ""]
    if sec.marks:
        names = mark_names(lang)
        parts += [T.marked_hint.format(kinds=", ".join(names.get(k, k) for k in sec.marks)), ""]
    if sec.ocr:
        parts += [f"{T.slide_ocr}:", '"""', sec.ocr[:3000], '"""', ""]
    if sec.visuals:
        parts += [f"{T.slide_visuals}:"] + [f"- {it.get('kind') or '?'}: {it.get('desc', '')}" for _i, it in sec.visuals]
        parts += [""]
    if sec.text:
        parts += [f"{T.transcript}:", '"""', sec.text, '"""', ""]
    parts += T.section_task
    return "\n".join(parts)


def flashcards_prompt(notes: str, k: int, lang: str = "pl") -> str:
    return texts(lang).flashcards.format(k=k, notes=notes)


def summary_prompt(notes: str, title: str, subject: str, lang: str = "pl") -> str:
    T = texts(lang)
    subj = (f" ({T.subject.lower()}: {subject})" if subject else "")
    return T.summary.format(title=title, subject=subj, notes=notes)


def condense_prompt(notes: str, lang: str = "pl") -> str:
    return texts(lang).condense.format(notes=notes)


_Q_KEYS = ("pytanie", "question", "q", "przod", "przód", "front")
_A_KEYS = ("odpowiedz", "odpowiedź", "answer", "a", "tyl", "tył", "back")


def _json_any(text: str):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def parse_flashcards(text: str) -> list[dict]:
    data = _json_any(text)
    if data is None:
        return []
    if isinstance(data, dict):
        items = None
        for k in ("fiszki", "flashcards", "cards", "karty"):
            if isinstance(data.get(k), list):
                items = data[k]
                break
        if items is None:
            lists = [v for v in data.values() if isinstance(v, list)]
            items = lists[0] if lists else [data]
    else:
        items = data
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        low = {str(k).lower(): v for k, v in it.items()}
        q = next((str(low[k]).strip() for k in _Q_KEYS if k in low and low[k]), "")
        a = next((str(low[k]).strip() for k in _A_KEYS if k in low and low[k]), "")
        if q and a:
            out.append({"q": q, "a": a})
    return out


def _est_tokens(text: str) -> int:
    return int(len(text) / 3.2) + 1


# ---------------------------------------------------------------------------
# Pamięć podręczna notatek fragmentów (notatki zrobione na żywo nie są liczone drugi raz)
# ---------------------------------------------------------------------------
def section_key(sec: Section, model: str, lang: str = "pl") -> str:
    import hashlib
    vis = "|".join(it.get("desc", "") for _i, it in sec.visuals)
    return hashlib.sha1(f"v2\n{model}\n{lang}\n{','.join(sec.marks)}\n{sec.text}\n{sec.ocr}\n{vis}"
                        .encode("utf-8")).hexdigest()[:20]


def load_cache(lecture: Lecture) -> dict:
    try:
        return json.loads((lecture.folder / "notes_cache.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(lecture: Lecture, cache: dict) -> None:
    p = lecture.folder / "notes_cache.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def section_note(llm, model: str, sec: Section, i: int, n: int, title: str, subject: str, num_ctx: int,
                 cancel=None, on_token=None, keep_alive: str = "10m", lang: str = "pl") -> str:
    if sec.words < 15 and not sec.ocr:
        return ""
    raw = llm.chat(model, [{"role": "system", "content": texts(lang).system},
                           {"role": "user", "content": section_prompt(sec, i, n, title, subject, lang)}],
                   num_ctx=num_ctx, cancel=cancel, on_token=on_token, keep_alive=keep_alive)
    return tidy_note(raw)


# ---------------------------------------------------------------------------
# Zaznaczone fragmenty i informacje o egzaminie
# ---------------------------------------------------------------------------
def text_between(segments: list[dict], start: float, end: float) -> str:
    return " ".join(s["text"] for s in segments if s["end"] > start and s["start"] < end).strip()


def exam_snippets(segments: list[dict], marks: list[dict], lang: str) -> list[tuple[float, str]]:
    """Fragmenty transkrypcji, w których padają słowa o egzaminie/zaliczeniu (+ zaznaczenia „Na egzamin”)."""
    pat = re.compile(EXAM_PATTERNS.get(lang, EXAM_PATTERNS["en"] if lang != "pl" else EXAM_PATTERNS["pl"]), re.IGNORECASE)
    hits = [i for i, s in enumerate(segments) if pat.search(s["text"])]
    windows: list[list[int]] = []
    for i in hits:
        lo, hi = max(0, i - 1), min(len(segments) - 1, i + 2)
        if windows and lo <= windows[-1][1] + 1:
            windows[-1][1] = max(windows[-1][1], hi)
        else:
            windows.append([lo, hi])
    out = [(segments[a]["start"], " ".join(s["text"] for s in segments[a:b + 1])) for a, b in windows]
    for m in marks:
        if m.get("kind") == "exam":
            txt = text_between(segments, m["start"] - 5, m.get("end", m["start"]) + 5)
            if txt:
                out.append((m["start"], txt))
    out.sort()
    return out[:40]


def extract_exam_info(llm, model: str, segments: list[dict], marks: list[dict], lang: str, num_ctx: int,
                      cancel=None) -> list[str]:
    snippets = exam_snippets(segments, marks, lang)
    if not snippets:
        return []
    block = "\n\n".join(f"[{fmt_time(t)}] {txt}" for t, txt in snippets)
    block = block[: int(num_ctx * 0.5 * 3)]
    raw = llm.chat(model, [{"role": "system", "content": texts(lang).system},
                           {"role": "user", "content": texts(lang).exam_extract.format(snippets=block)}],
                   num_ctx=num_ctx, cancel=cancel, json_mode=True, temperature=0.1)
    data = _json_any(raw)
    items = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                items = v
                break
    elif isinstance(data, list):
        items = data
    return [x.strip() for x in items if isinstance(x, str) and x.strip()][:20]


# ---------------------------------------------------------------------------
# 5. całość
# ---------------------------------------------------------------------------
def generate(lecture: Lecture, llm, model: str, num_ctx: int = 16384, cards_per_section: int = 4,
             progress: Optional[Callable[[str, float], None]] = None,
             on_token: Optional[Callable[[str], None]] = None,
             cancel: Optional[threading.Event] = None, use_cache: bool = False,
             vision_model: Optional[str] = None) -> None:
    def prog(msg, frac):
        if progress:
            progress(msg, frac)

    title, subject = lecture.meta.title, lecture.meta.subject
    lang = lecture_lang(lecture)
    T = texts(lang)
    names = mark_names(lang)
    segments = lecture.load_segments()
    # --- opisy slajdów (obrazy, schematy, wykresy) modelem widzącym obrazy ---
    if vision_model and lecture.load_slides().get("slides"):
        from .vision import describe_slides
        try:
            describe_slides(lecture, llm, vision_model, lang,
                            progress=lambda m, f: prog(m, 0.01 + 0.14 * max(0.0, f)), cancel=cancel)
        except Exception as e:  # noqa: BLE001
            if cancel is not None and cancel.is_set():
                raise
            log.warning("opisy slajdów pominięte: %s", e)
            prog(f"Opisy slajdów pominięte ({str(e)[:80]}) – notatki z tekstu slajdów.", 0.15)
    slides_data = lecture.load_slides()
    marks = lecture.load_marks()
    sections = build_sections(segments, slides_data, lecture.meta.duration)
    attach_marks(sections, marks)
    if not sections or not any(s.text or s.ocr for s in sections):
        raise RuntimeError("Brak transkrypcji i tekstu ze slajdów – nie ma z czego zrobić notatek.")

    n = len(sections)
    chat = lambda prompt, **kw: llm.chat(model, [{"role": "system", "content": T.system},  # noqa: E731
                                                 {"role": "user", "content": prompt}],
                                         num_ctx=num_ctx, cancel=cancel, **kw)

    # --- notatki do sekcji (fragmenty zrobione już tym samym modelem bierzemy z pamięci podręcznej) ---
    cache = load_cache(lecture) if use_cache else {}
    new_cache: dict = dict(load_cache(lecture))
    notes: list[str] = []
    for i, sec in enumerate(sections, 1):
        key = section_key(sec, model, lang)
        if key in cache:
            notes.append(cache[key])
            continue
        prog(f"Notatki: fragment {i}/{n}", 0.15 + 0.40 * (i - 1) / n)
        if on_token:
            on_token(f"\n\n— fragment {i}/{n} —\n")
        note = section_note(llm, model, sec, i, n, title, subject, num_ctx, cancel, on_token, lang=lang)
        notes.append(note)
        new_cache[key] = note
        try:
            save_cache(lecture, new_cache)
        except OSError:
            pass

    # --- zaznaczone fragmenty ---
    marked_notes: list[tuple[dict, str]] = []
    for j, m in enumerate(sorted(marks, key=lambda x: x.get("start", 0)), 1):
        prog(f"Zaznaczone fragmenty: {j}/{len(marks)}", 0.56)
        txt = text_between(segments, m["start"] - 5, m.get("end", m["start"]) + 5)
        if len(txt.split()) < 8:
            continue
        tm = f"{fmt_time(m['start'])}–{fmt_time(m.get('end', m['start']))}"
        try:
            marked_notes.append((m, tidy_note(chat(T.mark_note.format(
                kind=names.get(m.get("kind"), m.get("kind")), time=tm, text=txt)))))
        except Exception as e:  # noqa: BLE001
            if cancel is not None and cancel.is_set():
                raise
            log.warning("zaznaczenie: %s", e)

    # --- informacje o egzaminie ---
    prog("Szukam informacji o egzaminie…", 0.58)
    try:
        exam_items = extract_exam_info(llm, model, segments, marks, lang, num_ctx, cancel)
    except Exception as e:  # noqa: BLE001
        if cancel is not None and cancel.is_set():
            raise
        log.warning("egzamin: %s", e)
        exam_items = []
    (lecture.folder / "exam_info.json").write_text(json.dumps({"items": exam_items}, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")

    # --- kategorie tematów (podobne tematy razem, każda kategoria ma swój kolor) ---
    from .topics import clean_title, heuristic_categories, llm_categories, save_categories
    titles = []
    for i, note in enumerate(notes, 1):
        mm = re.match(r"^\s*###\s+(.+?)\s*(?:\n|$)", note or "")
        titles.append((i, clean_title(mm.group(1)) if mm else T.fragment))
    prog("Porządkuję tematy w kategorie…", 0.59)
    cats: list = []
    try:
        cats = llm_categories(llm, model, titles, lang, num_ctx, cancel)
    except Exception as e:  # noqa: BLE001
        if cancel is not None and cancel.is_set():
            raise
        log.warning("kategorie: %s", e)
    if not cats:
        cats = heuristic_categories(titles)
    try:
        save_categories(lecture, cats)
    except OSError:
        pass
    cat_of = {n: c["name"] for c in cats for n in c["sections"]}
    title_of = dict(titles)

    # --- fiszki: liczba zależna od długości wykładu, bez powtórzeń, z kategorią i tematem ---
    cards: list[dict] = []
    seen_q: list[set] = []
    total_words = sum(sec.words for sec in sections) or 1
    minutes = (lecture.meta.duration or 0) / 60 or total_words / 130
    target = int(max(12, min(60, round(minutes * 0.5))))

    def similar(q: str) -> bool:
        toks = set(re.findall(r"\w{4,}", q.lower()))
        for other in seen_q:
            if toks and len(toks & other) / max(1, len(toks | other)) >= 0.6:
                return True
        seen_q.append(toks)
        return False
    for i, (sec, note) in enumerate(zip(sections, notes), 1):
        prog(f"Fiszki: fragment {i}/{n}", 0.60 + 0.25 * (i - 1) / n)
        if not note:
            continue
        share = max(sec.words, 60) / total_words
        k = max(1, min(cards_per_section, round(target * share))) + (1 if sec.marks else 0)
        try:
            raw = chat(flashcards_prompt(note, k, lang), json_mode=True, temperature=0.2)
        except Exception as e:  # noqa: BLE001
            if cancel is not None and cancel.is_set():
                raise
            log.warning("fiszki %d: %s", i, e)
            continue
        for c in parse_flashcards(raw)[:k + 1]:
            if similar(c["q"]):
                continue
            c.update({"section": i, "t": round(sec.start, 1), "known": 0,
                      "category": cat_of.get(i, ""), "topic": title_of.get(i, "")})
            if sec.marks:
                c["marks"] = sec.marks
            cards.append(c)
    # zachowaj postęp nauki fiszek, które się powtarzają (np. po ponownym generowaniu)
    old = {re.sub(r"\W+", "", c["q"].lower()): c for c in lecture.load_flashcards()}
    for c in cards:
        o = old.get(re.sub(r"\W+", "", c["q"].lower()))
        if o:
            for f in ("due", "ivl", "reps", "lapses", "known"):
                if f in o:
                    c[f] = o[f]

    # --- podsumowanie ---
    prog("Podsumowanie wykładu…", 0.86)
    all_notes = "\n\n".join(x for x in notes if x)
    budget = int(num_ctx * 0.55)
    level = 0
    while _est_tokens(all_notes) > budget and level < 3:
        level += 1
        chunks, cur = [], ""
        for block in all_notes.split("\n\n"):
            if cur and _est_tokens(cur + block) > budget // 2:
                chunks.append(cur)
                cur = ""
            cur += block + "\n\n"
        if cur:
            chunks.append(cur)
        condensed = []
        for j, ch in enumerate(chunks, 1):
            prog(f"Podsumowanie: skracanie części {j}/{len(chunks)}", 0.86 + 0.06 * j / len(chunks))
            condensed.append(chat(condense_prompt(ch, lang)))
        all_notes = "\n\n".join(condensed)
    summary = chat(summary_prompt(all_notes, title, subject, lang), on_token=on_token)
    summary = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", summary.strip()).strip()
    summary = re.sub(r"^#\s+[^\n]*\n+", "", summary)       # tytuł dopisany przez model
    summary = re.sub(r"^###\s+", "## ", summary, flags=re.MULTILINE)

    # --- złożenie plików ---
    prog("Zapisywanie…", 0.97)
    lecture.summary_path.write_text(summary + "\n", encoding="utf-8")
    lecture.save_flashcards(cards)
    lecture.notes_path.write_text(assemble_markdown(lecture, sections, notes, summary, marked_notes, exam_items, marks),
                                  encoding="utf-8")
    lecture.meta.notes_model = model
    lecture.meta.edited = False
    lecture.save_meta()
    from .exporters import export_html
    export_html(lecture)
    prog("Gotowe", 1.0)


def _first_line(md: str, limit: int = 240) -> str:
    """Pierwsza treściwa linia notatki (bez znaczników Markdown) – do ramki „zaznaczone przez Ciebie”."""
    for line in (md or "").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or t.startswith("!["):
            continue
        t = re.sub(r"^(?:(?:[-*]|\d+\.)\s+|>\s*)+", "", t)
        t = re.sub(r"^\*\*[^*]{2,30}:\*\*\s*", "", t).strip()
        if len(t) > 8:
            return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def mark_boxes(marks: list[dict], marked_notes: Optional[list], start: float, end: float, lang: str) -> list[str]:
    """Ramki „Ważne · zaznaczone przez Ciebie 31:40” dla zaznaczeń w zakresie [start, end)."""
    from .notes_style import LABELS
    names = mark_names(lang)
    bodies = {id(mk): body for mk, body in (marked_notes or [])}
    by_id = {mk.get("id"): body for mk, body in (marked_notes or [])}
    out = []
    for mk in sorted(marks or [], key=lambda x: x.get("start", 0)):
        t = float(mk.get("start", 0))
        if not (start <= t < end):
            continue
        name = names.get(mk.get("kind"), "") or ""
        label = name if name.lower() in LABELS and LABELS[name.lower()] == "important" else (
            "Important" if lang == "en" else "Ważne")
        who = "marked by you" if lang == "en" else "zaznaczone przez Ciebie"
        extra = f" ({name})" if name and name != label else ""
        body = _first_line(bodies.get(id(mk)) or by_id.get(mk.get("id")) or "")
        out += [f"> **{label}:** *{who}{extra} · {fmt_time(t)}*" + (f" — {body}" if body else ""), ""]
    return out


def assemble_markdown(lecture: Lecture, sections: list[Section], notes: list[str], summary: str,
                      marked_notes: Optional[list] = None, exam_items: Optional[list] = None,
                      marks: Optional[list] = None) -> str:
    lang = lecture_lang(lecture)
    T = texts(lang)
    names = mark_names(lang)
    m = lecture.meta
    try:
        date = datetime.fromisoformat(m.created).strftime("%d.%m.%Y %H:%M")
    except Exception:
        date = m.created
    head = [f"# {m.title}", ""]
    info = " · ".join(x for x in [m.subject, date, fmt_time(m.duration) if m.duration and lecture.audio_parts() else ""]
                      if x)
    if info:
        head += [f"*{info}*", ""]
    out = head + [summary, ""]
    if exam_items:
        out += [f"## {T.exam_info}", ""] + [f"- {x}" for x in exam_items] + [""]
    if marked_notes:
        out += [f"## {T.marked}", ""]
        for mk, body in marked_notes:
            tm = f"{fmt_time(mk['start'])}–{fmt_time(mk.get('end', mk['start']))}"
            out += [f"### ★ {names.get(mk.get('kind'), mk.get('kind'))} · {tm}", "", body, ""]
    out += ["---", "", f"# {T.detailed}", ""]
    # zdjęcia slajdów bez nagrania – czasy są umowne, więc ich nie pokazujemy
    timeline = not (m.kind == "files" and not lecture.audio_parts())
    shown: set[str] = set()
    for i, (sec, note) in enumerate(zip(sections, notes), 1):
        topic, body = "", note or ""
        mm = re.match(r"^\s*###\s+(.+?)\s*(?:\n|$)", body)
        if mm:
            topic, body = mm.group(1).strip(), body[mm.end():].strip()
        star = "★ " if sec.marks else ""
        out.append(f"## {i}. {star}{topic or T.fragment}")
        badge = (" · **" + ", ".join(names.get(k, k) for k in sec.marks) + "**") if sec.marks else ""
        if timeline:
            out.append(f"*{fmt_time(sec.start)}–{fmt_time(sec.end)}*{badge}")
        elif badge:
            out.append(badge.strip(" ·"))
        out.append("")
        from .vision import slide_items
        for sl in sec.slides:
            f = sl.get("file", "")
            if f and f not in shown:
                out += [f"![{T.slide_word} {sl.get('index')}]({f})", ""]
                shown.add(f)
                items = slide_items(sl)
                if len(items) == 1:
                    it = items[0]
                    kind = (it.get("kind") or "").strip()
                    out += [f"> **{T.on_slide}:** " + (f"*{kind[:1].upper() + kind[1:]}* — " if kind else "")
                            + it.get("desc", ""), ""]
                elif items:
                    out += [f"> **{T.on_slide}:**", ">"]
                    for it in items:
                        kind = (it.get("kind") or "").strip()
                        out.append("> - " + (f"*{kind[:1].upper() + kind[1:]}* — " if kind else "") + it.get("desc", ""))
                    out.append("")
            elif f:
                out += [f"*({T.revisit} {sl.get('index')})*", ""]
        if marks:
            out += mark_boxes(marks, marked_notes, sec.start, sec.end if i < len(sections) else 1e12, lang)
        out += [body or T.no_speech, ""]
    return "\n".join(out).strip() + "\n"
