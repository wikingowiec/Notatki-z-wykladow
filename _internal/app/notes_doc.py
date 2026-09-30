"""Struktura notatki: nagłówki, spis treści z odnośnikami, podział na fragmenty (do pytań)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_H = re.compile(r"^(#{1,2})\s+(.+?)\s*(\{#[\w-]+\})?\s*$")
_OLD_SECTION = re.compile(r"^(\d+)\.\s*\[([\d:]+)\s*[–-]\s*[\d:]+\]\s*$")   # stary format: "3. [00:00–01:43]"
_TIME_LINE = re.compile(r"^\*\s*([\d:]+)\s*[–-]\s*([\d:]+)\s*\*")
TOC_TITLE = "Spis treści"
TOC_TITLES = ("spis treści", "contents")


@dataclass
class Heading:
    line: int
    level: int
    text: str
    anchor: str
    label: str            # tekst w spisie treści
    time: str = ""
    topic_line: int = -1  # stary format: linia "### temat" do scalenia z nagłówkiem


@dataclass
class Chunk:
    anchor: str
    title: str
    time: str
    text: str
    lines: list = field(default_factory=list)


def headings(md: str) -> list[Heading]:
    """Nagłówki # i ## (oprócz tytułu i spisu treści) z kotwicami sec-1, sec-2…"""
    lines = md.splitlines()
    out: list[Heading] = []
    first_h1 = True
    n = 0
    in_code = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        m = _H.match(line)
        if not m:
            continue
        level, text = len(m.group(1)), m.group(2).strip()
        if level == 1 and first_h1:
            first_h1 = False
            continue
        if text.lower() in TOC_TITLES:
            continue
        label, time = text, ""
        old = _OLD_SECTION.match(text)
        if old:  # stary format – temat z najbliższego "### "
            time = old.group(2)
            topic_line = next((j for j in range(i + 1, min(len(lines), i + 10)) if lines[j].startswith("### ")), -1)
            topic = lines[topic_line][4:].strip() if topic_line >= 0 else ""
            label = f"{old.group(1)}. {topic}" if topic else text
            out.append(Heading(i, level, text, f"sec-{n + 1}", label, time, topic_line))
            n += 1
            continue
        else:
            nxt = next((l.strip() for l in lines[i + 1:i + 4] if l.strip()), "")
            tm = _TIME_LINE.match(nxt)
            if tm:
                time = tm.group(1)
        n += 1
        out.append(Heading(i, level, text, f"sec-{n}", label, time))
    return out


def with_toc(md: str, include_toc: bool = True, categories: list | None = None) -> str:
    """Dodaje kotwice do nagłówków i (opcjonalnie) klikalny spis treści na początku notatki.
    categories – tematy „Notatek szczegółowych” w spisie pogrupowane w kategorie."""
    if not md.strip():
        return md
    from .topics import clean_md_titles
    md = clean_md_titles(md)
    hs = headings(md)
    if len(hs) < 2:
        return md
    lines = md.splitlines()
    for h in hs:
        if h.topic_line >= 0:   # stary format: temat do nagłówka, czas pod nim
            lines[h.line] = f"## {h.label} {{#{h.anchor}}}"
            lines[h.topic_line] = f"*{h.time}*" if h.time else ""
        elif "{#" not in lines[h.line]:
            lines[h.line] = f"{lines[h.line].rstrip()} {{#{h.anchor}}}"
    if not include_toc:
        return "\n".join(lines)
    title = "Contents" if re.search(r"^# Detailed notes", md, re.MULTILINE) else TOC_TITLE
    toc = [f"## {title}", ""]
    cat_of: dict[int, str] = {}
    for c in categories or []:
        for n in c.get("sections", []):
            cat_of[n] = c.get("name", "")
    last_cat = None
    for h in hs:
        nested = h.level == 2 and any(x.level == 1 and x.line < h.line for x in hs)
        indent = "    " if nested else ""
        t = f" · {h.time}" if h.time else ""
        num = re.match(r"^(\d+)\.", h.label)
        if nested and num and cat_of:
            cat = cat_of.get(int(num.group(1)), "")
            if cat != last_cat and cat:
                toc.append(f"    - **{_esc(cat)}**")
                last_cat = cat
            indent = "        " if cat else indent
        toc.append(f"{indent}- [{_esc(h.label)}](#{h.anchor}){t}")
    toc.append("")
    # wstaw po tytule i linii z informacjami (*przedmiot · data*)
    insert_at = 0
    for i, l in enumerate(lines):
        if l.startswith("# "):
            j = i + 1
            while j < len(lines):
                st = lines[j].strip()
                if not st or (st.startswith("*") and st.endswith("*") and not st.startswith("**")):
                    j += 1
                else:
                    break
            insert_at = j
            break
    return "\n".join(lines[:insert_at] + [""] + toc + lines[insert_at:])


def _esc(s: str) -> str:
    return s.replace("[", "(").replace("]", ")")


def chunks(md: str) -> list[Chunk]:
    """Dzieli notatkę na fragmenty wg nagłówków (do wyszukiwania odpowiedzi)."""
    lines = md.splitlines()
    hs = headings(md)
    out: list[Chunk] = []
    for k, h in enumerate(hs):
        end = hs[k + 1].line if k + 1 < len(hs) else len(lines)
        body = [l for l in lines[h.line + 1:end] if not l.strip().startswith("![")]
        text = "\n".join(body).strip()
        if len(text) < 3:
            continue
        out.append(Chunk(h.anchor, h.label, h.time, text))
    return out
